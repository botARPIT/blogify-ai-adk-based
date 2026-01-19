"""Blog generation pipeline with human approval checkpoints."""

from typing import Any, Callable

from google.adk.agents import Agent

from src.agents.editor_agent import editor_agent
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
    1. Intent Clarification Loop (max 3 iterations) → Human Approval
    2. Outline Generation → Human Approval  
    3. Research
    4. Writer-Editor Loop (automatic refinement)
    5. Final output
    """

    def __init__(self) -> None:
        self.agents = {
            "intent": intent_clarification_loop,
            "outline": outline_agent,
            "research": research_agent,
            "writer_editor_loop": writer_editor_loop,
        }

    async def run_with_approvals(
        self,
        session_id: str,
        user_id: str,
        topic: str,
        audience: str | None,
        approval_callback: Callable[[str, Any], bool] | None = None,
    ) -> dict[str, Any]:
        """
        Run blog generation pipeline with human approval checkpoints.
        
        Args:
            session_id: Session identifier
            user_id: User identifier
            topic: Blog topic
            audience: Target audience
            approval_callback: Optional callback for human approval
        
        Returns:
            Pipeline result with final blog or approval request
        """
        state: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "topic": topic,
            "audience": audience,
        }

        # Step 1: Intent Clarification Loop
        logger.info("intent_clarification_start", session_id=session_id)
        # TODO: Run intent clarification loop
        # intent_result = await self.agents["intent"].run(...)
        # state["intent_result"] = intent_result

        # Human approval checkpoint after intent
        if approval_callback:
            approved = await approval_callback("intent", state)
            if not approved:
                return {"status": "pending_approval", "stage": "intent", "state": state}

        # Step 2: Outline Generation
        logger.info("outline_generation_start", session_id=session_id)
        # TODO: Run outline agent
        # outline_result = await self.agents["outline"].run(...)
        # state["blog_outline"] = outline_result

        # Human approval checkpoint after outline
        if approval_callback:
            approved = await approval_callback("outline", state)
            if not approved:
                return {"status": "pending_approval", "stage": "outline", "state": state}

        # Step 3: Research (no approval needed)
        logger.info("research_start", session_id=session_id)
        # TODO: Run research agent
        # research_result = await self.agents["research"].run(...)
        # state["research_data"] = research_result

        # Step 4: Writer-Editor Loop (automatic)
        logger.info("writing_start", session_id=session_id)
        # TODO: Run writer-editor loop
        # final_result = await self.agents["writer_editor_loop"].run(...)
        # state["editor_review"] = final_result

        return {"status": "completed", "state": state}


# Global instance
blog_pipeline = BlogGenerationPipeline()
