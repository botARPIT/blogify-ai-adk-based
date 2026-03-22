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

from src.config.logging_config import get_logger, setup_logging
from src.core.startup import StartupCheckError, runtime_manager
from src.core.task_queue import task_queue, TaskStatus
from src.models.repository import db_repository

setup_logging("INFO")
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
        # Start job reclaim loop
        await task_queue.start_reclaim_loop(interval=60)

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


async def process_full_blog(job: dict, executor: StageExecutor, worker_id: str):
    """
    Process a complete blog generation (all stages).
    
    Runs all pipeline stages in sequence:
    intent → outline → research → writing → completed
    """
    job_id = job["id"]
    payload = job.get("payload", {})
    blog_id = payload.get("blog_id")
    session_id = payload.get("session_id", "unknown")
    topic = payload.get("topic", "")
    
    if not blog_id:
        logger.error("job_missing_blog_id", job_id=job_id)
        await task_queue.update_task(job_id, status=TaskStatus.FAILED, error="Missing blog_id")
        return
    
    current_stage = "intent"
    
    try:
        # Update job status to processing
        await task_queue.update_task(job_id, status=TaskStatus.PROCESSING)
        
        # Update blog status
        await db_repository.update_blog(session_id=session_id, status="processing")
        
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
            
            # Extend visibility timeout before each stage
            await task_queue.extend_visibility(job_id, 300)
            
            # Execute the stage
            result, next_stage = await executor.execute_stage(blog_id, current_stage)
            
            if next_stage == "failed":
                raise Exception(result.get("error", "Stage execution failed"))
            
            logger.info(
                "stage_completed",
                job_id=job_id,
                stage=current_stage,
                next_stage=next_stage,
            )
            
            current_stage = next_stage
        
        # All stages complete
        await task_queue.update_task(
            job_id,
            status=TaskStatus.COMPLETED,
            result={"session_id": session_id, "blog_id": blog_id},
        )
        
        logger.info("job_completed", job_id=job_id, blog_id=blog_id)
        print(f"✅ Blog {session_id[:8]} completed!")
        
    except Exception as e:
        logger.error(
            "job_processing_failed",
            job_id=job_id,
            blog_id=blog_id,
            stage=current_stage,
            error=str(e),
        )
        print(f"❌ Job failed at stage {current_stage}: {str(e)[:100]}")
        
        await handle_job_failure(job, str(e), current_stage)


async def handle_job_failure(job: dict, error: str, stage: str = "unknown"):
    """
    Handle job failure with retry logic.
    
    Uses exponential backoff for retries.
    Moves to dead letter queue after max attempts.
    """
    job_id = job["id"]
    payload = job.get("payload", {})
    session_id = payload.get("session_id", "unknown")
    attempts = job.get("retries", 0) + 1
    max_attempts = job.get("max_retries", 3)
    
    # Update blog with error
    await db_repository.update_blog(
        session_id=session_id,
        status="failed",
    )
    
    if attempts < max_attempts:
        # Retry with exponential backoff
        backoff_seconds = min(300, 2 ** attempts * 10)
        
        logger.info(
            "job_retry_scheduled",
            job_id=job_id,
            attempt=attempts,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
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
        
        await task_queue.update_task(
            job_id,
            status=TaskStatus.FAILED,
            error=f"Max retries exceeded at stage {stage}: {error}",
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
