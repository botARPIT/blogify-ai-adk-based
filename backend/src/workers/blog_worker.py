"""Background worker for blog generation jobs.

This worker process consumes jobs from Redis queue and executes
the full LLM pipeline. No LLM calls happen in the API layer.

Features:
- Visibility timeout for crash recovery
- Automatic job reclaim
- Per-stage execution with DB persistence
- Graceful shutdown

Usage:
    python -m src.workers.blog_worker
    python -m src.workers.blog_worker worker-001
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import uuid

# Load environment before other imports
from dotenv import load_dotenv
env = os.getenv("ENVIRONMENT", "dev")
load_dotenv(f".env.{env}")

from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.job_reaper import job_reaper
from src.core.startup import StartupCheckError, runtime_manager
from src.core.task_queue import task_queue, TaskStatus
from src.models.orm_models import BlogSessionStatus
from src.models.orm_models import EndUser
from src.models.repository import db_repository, get_session_factory
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.notification_repository import NotificationRepository
from src.services.budget_service import BudgetService
from src.services.notification_service import NotificationService

# Lease heartbeat configuration
HEARTBEAT_INTERVAL = 15  # seconds between heartbeat updates

setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
logger = get_logger(__name__)

# Worker configuration
POLL_INTERVAL = 1  # seconds

# BACKPRESSURE: Limit concurrent jobs per worker
# Prevents CPU/memory/token exhaustion
MAX_CONCURRENT_JOBS = 3
job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

# Shutdown flag
shutdown_requested = False

# Active jobs counter
active_jobs = 0



async def run_worker(worker_id: str | None = None):
    """
    Main worker loop.
    
    Args:
        worker_id: Unique worker identifier (generated if not provided)
    """
    global shutdown_requested
    
    if worker_id is None:
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    
    logger.info("worker_starting", worker_id=worker_id, pid=os.getpid())
    
    try:
        await runtime_manager.prepare_worker(worker_id, os.getpid())
        await runtime_manager.start_worker_heartbeat(worker_id, lambda: active_jobs)
    except StartupCheckError as exc:
        logger.error("worker_startup_checks_failed", report=exc.report.to_dict())
        return 1
    except Exception as e:
        logger.error("worker_startup_failed", error=str(e))
        return 1
    
    jobs_processed = 0
    try:
        # Start DB-authoritative job reaper (replaces Redis-only reclaim)
        await job_reaper.start()

        from src.workers.stage_executor import StageExecutor

        executor = StageExecutor()
        
        logger.info(
            "worker_ready",
            worker_id=worker_id,
            max_concurrent_jobs=MAX_CONCURRENT_JOBS,
        )
        print(f"🚀 Worker {worker_id} ready (max {MAX_CONCURRENT_JOBS} concurrent jobs)")
        
        while not shutdown_requested:
            try:
                # BACKPRESSURE: Check if we have capacity before claiming
                if job_semaphore.locked() and job_semaphore._value == 0:
                    await asyncio.sleep(0.1)
                    continue
                
                job = await task_queue.dequeue(timeout=POLL_INTERVAL)
                
                if job is None:
                    continue
                
                logger.info(
                    "job_claimed",
                    job_id=job["id"],
                    worker_id=worker_id,
                    job_type=job.get("type", "unknown"),
                    semaphore_available=job_semaphore._value,
                )
                print(f"📥 Claimed job {job['id'][:8]}...")
                
                asyncio.create_task(
                    process_with_semaphore(job, executor, worker_id)
                )
                jobs_processed += 1
                
            except asyncio.CancelledError:
                logger.info("worker_cancelled", worker_id=worker_id)
                break
            except Exception as e:
                logger.error("worker_loop_error", error=str(e))
                await asyncio.sleep(POLL_INTERVAL)
    except Exception as e:
        logger.error("worker_runtime_failed", worker_id=worker_id, error=str(e))
        return 1
    finally:
        print(f"⏳ Waiting for active jobs to complete...")
        while job_semaphore._value < MAX_CONCURRENT_JOBS:
            await asyncio.sleep(0.5)

        await job_reaper.stop()
        await runtime_manager.shutdown_worker(worker_id)

        logger.info(
            "worker_shutdown_complete",
            worker_id=worker_id,
            jobs_processed=jobs_processed,
        )
        print(f"👋 Worker {worker_id} shutdown. Processed {jobs_processed} jobs.")

    return 0


async def process_with_semaphore(job: dict, executor: StageExecutor, worker_id: str):
    """
    Process job with semaphore protection.
    
    Ensures we never exceed MAX_CONCURRENT_JOBS active jobs.
    """
    global active_jobs
    
    async with job_semaphore:
        active_jobs += 1
        try:
            await process_full_blog(job, executor, worker_id)
        finally:
            active_jobs -= 1


async def _run_heartbeat(
    canonical_session_id: int,
    lease_version: int,
    worker_id: str,
) -> asyncio.Event:
    """Run a background heartbeat loop for a leased session.

    Returns a stop event — set it to terminate the loop.
    Also returns a 'stale' flag via the event's internal state.
    """
    stop_event = asyncio.Event()
    stop_event._lease_valid = True  # type: ignore[attr-defined]

    async def _beat():
        while not stop_event.is_set():
            try:
                async with get_session_factory()() as db:
                    async with db.begin():
                        repo = BlogSessionRepository(db)
                        alive = await repo.heartbeat(
                            canonical_session_id, lease_version, worker_id
                        )
                        if not alive:
                            logger.warning(
                                "heartbeat_lease_lost",
                                session_id=canonical_session_id,
                                lease_version=lease_version,
                                worker_id=worker_id,
                            )
                            stop_event._lease_valid = False  # type: ignore[attr-defined]
                            stop_event.set()
                            return
            except Exception as e:
                logger.error(
                    "heartbeat_error",
                    session_id=canonical_session_id,
                    error=str(e),
                )
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    asyncio.create_task(_beat())
    return stop_event


async def process_full_blog(job: dict, executor: StageExecutor, worker_id: str):
    """
    Process a complete blog generation (all stages).
    
    Runs all pipeline stages in sequence:
    intent → outline → research → writing → completed

    Uses DB-authoritative lease ownership:
    - Claims session with SELECT FOR UPDATE before processing
    - Runs per-job heartbeat to prove liveness
    - Verifies lease on complete/fail to reject stale workers
    """
    job_id = job["id"]
    payload = job.get("payload", {})
    blog_id = payload.get("blog_id")
    session_id = payload.get("session_id", "unknown")
    canonical_session_id = payload.get("canonical_session_id")
    topic = payload.get("topic", "")
    audience = payload.get("audience", "general readers")
    user_id = payload.get("user_id", "anonymous")
    job_phase = payload.get("job_phase", "outline_gate")
    invocation_id = payload.get("invocation_id")
    confirmation_request_id = payload.get("confirmation_request_id")
    approved_outline = payload.get("approved_outline")
    outline_feedback = payload.get("outline_feedback")
    
    if not blog_id and canonical_session_id is None:
        logger.error("job_missing_blog_id", job_id=job_id)
        await task_queue.update_task(job_id, status=TaskStatus.FAILED, error="Missing blog_id")
        return
    
    # ── Lease claim (DB-authoritative) ──────────────────────────────
    lease_version: int | None = None
    heartbeat_stop: asyncio.Event | None = None

    if canonical_session_id is not None:
        async with get_session_factory()() as db:
            async with db.begin():
                repo = BlogSessionRepository(db)
                lease_version = await repo.claim_session(
                    canonical_session_id, worker_id
                )
        if lease_version is None:
            logger.warning(
                "claim_rejected",
                session_id=canonical_session_id,
                worker_id=worker_id,
            )
            return
        logger.info(
            "session_claimed",
            session_id=canonical_session_id,
            worker_id=worker_id,
            lease_version=lease_version,
        )
        # Start per-job heartbeat loop
        heartbeat_stop = await _run_heartbeat(
            canonical_session_id, lease_version, worker_id
        )

    current_stage = "intent"
    
    try:
        # Update Redis job status
        await task_queue.update_task(job_id, status=TaskStatus.PROCESSING)
        
        # Update blog status (legacy path)
        if blog_id is not None:
            await db_repository.update_blog(session_id=session_id, status="processing")
        if canonical_session_id is not None:
            await _update_canonical_session_status(
                canonical_session_id=canonical_session_id,
                status=BlogSessionStatus.PROCESSING,
                current_stage=current_stage,
            )
        
        print(f"🔄 Processing blog {session_id[:8]} - Topic: {topic[:50]}...")
        
        # Run all stages in sequence
        while current_stage != "completed" and current_stage != "failed":
            logger.info(
                "executing_stage",
                job_id=job_id,
                blog_id=blog_id,
                stage=current_stage,
            )
            print(f"  ➡️  Stage: {current_stage}")
            
            # Check if our lease is still valid before each stage
            if heartbeat_stop is not None and not heartbeat_stop._lease_valid:  # type: ignore[attr-defined]
                logger.warning(
                    "lease_lost_before_stage",
                    session_id=canonical_session_id,
                    stage=current_stage,
                )
                return  # Silently exit — reaper has taken over

            # Extend Redis visibility timeout before each stage
            await task_queue.extend_visibility(job_id, 300)
            
            # Execute the stage
            if blog_id is not None:
                result, next_stage = await executor.execute_stage(
                    blog_id,
                    current_stage,
                    canonical_session_id=canonical_session_id,
                )
            else:
                if job_phase == "resume_after_outline":
                    pipeline_result = await executor.execute_resume_from_outline(
                        session_id=session_id,
                        topic=topic,
                        audience=audience,
                        user_id=user_id,
                        canonical_session_id=canonical_session_id,
                        invocation_id=invocation_id,
                        confirmation_request_id=confirmation_request_id,
                        approved_outline=approved_outline,
                        feedback_text=outline_feedback,
                    )
                else:
                    pipeline_result = await executor.execute_full_pipeline(
                        blog_id=None,
                        session_id=session_id,
                        topic=topic,
                        audience=audience,
                        user_id=user_id,
                        canonical_session_id=canonical_session_id,
                    )
                if pipeline_result.error:
                    raise Exception(pipeline_result.error)
                result = {
                    "session_id": session_id,
                    "job_phase": job_phase,
                    "paused_for_confirmation": pipeline_result.paused_for_confirmation,
                }
                next_stage = "completed"
            
            if next_stage == "failed":
                raise Exception(result.get("error", "Stage execution failed"))
            
            logger.info(
                "stage_completed",
                job_id=job_id,
                stage=current_stage,
                next_stage=next_stage,
            )
            
            current_stage = next_stage
        
        # ── Lease-verified completion ────────────────────────────────
        if heartbeat_stop is not None:
            heartbeat_stop.set()  # Stop heartbeat loop

        if canonical_session_id is not None and lease_version is not None:
            async with get_session_factory()() as db:
                async with db.begin():
                    repo = BlogSessionRepository(db)
                    accepted = await repo.complete_with_lease(
                        canonical_session_id, lease_version, worker_id
                    )
            if not accepted:
                logger.warning(
                    "stale_worker_completion_rejected",
                    session_id=canonical_session_id,
                    lease_version=lease_version,
                    worker_id=worker_id,
                )
                return

        # Update Redis job status
        await task_queue.update_task(
            job_id,
            status=TaskStatus.COMPLETED,
            result={"session_id": session_id, "blog_id": blog_id, "job_phase": job_phase},
        )

        logger.info("job_completed", job_id=job_id, blog_id=blog_id, job_phase=job_phase)
        if result.get("paused_for_confirmation"):
            print(f"📝 Blog {session_id[:8]} paused for outline review.")
        else:
            print(f"✅ Blog {session_id[:8]} completed!")
        
    except Exception as e:
        # Stop heartbeat on failure path
        if heartbeat_stop is not None:
            heartbeat_stop.set()

        logger.error(
            "job_processing_failed",
            job_id=job_id,
            blog_id=blog_id,
            stage=current_stage,
            error=str(e),
        )
        print(f"❌ Job failed at stage {current_stage}: {str(e)[:100]}")
        
        await handle_job_failure(
            job, str(e), current_stage,
            lease_version=lease_version,
            worker_id=worker_id,
        )


async def handle_job_failure(
    job: dict,
    error: str,
    stage: str = "unknown",
    *,
    lease_version: int | None = None,
    worker_id: str | None = None,
):
    """
    Handle job failure with retry logic + lease verification.
    
    Uses exponential backoff for retries.
    Moves to dead letter queue after max attempts.
    If a lease is active, verifies ownership before mutating DB state.
    """
    job_id = job["id"]
    payload = job.get("payload", {})
    session_id = payload.get("session_id", "unknown")
    canonical_session_id = payload.get("canonical_session_id")
    attempts = job.get("retries", 0) + 1
    max_attempts = job.get("max_retries", 3)
    
    # Update blog with error (legacy path)
    if payload.get("blog_id") is not None:
        await db_repository.update_blog(
            session_id=session_id,
            status="failed",
        )

    if attempts < max_attempts:
        # Retry — use lease-verified requeue if we have a lease
        if canonical_session_id is not None and lease_version is not None and worker_id is not None:
            async with get_session_factory()() as db:
                async with db.begin():
                    repo = BlogSessionRepository(db)
                    accepted = await repo.fail_with_lease(
                        canonical_session_id, lease_version, worker_id,
                        requeue=True,
                    )
            if not accepted:
                logger.warning(
                    "stale_worker_retry_rejected",
                    session_id=canonical_session_id,
                    lease_version=lease_version,
                    worker_id=worker_id,
                )
                return

        logger.info(
            "job_retry_scheduled",
            job_id=job_id,
            attempt=attempts,
            max_attempts=max_attempts,
        )
        print(f"🔄 Retry scheduled ({attempts}/{max_attempts})")
        
        await task_queue.requeue(job_id)
        
    else:
        # Max retries exceeded - fail permanently
        logger.error(
            "job_max_retries_exceeded",
            job_id=job_id,
            attempts=attempts,
            error=error,
        )
        print(f"💀 Max retries exceeded. Job failed permanently.")

        if canonical_session_id is not None:
            await _release_and_fail_canonical_session(
                canonical_session_id=canonical_session_id,
                current_stage=stage,
                error=error,
            )
        
        await task_queue.update_task(
            job_id,
            status=TaskStatus.FAILED,
            error=f"Max retries exceeded at stage {stage}: {error}",
        )


async def _update_canonical_session_status(
    canonical_session_id: int,
    status: BlogSessionStatus,
    current_stage: str | None,
) -> None:
    async with db_repository.async_session() as session:
        async with session.begin():
            session_repo = BlogSessionRepository(session)
            await session_repo.update_status(
                canonical_session_id,
                status=status,
                current_stage=current_stage,
            )


async def _release_and_fail_canonical_session(
    canonical_session_id: int,
    current_stage: str,
    error: str,
) -> None:
    async with db_repository.async_session() as session:
        async with session.begin():
            session_repo = BlogSessionRepository(session)
            budget_service = BudgetService(
                budget_repo=BudgetRepository(session),
                session_repo=session_repo,
            )
            blog_session = await session_repo.get_by_id(canonical_session_id)
            if blog_session is None:
                return

            await session_repo.update_status(
                canonical_session_id,
                status=BlogSessionStatus.FAILED,
                current_stage=current_stage,
            )
            await budget_service.release(
                tenant_id=blog_session.tenant_id,
                end_user_id=blog_session.end_user_id,
                blog_session_id=canonical_session_id,
                reserved_usd=blog_session.budget_reserved_usd,
                reserved_tokens=blog_session.budget_reserved_tokens,
                already_spent_usd=blog_session.budget_spent_usd,
                already_spent_tokens=blog_session.budget_spent_tokens,
            )
            notification_service = NotificationService(
                auth_user_repo=AuthUserRepository(session),
                notification_repo=NotificationRepository(session),
            )
            end_user = await session.get(EndUser, blog_session.end_user_id)
            await notification_service.create_for_end_user(
                end_user=end_user,
                type="blog_failed",
                title="Blog generation failed",
                message=f"Session {canonical_session_id} failed during {current_stage}.",
                session_id=canonical_session_id,
                action_url=f"/sessions/{canonical_session_id}/progress",
            )
            logger.error(
                "canonical_session_failed",
                canonical_session_id=canonical_session_id,
                current_stage=current_stage,
                error=error,
            )


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    
    signal_name = signal.Signals(signum).name
    logger.info("shutdown_signal_received", signal=signal_name)
    print(f"\n⚠️  Shutdown signal received ({signal_name}). Finishing current job...")
    
    shutdown_requested = True


def main():
    """Entry point for worker process."""
    print("=" * 60)
    print("  BLOGIFY BACKGROUND WORKER")
    print("=" * 60)
    
    # Parse worker ID from command line or generate
    worker_id = None
    if len(sys.argv) > 1:
        worker_id = sys.argv[1]
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Run worker
    try:
        exit_code = asyncio.run(run_worker(worker_id))
        if isinstance(exit_code, int):
            sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("worker_interrupted")
    except Exception as e:
        logger.error("worker_fatal_error", error=str(e))
        print(f"💥 Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
