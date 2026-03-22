"""Blog pipeline executor for worker processes.

Replaces the per-stage executor with a single ``run_pipeline()`` call
that uses ADK-native orchestration.  Cost tracking and blog record
updates are handled here (pipeline_v2 is pure orchestration).
"""

from __future__ import annotations

from typing import Any

from src.agents.pipeline_v2 import CostInfo, PipelineResult, run_pipeline
from src.config.budget_config import get_model_cost
from src.config.logging_config import get_logger
from src.models.repository import db_repository
from src.monitoring.tracing import trace_span

logger = get_logger(__name__)


class StageExecutor:
    """Execute the full blog generation pipeline and persist results.

    The ADK SequentialAgent handles stage-by-stage orchestration
    internally.  This class is responsible for:

    1. Calling ``run_pipeline()``
    2. Persisting results to the database
    3. Recording cost entries
    """

    async def execute_full_pipeline(
        self,
        blog_id: int,
        session_id: str,
        topic: str,
        audience: str = "general readers",
        user_id: str = "anonymous",
    ) -> PipelineResult:
        """Run the entire blog pipeline and persist results.

        Parameters
        ----------
        blog_id:
            Database blog ID for updates.
        session_id:
            External session ID.
        topic:
            Blog topic.
        audience:
            Target audience.
        user_id:
            Real user id — propagated into the ADK session.

        Returns
        -------
        PipelineResult with all stage outputs and cost info.
        """
        with trace_span("stage_executor.full_pipeline", {"blog_id": blog_id, "session_id": session_id}):
            logger.info(
                "pipeline_execution_start",
                blog_id=blog_id,
                session_id=session_id,
                topic=topic[:80],
            )

            # ── Run the pipeline ────────────────────────────────────
            result = await run_pipeline(
                topic=topic,
                audience=audience,
                user_id=user_id,
                session_id=session_id,
            )

            # ── Persist results ─────────────────────────────────────
            if result.error:
                await db_repository.update_blog(
                    session_id=session_id,
                    status="failed",
                )
                logger.error(
                    "pipeline_execution_failed",
                    blog_id=blog_id,
                    session_id=session_id,
                    error=result.error,
                )
                return result

            # Update blog with final content
            title = ""
            if result.outline and isinstance(result.outline, dict):
                title = result.outline.get("title", "")

            word_count = len(result.final_content.split()) if result.final_content else 0
            sources_count = 0
            if result.research and isinstance(result.research, dict):
                sources_count = result.research.get("total_sources", 0)

            total_tokens = sum(c.total_tokens for c in result.costs)
            total_cost_usd = sum(
                get_model_cost(c.model, c.prompt_tokens, c.completion_tokens)
                for c in result.costs
                if c.model
            )

            await db_repository.update_blog(
                session_id=session_id,
                title=title,
                content=result.final_content,
                word_count=word_count,
                sources_count=sources_count,
                status="completed",
                total_cost_usd=total_cost_usd,
                total_tokens=total_tokens,
            )

            # ── Record cost entries ─────────────────────────────────
            await self._record_costs(
                user_id=user_id,
                session_id=session_id,
                blog_id=blog_id,
                costs=result.costs,
            )

            # ── Persist per-stage data for audit trail ──────────────
            stage_data = {
                "intent": result.intent_result,
                "outline": result.outline,
                "research": result.research,
                "draft": result.draft[:500] if result.draft else None,
                "editor_review": result.editor_review,
            }
            await db_repository.update_blog_stage(
                session_id=session_id,
                stage="completed",
                stage_data=stage_data,
            )

            logger.info(
                "pipeline_execution_complete",
                blog_id=blog_id,
                session_id=session_id,
                title=title[:50],
                word_count=word_count,
                total_tokens=total_tokens,
                total_cost_usd=round(total_cost_usd, 6),
            )

            return result

    # -- legacy compat shim for blog_worker.py stage loop --------
    async def execute_stage(
        self,
        blog_id: int,
        stage: str,
    ) -> tuple[dict[str, Any], str]:
        """Legacy shim — runs the full pipeline in a single call.

        ``blog_worker.py`` still drives a stage loop; this shim
        translates a stage-loop call into a single full-pipeline call
        so the worker gets ``("completed", result)`` on the first
        invocation and never re-enters.
        """
        blog = await db_repository.get_blog(blog_id)
        if not blog:
            return {"error": f"Blog {blog_id} not found"}, "failed"

        result = await self.execute_full_pipeline(
            blog_id=blog_id,
            session_id=blog.session_id,
            topic=blog.topic,
            audience=blog.audience or "general readers",
            user_id=getattr(blog, "user_id", "anonymous"),
        )

        if result.error:
            return {"error": result.error}, "failed"

        return {
            "title": result.outline.get("title", "") if result.outline else "",
            "content": result.final_content,
        }, "completed"

    # -- cost recording ------------------------------------------

    async def _record_costs(
        self,
        user_id: str,
        session_id: str,
        blog_id: int,
        costs: list[CostInfo],
    ) -> None:
        """Write cost tracking records for each pipeline stage."""
        for cost in costs:
            if cost.total_tokens == 0:
                continue

            cost_usd = get_model_cost(
                cost.model, cost.prompt_tokens, cost.completion_tokens
            )

            try:
                await db_repository.create_cost_record(
                    user_id=user_id,
                    session_id=session_id,
                    agent_name=cost.stage,
                    model_name=cost.model,
                    prompt_tokens=cost.prompt_tokens,
                    completion_tokens=cost.completion_tokens,
                    total_tokens=cost.total_tokens,
                    cost_usd=cost_usd,
                    blog_id=blog_id,
                )
            except Exception as exc:
                logger.warning(
                    "cost_record_failed",
                    stage=cost.stage,
                    error=str(exc),
                )
