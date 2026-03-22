"""Internal API routes for Blogify-AI.

These endpoints are called by Blogify backend only.
All endpoints require X-Internal-API-Key header.
"""

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from src.config.logging_config import get_logger
from src.core.task_queue import task_queue, TaskStatus
from src.agents.pipeline import blog_pipeline
from src.monitoring.tracing import trace_span

logger = get_logger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

# Internal API key from environment
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "dev-internal-key")


def verify_internal_key(x_internal_api_key: str = Header(...)):
    """Verify internal API key."""
    if x_internal_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# ============================================
# BLOG GENERATION ENDPOINTS
# ============================================

class BlogGenerationRequest(BaseModel):
    """Request from Blogify to generate a blog."""
    job_id: str = Field(..., description="Job ID from Blogify")
    user_id: str = Field(..., description="User ID from Blogify")
    topic: str = Field(..., min_length=10, max_length=500)
    audience: str = Field(default="general readers")
    tone: str = Field(default="professional")
    user_plan: str = Field(default="free")
    callback_url: str = Field(..., description="Webhook URL for events")


class BlogGenerationAccepted(BaseModel):
    """Response when job is accepted."""
    job_id: str
    accepted: bool = True
    message: str = "Job queued for processing"


@router.post("/ai/blogs", response_model=BlogGenerationAccepted)
async def submit_blog_generation(
    request: BlogGenerationRequest,
    background_tasks: BackgroundTasks,
    _: bool = Header(default=None, alias="X-Internal-API-Key"),
):
    """
    Accept blog generation job from Blogify.
    
    Immediately queues the job and returns 202.
    Processing happens asynchronously with webhook callbacks.
    """
    # Verify API key
    verify_internal_key(_ or "")
    
    logger.info(
        "blog_job_received",
        job_id=request.job_id,
        user_id=request.user_id,
        topic=request.topic[:50],
    )
    
    # Queue the job
    await task_queue.enqueue(
        task_type="blog_generation",
        payload={
            "job_id": request.job_id,
            "user_id": request.user_id,
            "topic": request.topic,
            "audience": request.audience,
            "tone": request.tone,
            "callback_url": request.callback_url,
        },
        task_id=request.job_id,
    )
    
    # Start processing in background
    background_tasks.add_task(
        process_blog_generation,
        request.job_id,
        request.dict(),
    )
    
    return BlogGenerationAccepted(job_id=request.job_id)


async def process_blog_generation(job_id: str, request_data: dict):
    """Background task to process blog generation."""
    import httpx
    
    callback_url = request_data.get("callback_url", "")
    
    try:
        # Update status to processing
        await task_queue.update_task(job_id, status=TaskStatus.PROCESSING)
        
        # Send progress event
        await send_webhook_event(callback_url, {
            "event_type": "job_progress",
            "job_id": job_id,
            "timestamp": datetime.utcnow().isoformat(),
            "progress": {"stage": "intent", "percent": 10}
        })
        
        # Run the pipeline
        with trace_span("blog_generation_job", {"job_id": job_id}):
            result = await blog_pipeline.run_full_pipeline(
                session_id=job_id,
                user_id=request_data.get("user_id", ""),
                topic=request_data.get("topic", ""),
                audience=request_data.get("audience"),
            )
        
        if result.get("status") == "completed":
            final_blog = result.get("final_blog", {})
            
            # Send completion event
            await send_webhook_event(callback_url, {
                "event_type": "job_completed",
                "job_id": job_id,
                "timestamp": datetime.utcnow().isoformat(),
                "result": {
                    "title": final_blog.get("title", "Untitled"),
                    "content": final_blog.get("content", ""),
                    "word_count": final_blog.get("word_count", 0),
                    "sources": [],  # TODO: Extract from research data
                    "outline": result.get("outline", {}),
                }
            })
            
            await task_queue.update_task(
                job_id,
                status=TaskStatus.COMPLETED,
                result=result,
            )
        else:
            raise Exception(result.get("error", "Generation failed"))
            
    except Exception as e:
        logger.error("blog_generation_failed", job_id=job_id, error=str(e))
        
        # Send failure event
        await send_webhook_event(callback_url, {
            "event_type": "job_failed",
            "job_id": job_id,
            "timestamp": datetime.utcnow().isoformat(),
            "error": {
                "code": "GENERATION_FAILED",
                "message": str(e),
                "retryable": True,
            }
        })
        
        await task_queue.update_task(
            job_id,
            status=TaskStatus.FAILED,
            error=str(e),
        )


async def send_webhook_event(callback_url: str, payload: dict):
    """Send webhook event to Blogify."""
    if not callback_url:
        logger.warning("no_callback_url", payload=payload)
        return
    
    import httpx
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                callback_url,
                json=payload,
                headers={
                    "X-Internal-API-Key": INTERNAL_API_KEY,
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("webhook_sent", url=callback_url, event=payload.get("event_type"))
    except Exception as e:
        logger.error("webhook_failed", url=callback_url, error=str(e))
        # TODO: Implement retry queue


@router.get("/ai/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    _: str = Header(default=None, alias="X-Internal-API-Key"),
):
    """
    Get job status (fallback for webhook failures).
    """
    verify_internal_key(_ or "")
    
    status = await task_queue.get_task_status(job_id)
    
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "job_id": job_id,
        "status": status.get("status"),
        "stage": status.get("payload", {}).get("stage"),
        "progress": status.get("progress"),
        "result": status.get("result"),
        "error": status.get("error"),
    }


# ============================================
# CHAT COPILOT ENDPOINTS
# ============================================

class MessageItem(BaseModel):
    """A message in conversation history."""
    role: str
    content: str


class BlogStateContext(BaseModel):
    """Current state of blog being edited."""
    id: str
    title: str
    content: str
    tag: str
    word_count: int
    published: bool


class UserProfileContext(BaseModel):
    """User profile information."""
    id: str
    name: str
    plan: str


class SystemContext(BaseModel):
    """System context for AI reasoning."""
    blog_state: Optional[BlogStateContext] = None
    user_profile: UserProfileContext
    available_commands: list[str]


class ChatRequest(BaseModel):
    """Chat request from Blogify."""
    conversation_id: str
    user_id: str
    user_plan: str
    system_context: SystemContext
    recent_messages: list[MessageItem]
    user_message: str


class AICommand(BaseModel):
    """AI command to be executed."""
    type: str
    payload: dict
    confidence: float
    explanation: str
    requires_approval: bool


class ChatResponse(BaseModel):
    """Chat response to Blogify."""
    assistant_message: str
    commands: list[AICommand]
    reasoning_trace: Optional[str] = None
    tokens_used: int
    model_used: str


@router.post("/ai/chat", response_model=ChatResponse)
async def chat_with_copilot(
    request: ChatRequest,
    _: str = Header(default=None, alias="X-Internal-API-Key"),
):
    """
    Process chat message with AI copilot.
    
    Returns assistant message and optional commands.
    """
    verify_internal_key(_ or "")
    
    logger.info(
        "chat_request",
        conversation_id=request.conversation_id,
        user_id=request.user_id,
        message_length=len(request.user_message),
    )
    
    with trace_span("chat_copilot", {"conversation_id": request.conversation_id}):
        # Build system prompt based on context
        system_prompt = build_chat_system_prompt(request.system_context)
        
        # Build messages for LLM
        messages = []
        for msg in request.recent_messages[-10:]:  # Last 10 messages
            messages.append({"role": msg.role.lower(), "content": msg.content})
        messages.append({"role": "user", "content": request.user_message})
        
        # Call LLM (using Gemini via ADK or direct)
        response_text, commands = await generate_chat_response(
            system_prompt,
            messages,
            request.system_context,
        )
        
        return ChatResponse(
            assistant_message=response_text,
            commands=commands,
            tokens_used=len(response_text.split()),  # Approximate
            model_used="gemini-1.5-flash",
        )


def build_chat_system_prompt(context: SystemContext) -> str:
    """Build system prompt for chat copilot."""
    prompt = """You are an AI writing assistant for a blog platform. You help users write, edit, and improve their blog posts.

CAPABILITIES:
- Edit specific sections of a blog
- Generate outlines
- Rewrite content in different tones
- Optimize for SEO
- Summarize drafts
- Generate title suggestions
- Add sources/citations
- Expand sections

RULES:
1. Be helpful, concise, and professional
2. When suggesting changes, always return structured commands
3. Explain your reasoning before suggesting changes
4. Never make up facts or statistics - ask for verification
5. Respect the user's writing style while improving clarity

AVAILABLE COMMANDS: {commands}
""".format(commands=", ".join(context.available_commands))
    
    if context.blog_state:
        prompt += f"""
CURRENT BLOG CONTEXT:
- Title: {context.blog_state.title}
- Word Count: {context.blog_state.word_count}
- Tag: {context.blog_state.tag}
- Published: {context.blog_state.published}

Blog Content:
{context.blog_state.content[:2000]}...
"""
    
    return prompt


async def generate_chat_response(
    system_prompt: str,
    messages: list[dict],
    context: SystemContext,
) -> tuple[str, list[AICommand]]:
    """Generate chat response using LLM."""
    from google import genai
    import os
    import json
    
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    
    # Format messages for Gemini
    full_prompt = f"{system_prompt}\n\n"
    for msg in messages:
        role = "User" if msg["role"] == "user" else "Assistant"
        full_prompt += f"{role}: {msg['content']}\n\n"
    
    full_prompt += """
Respond with:
1. Your helpful message to the user
2. If you have suggestions, include a JSON block with commands like:
```json
{
  "commands": [
    {
      "type": "COMMAND_TYPE",
      "payload": {...},
      "confidence": 0.95,
      "explanation": "...",
      "requires_approval": true
    }
  ]
}
```
"""
    
    try:
        response = await client.aio.models.generate_content(
            model="gemini-1.5-flash",
            contents=full_prompt,
        )
        
        response_text = response.text
        
        # Extract commands if present
        commands = []
        if "```json" in response_text:
            try:
                json_start = response_text.index("```json") + 7
                json_end = response_text.index("```", json_start)
                json_str = response_text[json_start:json_end].strip()
                data = json.loads(json_str)
                
                for cmd in data.get("commands", []):
                    commands.append(AICommand(
                        type=cmd.get("type", "UNKNOWN"),
                        payload=cmd.get("payload", {}),
                        confidence=cmd.get("confidence", 0.5),
                        explanation=cmd.get("explanation", ""),
                        requires_approval=cmd.get("requires_approval", True),
                    ))
                
                # Remove JSON block from message
                response_text = response_text[:response_text.index("```json")].strip()
            except (ValueError, json.JSONDecodeError):
                pass
        
        return response_text, commands
        
    except Exception as e:
        logger.error("chat_llm_error", error=str(e))
        return "I apologize, but I encountered an error. Please try again.", []
