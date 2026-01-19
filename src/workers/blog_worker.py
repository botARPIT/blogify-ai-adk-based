"""Background worker for blog generation jobs.

This worker process consumes jobs from Redis queue and executes
LLM pipeline stages. No LLM calls happen in the API layer.

Usage:
    python -m src.workers.blog_worker
"""

import asyncio
import os
import signal
import sys
import uuid
from datetime import datetime

# Load environment before other imports
from dotenv import load_dotenv
env = os.getenv("ENVIRONMENT", "dev")
load_dotenv(f".env.{env}")

from src.config.logging_config import get_logger, setup_logging
from src.core.task_queue import task_queue, TaskStatus
from src.models.repository import db_repository
from src.workers.stage_executor import StageExecutor

setup_logging("INFO")
logger = get_logger(__name__)

# Worker configuration
POLL_INTERVAL = 1  # seconds
SHUTDOWN_TIMEOUT = 30

# Shutdown flag
shutdown_requested = False


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
    
    # Initialize services
    try:
        await db_repository.create_tables()
        logger.info("database_initialized")
    except Exception as e:
        logger.error("database_init_failed", error=str(e))
        return
    
    executor = StageExecutor()
    jobs_processed = 0
    
    logger.info("worker_ready", worker_id=worker_id)
    
    while not shutdown_requested:
        try:
            # Try to claim a job
            job = await task_queue.dequeue(timeout=POLL_INTERVAL)
            
            if job is None:
                continue
            
            logger.info(
                "job_claimed",
                job_id=job["id"],
                worker_id=worker_id,
                job_type=job.get("type", "unknown"),
            )
            
            # Process the job
            await process_blog_job(job, executor, worker_id)
            jobs_processed += 1
            
        except asyncio.CancelledError:
            logger.info("worker_cancelled", worker_id=worker_id)
            break
        except Exception as e:
            logger.error("worker_loop_error", error=str(e))
            await asyncio.sleep(POLL_INTERVAL)
    
    logger.info(
        "worker_shutdown_complete",
        worker_id=worker_id,
        jobs_processed=jobs_processed,
    )


async def process_blog_job(job: dict, executor: StageExecutor, worker_id: str):
    """
    Process a single blog generation job.
    
    Args:
        job: Job data from queue
        executor: Stage executor instance
        worker_id: Worker identifier
    """
    job_id = job["id"]
    payload = job.get("payload", {})
    blog_id = payload.get("blog_id")
    current_stage = payload.get("stage", "intent")
    session_id = payload.get("session_id", "unknown")
    
    if not blog_id:
        logger.error("job_missing_blog_id", job_id=job_id)
        await task_queue.update_task(job_id, status=TaskStatus.FAILED, error="Missing blog_id")
        return
    
    try:
        # Update job status to processing
        await task_queue.update_task(job_id, status=TaskStatus.PROCESSING)
        
        # Execute the stage
        logger.info(
            "executing_stage",
            job_id=job_id,
            blog_id=blog_id,
            stage=current_stage,
        )
        
        result, next_stage = await executor.execute_stage(blog_id, current_stage)
        
        if next_stage == "completed":
            # All stages done - job complete
            await task_queue.update_task(
                job_id,
                status=TaskStatus.COMPLETED,
                result=result,
            )
            logger.info(
                "job_completed",
                job_id=job_id,
                blog_id=blog_id,
                word_count=result.get("word_count", 0),
            )
            
        elif next_stage == "failed":
            # Stage failed - handle retry
            error_msg = result.get("error", "Unknown error")
            await handle_job_failure(job, error_msg)
            
        else:
            # More stages to process - enqueue next stage
            await enqueue_next_stage(
                blog_id=blog_id,
                session_id=session_id,
                stage=next_stage,
                original_payload=payload,
            )
            await task_queue.update_task(job_id, status=TaskStatus.COMPLETED)
            logger.info(
                "stage_completed",
                job_id=job_id,
                current_stage=current_stage,
                next_stage=next_stage,
            )
            
    except Exception as e:
        logger.error(
            "job_processing_failed",
            job_id=job_id,
            blog_id=blog_id,
            stage=current_stage,
            error=str(e),
        )
        await handle_job_failure(job, str(e))


async def handle_job_failure(job: dict, error: str):
    """
    Handle job failure with retry logic.
    
    Uses exponential backoff for retries.
    Moves to dead letter queue after max attempts.
    
    Args:
        job: Failed job data
        error: Error message
    """
    job_id = job["id"]
    attempts = job.get("retries", 0) + 1
    max_attempts = job.get("max_retries", 3)
    
    if attempts < max_attempts:
        # Retry with exponential backoff
        backoff_seconds = min(300, 2 ** attempts * 10)  # Max 5 minutes
        
        logger.info(
            "job_retry_scheduled",
            job_id=job_id,
            attempt=attempts,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
        )
        
        # For now, just requeue immediately
        # In production, use delayed queue
        await task_queue.requeue(job_id)
        
    else:
        # Max retries exceeded - fail permanently
        logger.error(
            "job_max_retries_exceeded",
            job_id=job_id,
            attempts=attempts,
            error=error,
        )
        await task_queue.update_task(
            job_id,
            status=TaskStatus.FAILED,
            error=f"Max retries exceeded: {error}",
        )


async def enqueue_next_stage(
    blog_id: int,
    session_id: str,
    stage: str,
    original_payload: dict,
):
    """
    Enqueue the next stage for processing.
    
    Args:
        blog_id: Blog ID
        session_id: Session ID
        stage: Next stage to execute
        original_payload: Original job payload
    """
    payload = {
        **original_payload,
        "blog_id": blog_id,
        "session_id": session_id,
        "stage": stage,
    }
    
    job_id = await task_queue.enqueue(
        task_type="blog_stage",
        payload=payload,
    )
    
    logger.info(
        "next_stage_enqueued",
        job_id=job_id,
        blog_id=blog_id,
        stage=stage,
    )


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    
    signal_name = signal.Signals(signum).name
    logger.info("shutdown_signal_received", signal=signal_name)
    
    shutdown_requested = True


def main():
    """Entry point for worker process."""
    # Parse worker ID from command line or generate
    worker_id = None
    if len(sys.argv) > 1:
        worker_id = sys.argv[1]
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Run worker
    try:
        asyncio.run(run_worker(worker_id))
    except KeyboardInterrupt:
        logger.info("worker_interrupted")
    except Exception as e:
        logger.error("worker_fatal_error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
