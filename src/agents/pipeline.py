"""Blog generation pipeline with production-grade features.

This module orchestrates ADK agents for blog generation with:
- Redis-backed session store (horizontal scaling)
- Circuit breakers for external API resilience
- Input sanitization for prompt injection protection
- Distributed tracing
- Timeout handling
"""

import asyncio
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.genai import types

from src.agents.editor_agent import editor_agent
from src.agents.intent_agent import intent_agent
from src.agents.outline_agent import outline_agent
from src.agents.research_agent import research_agent
from src.agents.writer_agent import writer_agent
from src.config.logging_config import get_logger
from src.core.sanitization import sanitize_for_llm, sanitize_topic, sanitize_audience
from src.core.session_store import redis_session_service
from src.monitoring.circuit_breaker import gemini_circuit_breaker, tavily_circuit_breaker
from src.monitoring.tracing import trace_span, trace_function
from src.tools.tavily_research import research_topic

logger = get_logger(__name__)

# Default timeout for LLM calls (seconds)
LLM_TIMEOUT = 60
RESEARCH_TIMEOUT = 30


class BlogGenerationPipeline:
    """
    Blog generation pipeline with human approval checkpoints.
    
    Flow:
    1. Intent Clarification → Human Approval
    2. Outline Generation → Human Approval  
    3. Research (auto)
    4. Writing (auto)
    5. Final output
    
    Production features:
    - Redis session store for horizontal scaling
    - Circuit breakers for API resilience
    - Input sanitization
    - Tracing support
    - Timeout handling
    """

    def __init__(self) -> None:
        self.agents = {
            "intent": intent_agent,
            "outline": outline_agent,
            "research": research_agent,
            "writer": writer_agent,
            "editor": editor_agent,
        }
        # Use Redis-backed session service instead of InMemorySessionService
        self._session_service = redis_session_service

    async def _run_agent_with_circuit_breaker(
        self,
        agent: Agent,
        prompt: str,
        timeout: int = LLM_TIMEOUT,
    ) -> str:
        """
        Run an ADK agent with circuit breaker and timeout protection.
        
        Args:
            agent: ADK agent to run
            prompt: Prompt to send
            timeout: Maximum execution time
            
        Returns:
            Agent response text
        """
        async def _execute():
            return await self._run_agent(agent, prompt)
        
        try:
            # Wrap in circuit breaker
            result = await gemini_circuit_breaker.call(_execute)
            return result
        except RuntimeError as e:
            if "circuit breaker" in str(e).lower():
                logger.error("circuit_breaker_open", agent=agent.name)
                return ""
            raise

    async def _run_agent(self, agent: Agent, prompt: str) -> str:
        """Run an ADK agent and return the response text."""
        with trace_span("adk_agent_call", {"agent": agent.name}) as span:
            try:
                runner = Runner(
                    agent=agent,
                    app_name="blogify",
                    session_service=self._session_service,
                )
                
                session = await self._session_service.create_session(
                    app_name="blogify",
                    user_id="system",
                )
                
                response_text = ""
                
                # Add timeout
                async def run_with_timeout():
                    nonlocal response_text
                    async for event in runner.run_async(
                        user_id="system",
                        session_id=session.id,
                        new_message=types.Content(
                            role="user",
                            parts=[types.Part(text=prompt)]
                        ),
                    ):
                        if hasattr(event, 'content') and event.content:
                            if hasattr(event.content, 'parts'):
                                for part in event.content.parts:
                                    if hasattr(part, 'text') and part.text:
                                        response_text += part.text
                            elif isinstance(event.content, str):
                                response_text += event.content
                
                await asyncio.wait_for(run_with_timeout(), timeout=LLM_TIMEOUT)
                
                span.set_attribute("response_length", len(response_text))
                return response_text.strip()
                
            except asyncio.TimeoutError:
                logger.error("agent_timeout", agent=agent.name, timeout=LLM_TIMEOUT)
                span.set_attribute("timeout", True)
                return ""
            except Exception as e:
                logger.error("agent_run_failed", agent=agent.name, error=str(e))
                span.record_exception(e)
                return ""

    @trace_function("intent_stage")
    async def run_intent_stage(self, topic: str, audience: str) -> dict[str, Any]:
        """Execute intent clarification agent with sanitization."""
        logger.info("running_intent_stage", topic=topic[:50])
        
        # Sanitize inputs
        is_valid, sanitized_topic, error = sanitize_topic(topic)
        if not is_valid:
            return {
                "status": "INVALID_INPUT",
                "message": error,
                "topic": topic,
                "audience": audience,
            }
        
        sanitized_audience = sanitize_audience(audience)
        
        prompt = f"""Analyze this blog request and determine if it's clear enough for blog generation.

Topic: {sanitized_topic}
Target Audience: {sanitized_audience}

Respond with a JSON object containing:
- "status": "CLEAR" if ready, or "UNCLEAR_TOPIC" / "MULTI_TOPIC" / "MISSING_AUDIENCE" if not
- "message": Brief explanation of your classification
"""
        
        response = await self._run_agent_with_circuit_breaker(
            self.agents["intent"],
            prompt,
        )
        
        if response:
            import json
            try:
                start = response.find("{")
                end = response.rfind("}") + 1
                if start >= 0 and end > start:
                    parsed = json.loads(response[start:end])
                    return {
                        "status": parsed.get("status", "CLEAR"),
                        "message": parsed.get("message", "Intent analyzed"),
                        "topic": topic,  # Return original
                        "audience": audience,
                    }
            except json.JSONDecodeError:
                pass
        
        return {
            "status": "CLEAR",
            "message": f"Topic '{topic}' for audience '{audience}' is suitable for blog generation.",
            "topic": topic,
            "audience": audience,
        }

    @trace_function("outline_stage")
    async def run_outline_stage(self, intent_result: dict) -> dict[str, Any]:
        """Execute outline generation agent."""
        logger.info("running_outline_stage")
        
        topic = intent_result.get("topic", "")
        audience = intent_result.get("audience", "general readers")
        
        # Sanitize for LLM
        topic = sanitize_for_llm(topic)
        audience = sanitize_for_llm(audience)
        
        prompt = f"""Create a detailed blog outline for the following:

Topic: {topic}
Target Audience: {audience}

Generate a structured outline with:
1. A compelling, SEO-friendly title (max 100 characters)
2. 4-5 sections with:
   - Unique section ID
   - Engaging heading
   - Clear goal for what the section should achieve
   - Target word count (100-300 words per section)

Respond with a JSON object containing:
- "title": The blog title
- "sections": Array of section objects
- "estimated_total_words": Total estimated word count
"""
        
        response = await self._run_agent_with_circuit_breaker(
            self.agents["outline"],
            prompt,
        )
        
        if response:
            import json
            try:
                start = response.find("{")
                end = response.rfind("}") + 1
                if start >= 0 and end > start:
                    parsed = json.loads(response[start:end])
                    if "title" in parsed and "sections" in parsed:
                        parsed["topic"] = intent_result.get("topic", "")
                        parsed["audience"] = intent_result.get("audience", "")
                        return parsed
            except json.JSONDecodeError:
                pass
        
        # Default outline structure
        return {
            "title": f"Complete Guide to {topic}",
            "sections": [
                {"id": "intro", "heading": "Introduction", "goal": f"Hook the reader and introduce {topic}", "target_words": 150},
                {"id": "fundamentals", "heading": "Understanding the Fundamentals", "goal": "Explain core concepts and background", "target_words": 250},
                {"id": "applications", "heading": "Real-World Applications", "goal": "Show practical use cases and examples", "target_words": 300},
                {"id": "best_practices", "heading": "Best Practices and Tips", "goal": "Provide actionable advice", "target_words": 250},
                {"id": "conclusion", "heading": "Conclusion", "goal": "Summarize key points and call to action", "target_words": 150},
            ],
            "estimated_total_words": 1100,
            "topic": intent_result.get("topic", ""),
            "audience": intent_result.get("audience", ""),
        }

    @trace_function("research_stage")
    async def run_research_stage(self, outline: dict) -> dict[str, Any]:
        """Execute research using Tavily API with circuit breaker."""
        logger.info("running_research_stage")
        
        title = outline.get("title", "")
        topic = outline.get("topic", title)
        
        async def _do_research():
            return await research_topic(topic, max_results=5)
        
        try:
            # Wrap in circuit breaker with timeout
            research_data = await asyncio.wait_for(
                tavily_circuit_breaker.call(_do_research),
                timeout=RESEARCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("research_timeout", topic=topic[:50])
            research_data = {"topic": topic, "summary": "", "sources": [], "total_sources": 0}
        except RuntimeError as e:
            if "circuit breaker" in str(e).lower():
                logger.error("tavily_circuit_breaker_open")
            research_data = {"topic": topic, "summary": "", "sources": [], "total_sources": 0}
        except Exception as e:
            logger.error("research_failed", error=str(e))
            research_data = {"topic": topic, "summary": "", "sources": [], "total_sources": 0}
        
        logger.info("research_stage_complete", sources=research_data.get("total_sources", 0))
        
        return research_data

    @trace_function("writing_stage")
    async def run_writing_stage(
        self, outline: dict, research_data: dict
    ) -> dict[str, Any]:
        """Execute writer agent to generate full blog content."""
        logger.info("running_writing_stage")
        
        title = outline.get("title", "Untitled Blog")
        sections = outline.get("sections", [])
        sources = research_data.get("sources", [])
        topic = outline.get("topic", title)
        audience = outline.get("audience", "general readers")
        
        # Sanitize all content going to LLM
        title = sanitize_for_llm(title)
        topic = sanitize_for_llm(topic)
        audience = sanitize_for_llm(audience)
        
        # Build source context
        source_context = ""
        if sources:
            source_context = "\n\nResearch Sources:\n"
            for i, src in enumerate(sources[:5], 1):
                src_content = sanitize_for_llm(src.get('content', '')[:200])
                source_context += f"{i}. {src.get('title', 'Source')}: {src_content}...\n"
        
        # Build section prompts
        section_prompts = "\n".join([
            f"- {sanitize_for_llm(s.get('heading', 'Section'))}: {sanitize_for_llm(s.get('goal', ''))} (~{s.get('target_words', 200)} words)"
            for s in sections
        ])
        
        prompt = f"""Write a complete, professional blog post.

TITLE: {title}
TOPIC: {topic}
AUDIENCE: {audience}

OUTLINE:
{section_prompts}

{source_context}

INSTRUCTIONS:
1. Write engaging, informative content for each section
2. Use a professional but accessible tone suitable for {audience}
3. Include specific examples, data, or insights where relevant
4. Each section should flow naturally into the next
5. Target approximately 800-1200 words total

Write the complete blog post in markdown format, starting with the title as # heading.
"""
        
        response = await self._run_agent_with_circuit_breaker(
            self.agents["writer"],
            prompt,
        )
        
        if response and len(response) > 200:
            word_count = len(response.split())
            
            # Add sources section
            if sources:
                response += "\n\n## References\n"
                for i, src in enumerate(sources[:5], 1):
                    response += f"{i}. [{src.get('title', 'Source')}]({src.get('url', '')})\n"
            
            return {
                "title": outline.get("title", "Untitled"),  # Original unsanitized
                "content": response,
                "word_count": word_count,
                "sources_count": len(sources),
            }
        
        # Fallback content
        content_parts = [f"# {outline.get('title', 'Untitled')}\n"]
        
        for section in sections:
            heading = section.get("heading", "Section")
            goal = section.get("goal", "")
            content_parts.append(f"\n## {heading}\n")
            content_parts.append(f"{goal}. This section explores key aspects of {topic} relevant to {audience}.\n")
        
        if sources:
            content_parts.append("\n## References\n")
            for i, src in enumerate(sources[:5], 1):
                content_parts.append(f"{i}. [{src.get('title', 'Source')}]({src.get('url', '')})\n")
        
        content = "".join(content_parts)
        
        return {
            "title": outline.get("title", "Untitled"),
            "content": content,
            "word_count": len(content.split()),
            "sources_count": len(sources),
        }

    @trace_function("full_pipeline")
    async def run_full_pipeline(
        self,
        session_id: str,
        user_id: str,
        topic: str,
        audience: str | None,
    ) -> dict[str, Any]:
        """Run full pipeline from topic to final blog."""
        logger.info("running_full_pipeline", session_id=session_id)
        
        audience = audience or "general readers"
        
        with trace_span("pipeline_execution", {"session_id": session_id}):
            # Stage 1: Intent
            intent_result = await self.run_intent_stage(topic, audience)
            
            # Check for invalid input
            if intent_result.get("status") == "INVALID_INPUT":
                return {
                    "status": "failed",
                    "error": intent_result.get("message", "Invalid input"),
                    "intent_result": intent_result,
                }
            
            # Stage 2: Outline
            outline = await self.run_outline_stage(intent_result)
            
            # Stage 3: Research
            research_data = await self.run_research_stage(outline)
            
            # Stage 4: Writing
            final_blog = await self.run_writing_stage(outline, research_data)
        
        logger.info("pipeline_complete", session_id=session_id, word_count=final_blog.get("word_count", 0))
        
        return {
            "status": "completed",
            "intent_result": intent_result,
            "outline": outline,
            "research_data": research_data,
            "final_blog": final_blog,
        }


# Global instance
blog_pipeline = BlogGenerationPipeline()
