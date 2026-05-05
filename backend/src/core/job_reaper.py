"""DB-authoritative job reaper for stale blog sessions.

PostgreSQL owns job leases and user-visible lifecycle state. Redis is only
used to transport a requeued payload after the database has decided that a
session is safe to reclaim.
"""

from __future__ import annotations

import asyncio

from src.config.logging_config import get_logger
from src.core.task_queue import task_queue
from src.models.orm_models import BlogSessionStatus
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.notification_repository import NotificationRepository
from src.models.repository import get_session_factory
from src.services.notification_service import NotificationService

logger = get_logger(__name__)

STALE_THRESHOLD_SECONDS = 120
REAPER_INTERVAL_SECONDS = 30
MAX_REAP_COUNT = 3


class JobReaper:
    """Async background reaper for stale blog processing sessions."""

    def __init__(
        self,
        stale_threshold: int = STALE_THRESHOLD_SECONDS,
        interval: int = REAPER_INTERVAL_SECONDS,
        max_reap_count: int = MAX_REAP_COUNT,
    ) -> None:
        self.stale_threshold = stale_threshold
        self.interval = interval
        self.max_reap_count = max_reap_count
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the reaper background loop."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "reaper_started",
            stale_threshold=self.stale_threshold,
            interval=self.interval,
        )

    async def stop(self, force: bool = False) -> None:
        """Gracefully stop the reaper.
        
        Args:
            force: If True, force stop without waiting for task completion.
        """
        self._running = False
        if self._task is not None:
            self._task.cancel()
            if force:
                if not self._task.done():
                    self._task.cancel()
                self._task = None
                logger.info("reaper_force_stopped")
            else:
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
        logger.info("reaper_stopped")

    async def _loop(self) -> None:
        """Main reaper loop."""
        while self._running:
            try:
                reaped = await self._reap_cycle()
                if reaped > 0:
                    logger.info("reaper_cycle_complete", reaped=reaped)
            except Exception as e:
                logger.error("reaper_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _reap_cycle(self) -> int:
        """Run one reap cycle and requeue exactly the sessions reclaimed."""
        session_factory = get_session_factory()
        reaped_payloads: list[dict] = []

        async with session_factory() as db:
            async with db.begin():
                repo = BlogSessionRepository(db)
                stale_sessions = await repo.find_stale_processing(
                    threshold_seconds=self.stale_threshold,
                )

                for blog_session in stale_sessions:
                    session_id = blog_session.id
                    old_owner = blog_session.lease.owned_by if blog_session.lease else None
                    old_lease = blog_session.lease.lease_version if blog_session.lease else None
                    old_reap_count = blog_session.lease.reap_count if blog_session.lease else 0

                    if old_reap_count >= self.max_reap_count:
                        logger.warning(
                            "reaper_max_reaps_exceeded",
                            session_id=session_id,
                            lease_version=old_lease,
                            reap_count=old_reap_count,
                            owner=old_owner,
                        )

                        await repo.update_status(
                            session_id,
                            status=BlogSessionStatus.FAILED,
                            current_stage=blog_session.current_stage,
                            error_message=(
                                f"Permanently failed after {old_reap_count} "
                                f"reaps (max {self.max_reap_count})"
                            ),
                        )

                        budget_repo = BudgetRepository(db)
                        await budget_repo.release_reservation(session_id)
                        logger.info(
                            "budget_released_on_permanent_failure",
                            session_id=session_id,
                        )

                        notification_repo = NotificationRepository(db)
                        notification_service = NotificationService(
                            auth_user_repo=AuthUserRepository(db),
                            notification_repo=notification_repo,
                        )
                        try:
                            message = (
                                f"Your blog '{blog_session.topic}' could not be completed "
                                "after multiple attempts. Please try again."
                            )
                            await notification_service.create_for_end_user(
                                end_user=blog_session.end_user,
                                type="session_permanently_failed",
                                title="Blog generation failed permanently",
                                message=message,
                                session_id=session_id,
                            )
                            logger.info(
                                "user_notified_on_permanent_failure",
                                session_id=session_id,
                            )
                        except Exception as notify_err:
                            logger.error(
                                "notification_failed_on_permanent_failure",
                                session_id=session_id,
                                error=str(notify_err),
                            )

                        continue

                    new_lease = await repo.reap_session(session_id)
                    if new_lease is None:
                        continue

                    logger.info(
                        "session_reaped",
                        session_id=session_id,
                        old_owner=old_owner,
                        old_lease=old_lease,
                        new_lease=new_lease,
                    )
                    reaped_payloads.append(
                        {
                            "canonical_session_id": blog_session.id,
                            "session_id": str(blog_session.id),
                            "topic": blog_session.topic,
                            "audience": blog_session.audience or "general readers",
                            "user_id": str(blog_session.end_user_id),
                            "job_phase": "outline_gate",
                            "_reaped": True,
                        }
                    )

        for payload in reaped_payloads:
            try:
                await task_queue.enqueue(
                    task_type="blog_generation",
                    payload=payload,
                )
                logger.info(
                    "reaped_session_requeued",
                    session_id=payload["canonical_session_id"],
                )
            except Exception as e:
                logger.error(
                    "reaper_requeue_failed",
                    session_id=payload["canonical_session_id"],
                    error=str(e),
                )

        return len(reaped_payloads)


job_reaper = JobReaper()
