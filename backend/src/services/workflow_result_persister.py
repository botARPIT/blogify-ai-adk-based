"""Transactional persistence for completed workflow segments."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.budget_config import get_model_cost
from src.core.task_queue import BlogJob
from src.models.orm_models import AgentRunStatus, BlogJobPhase, BlogSessionStatus, BlogVersion
from src.models.repositories.agent_run_repository import AgentRunRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_account_repository import BudgetAccountRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.research_sources_repository import ResearchSourcesRepository
from src.models.repositories.session_lease_repository import SessionLeaseRepository
from src.models.repositories.session_reservation_repository import SessionReservationRepository
from src.models.repositories.workflow_outbox_repository import WorkflowOutboxRepository
from src.services.budget_service import BudgetService
from src.workflows.contracts import StageUsage, WorkflowRunResult
from src.workflows.state_schema import build_session_state


class WorkflowResultPersister:
    """Fence and atomically commit a framework-neutral workflow result."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._session_repo = BlogSessionRepository(session)
        self._version_repo = BlogVersionRepository(session)
        self._run_repo = AgentRunRepository(session)
        self._sources_repo = ResearchSourcesRepository(session)
        self._lease_repo = SessionLeaseRepository(session)
        self._outbox_repo = WorkflowOutboxRepository(session)

        budget_repo = BudgetRepository(session)
        account_repo = BudgetAccountRepository(session)
        reservation_repo = SessionReservationRepository(session)
        self._budget_service = BudgetService(
            budget_repo,
            self._session_repo,
            account_repo,
            reservation_repo,
        )

    async def persist_success(self, job: BlogJob, result: WorkflowRunResult) -> None:
        """Commit one workflow checkpoint after verifying exact attempt ownership."""
        await self._lock_attempt(job)
        active_version = await self._version_repo.get_active_for_session(
            job.session_id,
            for_update=True,
        )
        if active_version is None:
            raise ValueError(f"Active blog version missing for session {job.session_id}")

        if job.phase == BlogJobPhase.FRESH_GENERATION.value:
            if result.intent_result and result.intent_result.get("intent_clear") is False:
                await self._persist_agent_rejection(job, result, active_version)
                await self._complete_outbox(job)
                return
            if not result.outline:
                raise ValueError("Fresh generation completed without a valid outline")
            await self._persist_outline_checkpoint(job, result, active_version)
        elif job.phase in {
            BlogJobPhase.RESEARCH_PHASE.value,
            BlogJobPhase.REVISION.value,
        }:
            if not result.final_content:
                raise ValueError(f"{job.phase} completed without final content")
            await self._persist_final_review_checkpoint(job, result, active_version)
        else:
            raise ValueError(f"Unsupported persistence phase: {job.phase}")

        await self._complete_outbox(job)

    async def persist_failure(self, job: BlogJob, error: str) -> None:
        """Persist a terminal failure only while this attempt still owns the work."""
        await self._lock_attempt(job)
        active_version = await self._version_repo.get_active_for_session(
            job.session_id,
            for_update=True,
        )
        if active_version is not None:
            await self._version_repo.update_version_state(
                active_version.id,
                status=BlogSessionStatus.FAILED.value,
                job_phase=job.phase,
                feedback_text=error,
                user_action=None,
                failed=True,
            )
        await self._session_repo.mark_failed(job.session_id, reason=error)
        await self._budget_service.release_all(
            user_id=job.user_id,
            blog_session_id=job.session_id,
        )
        if job.outbox_event_id is not None:
            failed = await self._outbox_repo.fail(
                job.outbox_event_id,
                worker_id=self._require_lease_owner(job),
                error=error,
            )
            if not failed:
                raise RuntimeError("Outbox claim disappeared while persisting failure")

    async def _lock_attempt(self, job: BlogJob) -> None:
        """Acquire locks in one stable order: outbox, blog session, session lease."""
        owner = self._require_lease_owner(job)
        version = self._require_lease_version(job)
        if job.outbox_event_id is not None:
            await self._outbox_repo.lock_current_claim(
                event_id=job.outbox_event_id,
                claim_owner=owner,
            )

        blog_session = await self._session_repo.get_by_id_for_update(job.session_id)
        if blog_session is None:
            raise ValueError(f"Blog session {job.session_id} not found")
        if blog_session.status != BlogSessionStatus.PROCESSING.value:
            from src.services.exceptions import WorkflowOwnershipLostError

            raise WorkflowOwnershipLostError(
                f"Session {job.session_id} is {blog_session.status}, not PROCESSING"
            )

        await self._lease_repo.assert_current_lease(
            session_id=job.session_id,
            lease_owner=owner,
            lease_version=version,
        )

    async def _persist_outline_checkpoint(
        self,
        job: BlogJob,
        result: WorkflowRunResult,
        active_version: BlogVersion,
    ) -> None:
        await self._commit_usage(job, active_version, result.usage)
        snapshot = self._build_state_snapshot(job, result, feedback_text=job.feedback_text)
        await self._version_repo.update_version_state(
            active_version.id,
            status=BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
            job_phase=BlogJobPhase.RESEARCH_PHASE.value,
            title=self._extract_title(result.outline, job.topic),
            outline_data=result.outline or {},
            approved_outline=active_version.approved_outline,
            research_data=self._normalize_research_data(result.research),
            draft_content=result.draft,
            final_content=result.final_content,
            editor_review=result.editor_review,
            feedback_text=job.feedback_text or active_version.feedback_text,
            adk_session_id=job.adk_session_id,
            state_snapshot=snapshot,
        )
        await self._session_repo.sync_active_version_fields(
            job.session_id,
            outline_data=result.outline or {},
            adk_session_id=job.adk_session_id,
        )
        await self._session_repo.update_status(
            job.session_id,
            BlogSessionStatus.AWAITING_OUTLINE_REVIEW,
            current_stage="outline_review",
        )

    async def _persist_agent_rejection(
        self,
        job: BlogJob,
        result: WorkflowRunResult,
        active_version: BlogVersion,
    ) -> None:
        """Commit a completed intent decision that terminally blocks the workflow."""
        reason = "Request rejected by the intent safety and clarity gate"
        await self._commit_usage(
            job,
            active_version,
            result.usage,
            intent_result=result.intent_result,
        )
        await self._version_repo.update_version_state(
            active_version.id,
            status=BlogSessionStatus.AGENT_REJECTED.value,
            job_phase=job.phase,
            feedback_text=reason,
            user_action=None,
            adk_session_id=job.adk_session_id,
            state_snapshot=self._build_state_snapshot(job, result, feedback_text=reason),
        )
        await self._session_repo.mark_agent_rejected(job.session_id, reason=reason)
        await self._budget_service.release_excess(
            user_id=job.user_id,
            blog_session_id=job.session_id,
        )

    async def _persist_final_review_checkpoint(
        self,
        job: BlogJob,
        result: WorkflowRunResult,
        active_version: BlogVersion,
    ) -> None:
        research = self._normalize_research_data(result.research)
        await self._commit_usage(job, active_version, result.usage, research)
        snapshot = self._build_state_snapshot(job, result, feedback_text=job.feedback_text)
        await self._version_repo.update_version_state(
            active_version.id,
            status=BlogSessionStatus.AWAITING_FINAL_REVIEW.value,
            job_phase=job.phase,
            title=self._extract_title(result.outline, job.topic),
            outline_data=result.outline or active_version.outline_data,
            approved_outline=snapshot.get("approved_outline") or active_version.approved_outline,
            research_data=research,
            draft_content=result.draft,
            final_content=result.final_content,
            editor_review=result.editor_review,
            feedback_text=job.feedback_text or active_version.feedback_text,
            user_action=None,
            adk_session_id=job.adk_session_id,
            state_snapshot=snapshot,
        )
        await self._session_repo.sync_active_version_fields(
            job.session_id,
            outline_data=result.outline or {},
            final_content=result.final_content,
            adk_session_id=job.adk_session_id,
        )
        await self._budget_service.release_excess(
            user_id=job.user_id,
            blog_session_id=job.session_id,
        )
        await self._session_repo.update_status(
            job.session_id,
            BlogSessionStatus.AWAITING_FINAL_REVIEW,
            current_stage="final_review",
        )

    async def _complete_outbox(self, job: BlogJob) -> None:
        if job.outbox_event_id is None:
            return
        completed = await self._outbox_repo.complete(
            job.outbox_event_id,
            worker_id=self._require_lease_owner(job),
        )
        if not completed:
            raise RuntimeError("Outbox claim disappeared while committing workflow result")

    async def _commit_usage(
        self,
        job: BlogJob,
        active_version: BlogVersion,
        usage_items: list[StageUsage],
        research_data: dict[str, Any] | None = None,
        intent_result: dict[str, Any] | None = None,
    ) -> None:
        sources = research_data.get("sources", []) if research_data else []
        if sources:
            await self._sources_repo.create_many(
                blog_session_id=job.session_id,
                sources=sources,
            )

        for usage in usage_items:
            if usage.total_tokens <= 0 and usage.latency_ms is None:
                continue
            stage_name = f"v{active_version.version_number}:{usage.stage}"
            existing = await self._run_repo.get_by_session_and_stage(
                job.session_id,
                stage_name,
            )
            if existing and existing.status == AgentRunStatus.COMPLETED:
                continue

            output_snapshot = self._build_run_snapshot(usage, research_data, intent_result)
            cost_usd = Decimal(str(get_model_cost(usage.model, usage.total_tokens)))
            if existing:
                calculated_latency = None
                if existing.started_at:
                    calculated_latency = int(
                        (datetime.now(timezone.utc) - existing.started_at).total_seconds() * 1000
                    )
                latency_ms = (
                    usage.latency_ms if usage.latency_ms is not None else calculated_latency
                )
                await self._run_repo.update(
                    existing.id,
                    total_tokens=usage.total_tokens,
                    cost_usd=float(cost_usd),
                    status=AgentRunStatus.COMPLETED,
                    latency_ms=latency_ms,
                    output_snapshot=output_snapshot,
                )
                run_id = existing.id
            else:
                completed_at = datetime.now(timezone.utc)
                started_at = (
                    completed_at - timedelta(milliseconds=usage.latency_ms)
                    if usage.latency_ms is not None
                    else completed_at
                )
                run = await self._run_repo.create(
                    blog_session_id=job.session_id,
                    stage_name=stage_name,
                    status=AgentRunStatus.COMPLETED,
                    total_tokens=usage.total_tokens,
                    cost_usd=float(cost_usd),
                    latency_ms=usage.latency_ms,
                    output_snapshot=output_snapshot,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                run_id = run.id

            if usage.total_tokens > 0:
                await self._budget_service.commit_stage(
                    user_id=job.user_id,
                    blog_session_id=job.session_id,
                    agent_run_id=run_id,
                    actual_tokens=usage.total_tokens,
                    actual_usd=cost_usd,
                )

    @staticmethod
    def _build_run_snapshot(
        usage: StageUsage,
        research_data: dict[str, Any] | None,
        intent_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store stage telemetry, not a misleading catch-all cost payload."""
        snapshot: dict[str, Any] = {
            "schema_version": 1,
            "stage": usage.stage,
            "execution": {
                "model": usage.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "latency_ms": usage.latency_ms,
            },
        }
        if usage.stage == "research":
            sources = research_data.get("sources", []) if research_data else []
            snapshot["research_evidence"] = {
                "source_count": len(sources),
                "sources": [
                    {
                        "title": source.get("title", ""),
                        "url": source.get("url", ""),
                        "provider": source.get("provider", ""),
                    }
                    for source in sources
                    if isinstance(source, dict)
                ],
            }
        if usage.stage == "intent" and intent_result is not None:
            snapshot["intent_gate"] = {
                "intent_clear": intent_result.get("intent_clear") is True,
                "outcome": "blocked" if intent_result.get("intent_clear") is False else "allowed",
            }
        return snapshot

    def _build_state_snapshot(
        self,
        job: BlogJob,
        result: WorkflowRunResult,
        *,
        feedback_text: str | None,
    ) -> dict[str, Any]:
        return build_session_state(
            topic=job.topic,
            audience=job.audience,
            tone=job.tone,
            intent_result=result.intent_result or {},
            blog_outline=result.outline or {},
            approved_outline=(
                job.approved_outline or {}
                if job.phase == BlogJobPhase.FRESH_GENERATION.value
                else result.outline or job.approved_outline or {}
            ),
            outline_feedback=feedback_text or "",
            outline_review_result={},
            research_data=self._normalize_research_data(result.research),
            blog_draft=result.draft,
            editor_review=result.editor_review or {},
        )

    @staticmethod
    def _extract_title(outline: dict[str, Any] | None, fallback: str) -> str:
        if isinstance(outline, dict):
            title = outline.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        return fallback

    @staticmethod
    def _normalize_research_data(research_data: Any) -> dict[str, Any]:
        if isinstance(research_data, dict):
            return research_data
        if isinstance(research_data, str):
            try:
                parsed = json.loads(research_data)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _require_lease_owner(job: BlogJob) -> str:
        if not job.lease_owner:
            raise ValueError("Workflow job is missing lease_owner")
        return job.lease_owner

    @staticmethod
    def _require_lease_version(job: BlogJob) -> int:
        if job.lease_version is None:
            raise ValueError("Workflow job is missing lease_version")
        return job.lease_version


__all__ = ["WorkflowResultPersister"]
