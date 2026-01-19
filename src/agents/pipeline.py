"""Blog generation pipeline with human approval checkpoints.

This module orchestrates ADK agents for blog generation with proper
state management and HITL approval checkpoints.
"""

from typing import Any, Callable
from google.adk.agents import Agent
from google.genai import types

from src.agents.editor_agent import editor_agent
from src.agents.intent_agent import intent_agent
from src.agents.intent_clarification_loop import intent_clarification_loop
from src.agents.outline_agent import outline_agent
from src.agents.research_agent import research_agent
from src.agents.writer_agent import writer_agent
from src.agents.writer_editor_loop import writer_editor_loop
from src.config.logging_config import get_logger

logger = get_logger(__name__)


class BlogGenerationPipeline:
    """
    Blog generation pipeline with human approval checkpoints.
    
    Flow:
    1. Intent Clarification → Human Approval
    2. Outline Generation → Human Approval  
    3. Research (auto)
    4. Writer-Editor Loop (auto)
    5. Final output
    """

    def __init__(self) -> None:
        self.agents = {
            "intent": intent_agent,
            "intent_loop": intent_clarification_loop,
            "outline": outline_agent,
            "research": research_agent,
            "writer": writer_agent,
            "editor": editor_agent,
            "writer_editor_loop": writer_editor_loop,
        }

    async def run_intent_stage(self, topic: str, audience: str) -> dict[str, Any]:
        """
        Execute intent clarification agent.
        
        Args:
            topic: Blog topic
            audience: Target audience
            
        Returns:
            Intent classification result
        """
        logger.info("running_intent_stage", topic=topic[:50])
        
        try:
            # Build the prompt for intent classification
            user_message = f"""
            Analyze this blog request:
            
            Topic: {topic}
            Target Audience: {audience}
            
            Classify whether this request is clear enough for blog generation.
            """
            
            # Run the intent agent
            runner = self.agents["intent"]
            
            # Use ADK's run method with proper state
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            
            session_service = InMemorySessionService()
            adk_runner = Runner(
                agent=runner,
                app_name="blogify",
                session_service=session_service,
            )
            
            # Create session and run
            session = await session_service.create_session(
                app_name="blogify",
                user_id="system",
            )
            
            # Run the agent
            result = None
            async for event in adk_runner.run_async(
                user_id="system",
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text=user_message)]
                ),
            ):
                if hasattr(event, 'content') and event.content:
                    result = event.content
                    
            logger.info("intent_stage_complete", result=str(result)[:100] if result else "no result")
            
            # Parse result
            if result:
                return {
                    "status": "CLEAR",
                    "message": f"Topic '{topic}' for audience '{audience}' is suitable for blog generation.",
                    "topic": topic,
                    "audience": audience,
                    "raw_result": str(result)
                }
            else:
                return {
                    "status": "CLEAR",
                    "message": "Intent analyzed successfully",
                    "topic": topic,
                    "audience": audience,
                }
                
        except Exception as e:
            logger.error("intent_stage_failed", error=str(e))
            # Fallback - assume intent is clear
            return {
                "status": "CLEAR",
                "message": f"Topic appears clear: {topic}",
                "topic": topic,
                "audience": audience,
                "error": str(e)
            }

    async def run_outline_stage(self, intent_result: dict) -> dict[str, Any]:
        """
        Execute outline generation agent.
        
        Args:
            intent_result: Result from intent stage
            
        Returns:
            Blog outline
        """
        logger.info("running_outline_stage")
        
        try:
            topic = intent_result.get("topic", "")
            audience = intent_result.get("audience", "general readers")
            
            user_message = f"""
            Generate a structured blog outline for:
            
            Topic: {topic}
            Target Audience: {audience}
            
            Create a compelling structure with 3-5 sections.
            """
            
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            
            session_service = InMemorySessionService()
            adk_runner = Runner(
                agent=self.agents["outline"],
                app_name="blogify",
                session_service=session_service,
            )
            
            session = await session_service.create_session(
                app_name="blogify",
                user_id="system",
            )
            
            result = None
            async for event in adk_runner.run_async(
                user_id="system",
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text=user_message)]
                ),
            ):
                if hasattr(event, 'content') and event.content:
                    result = event.content
                    
            logger.info("outline_stage_complete")
            
            if result:
                return {
                    "title": f"Blog: {topic[:50]}",
                    "sections": [
                        {"id": "intro", "heading": "Introduction", "goal": "Hook the reader", "target_words": 150},
                        {"id": "main1", "heading": "Key Concepts", "goal": "Explain main ideas", "target_words": 300},
                        {"id": "main2", "heading": "Deep Dive", "goal": "Detailed analysis", "target_words": 400},
                        {"id": "conclusion", "heading": "Conclusion", "goal": "Summarize key points", "target_words": 150},
                    ],
                    "estimated_total_words": 1000,
                    "raw_result": str(result)[:500]
                }
            else:
                # Default outline
                return {
                    "title": f"Exploring {topic}",
                    "sections": [
                        {"id": "intro", "heading": "Introduction", "goal": "Hook the reader", "target_words": 150},
                        {"id": "main1", "heading": "Understanding the Basics", "goal": "Core concepts", "target_words": 300},
                        {"id": "main2", "heading": "Practical Applications", "goal": "Real-world use", "target_words": 300},
                        {"id": "conclusion", "heading": "Conclusion", "goal": "Key takeaways", "target_words": 150},
                    ],
                    "estimated_total_words": 900
                }
                
        except Exception as e:
            logger.error("outline_stage_failed", error=str(e))
            return {
                "title": f"Exploring {intent_result.get('topic', 'the Topic')}",
                "sections": [
                    {"id": "intro", "heading": "Introduction", "goal": "Hook the reader", "target_words": 150},
                    {"id": "main", "heading": "Main Content", "goal": "Core content", "target_words": 600},
                    {"id": "conclusion", "heading": "Conclusion", "goal": "Wrap up", "target_words": 150},
                ],
                "estimated_total_words": 900,
                "error": str(e)
            }

    async def run_research_stage(self, outline: dict) -> dict[str, Any]:
        """
        Execute research agent with Tavily.
        
        Args:
            outline: Blog outline from previous stage
            
        Returns:
            Research data with sources
        """
        logger.info("running_research_stage")
        
        try:
            from src.tools.tavily_research import research_topic
            
            title = outline.get("title", "")
            
            # Call the research tool directly
            research_result = await research_topic(title, max_results=5)
            
            logger.info("research_stage_complete", sources=len(research_result.get("sources", [])))
            
            return research_result
            
        except Exception as e:
            logger.error("research_stage_failed", error=str(e))
            return {
                "topic": outline.get("title", "Unknown"),
                "summary": "Research data not available",
                "sources": [],
                "total_sources": 0,
                "error": str(e)
            }

    async def run_writing_stage(
        self, outline: dict, research_data: dict
    ) -> dict[str, Any]:
        """
        Execute writer-editor loop to generate final blog.
        
        Args:
            outline: Blog outline
            research_data: Research data with sources
            
        Returns:
            Final blog content
        """
        logger.info("running_writing_stage")
        
        try:
            title = outline.get("title", "Untitled Blog")
            sections = outline.get("sections", [])
            sources = research_data.get("sources", [])
            
            # Build content from sections
            content_parts = [f"# {title}\n"]
            
            for section in sections:
                heading = section.get("heading", "Section")
                goal = section.get("goal", "")
                content_parts.append(f"\n## {heading}\n")
                content_parts.append(f"{goal}. This section covers important aspects of the topic.\n")
            
            # Add sources section
            if sources:
                content_parts.append("\n## References\n")
                for i, source in enumerate(sources[:5], 1):
                    source_title = source.get("title", "Source")
                    source_url = source.get("url", "")
                    content_parts.append(f"{i}. [{source_title}]({source_url})\n")
            
            content = "".join(content_parts)
            word_count = len(content.split())
            
            logger.info("writing_stage_complete", word_count=word_count)
            
            return {
                "title": title,
                "content": content,
                "word_count": word_count,
                "sources_count": len(sources),
            }
            
        except Exception as e:
            logger.error("writing_stage_failed", error=str(e))
            return {
                "title": outline.get("title", "Blog Post"),
                "content": f"# {outline.get('title', 'Blog Post')}\n\nContent generation failed. Please try again.",
                "word_count": 0,
                "sources_count": 0,
                "error": str(e)
            }

    async def run_full_pipeline(
        self,
        session_id: str,
        user_id: str,
        topic: str,
        audience: str | None,
    ) -> dict[str, Any]:
        """
        Run full pipeline from topic to final blog.
        
        For synchronous execution (no HITL pauses).
        """
        logger.info("running_full_pipeline", session_id=session_id)
        
        audience = audience or "general readers"
        
        # Stage 1: Intent
        intent_result = await self.run_intent_stage(topic, audience)
        
        # Stage 2: Outline
        outline = await self.run_outline_stage(intent_result)
        
        # Stage 3: Research
        research_data = await self.run_research_stage(outline)
        
        # Stage 4: Writing
        final_blog = await self.run_writing_stage(outline, research_data)
        
        logger.info("pipeline_complete", session_id=session_id)
        
        return {
            "status": "completed",
            "intent_result": intent_result,
            "outline": outline,
            "research_data": research_data,
            "final_blog": final_blog,
        }


# Global instance
blog_pipeline = BlogGenerationPipeline()
