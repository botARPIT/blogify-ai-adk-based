"""Stage executor for pipeline stages.

Executes individual pipeline stages and handles state transitions.
Used by the worker process.
"""

from typing import Any, Tuple

from src.agents.pipeline import BlogGenerationPipeline
from src.config.logging_config import get_logger
from src.models.repository import db_repository
from src.monitoring.tracing import trace_span

logger = get_logger(__name__)

# Stage transition map
STAGE_TRANSITIONS = {
    "intent": "outline",
    "outline": "research",
    "research": "writing",
    "writing": "completed",
}


class StageExecutor:
    """
    Executes individual pipeline stages.
    
    Each stage is independently executable and persists its
    results to the database before returning.
    """
    
    def __init__(self):
        """Initialize with pipeline instance."""
        self.pipeline = BlogGenerationPipeline()
    
    async def execute_stage(
        self,
        blog_id: int,
        stage: str,
    ) -> Tuple[dict[str, Any], str]:
        """
        Execute a single pipeline stage.
        
        Args:
            blog_id: Blog database ID
            stage: Stage to execute ('intent', 'outline', 'research', 'writing')
            
        Returns:
            Tuple of (result_data, next_stage)
            next_stage can be: 'outline', 'research', 'writing', 'completed', 'failed'
        """
        with trace_span(f"stage_execution_{stage}", {"blog_id": blog_id}):
            
            # Fetch blog from database
            blog = await db_repository.get_blog(blog_id)
            
            if not blog:
                logger.error("blog_not_found", blog_id=blog_id)
                return {"error": f"Blog {blog_id} not found"}, "failed"
            
            logger.info(
                "stage_execution_start",
                blog_id=blog_id,
                session_id=blog.session_id,
                stage=stage,
            )
            
            try:
                # Execute the appropriate stage
                if stage == "intent":
                    result = await self._run_intent(blog)
                elif stage == "outline":
                    result = await self._run_outline(blog)
                elif stage == "research":
                    result = await self._run_research(blog)
                elif stage == "writing":
                    result = await self._run_writing(blog)
                else:
                    logger.error("unknown_stage", stage=stage)
                    return {"error": f"Unknown stage: {stage}"}, "failed"
                
                # Check for stage failure
                if result.get("status") == "INVALID_INPUT":
                    return result, "failed"
                
                # Determine next stage
                next_stage = STAGE_TRANSITIONS.get(stage, "failed")
                
                logger.info(
                    "stage_execution_complete",
                    blog_id=blog_id,
                    stage=stage,
                    next_stage=next_stage,
                )
                
                return result, next_stage
                
            except Exception as e:
                logger.error(
                    "stage_execution_error",
                    blog_id=blog_id,
                    stage=stage,
                    error=str(e),
                )
                
                # Update blog with error
                await db_repository.update_blog(
                    session_id=blog.session_id,
                    status="failed",
                )
                
                return {"error": str(e)}, "failed"
    
    async def _run_intent(self, blog) -> dict[str, Any]:
        """
        Run intent clarification stage.
        
        Analyzes the topic and audience to determine if the
        request is clear enough for blog generation.
        """
        result = await self.pipeline.run_intent_stage(
            topic=blog.topic,
            audience=blog.audience or "general readers",
        )
        
        # Persist stage data
        await db_repository.update_blog_stage(
            session_id=blog.session_id,
            stage="intent",
            stage_data=result,
        )
        
        return result
    
    async def _run_outline(self, blog) -> dict[str, Any]:
        """
        Run outline generation stage.
        
        Creates a structured outline with sections based on
        the intent from the previous stage.
        """
        # Get intent data from previous stage
        intent_data = blog.stage_data or {}
        
        # Add topic/audience if not present
        if "topic" not in intent_data:
            intent_data["topic"] = blog.topic
        if "audience" not in intent_data:
            intent_data["audience"] = blog.audience or "general readers"
        
        result = await self.pipeline.run_outline_stage(intent_data)
        
        # Persist stage data
        await db_repository.update_blog_stage(
            session_id=blog.session_id,
            stage="outline",
            stage_data=result,
        )
        
        return result
    
    async def _run_research(self, blog) -> dict[str, Any]:
        """
        Run research stage.
        
        Uses Tavily API to gather relevant sources and information
        about the topic.
        """
        # Get outline from previous stage
        outline_data = blog.stage_data or {}
        
        result = await self.pipeline.run_research_stage(outline_data)
        
        # Persist stage data (keep outline, add research)
        merged_data = {
            **outline_data,
            "research": result,
        }
        
        await db_repository.update_blog_stage(
            session_id=blog.session_id,
            stage="research",
            stage_data=merged_data,
        )
        
        return result
    
    async def _run_writing(self, blog) -> dict[str, Any]:
        """
        Run writing stage - final content generation.
        
        Uses the outline and research to generate the full
        blog post content.
        """
        # Get accumulated data from previous stages
        stage_data = blog.stage_data or {}
        
        # Extract outline and research
        outline = {
            "title": stage_data.get("title", f"Guide to {blog.topic}"),
            "sections": stage_data.get("sections", []),
            "topic": stage_data.get("topic", blog.topic),
            "audience": stage_data.get("audience", blog.audience),
        }
        
        research_data = stage_data.get("research", {
            "sources": [],
            "summary": "",
        })
        
        result = await self.pipeline.run_writing_stage(outline, research_data)
        
        # Update blog with final content
        await db_repository.update_blog(
            session_id=blog.session_id,
            title=result.get("title"),
            content=result.get("content"),
            word_count=result.get("word_count", 0),
            sources_count=result.get("sources_count", 0),
            status="completed",
        )
        
        logger.info(
            "blog_generation_complete",
            session_id=blog.session_id,
            title=result.get("title", "")[:50],
            word_count=result.get("word_count", 0),
        )
        
        return result
