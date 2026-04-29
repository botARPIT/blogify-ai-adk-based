"""Standalone reaper process for stale blog sessions.

This runs as a separate process from the worker to ensure:
- Reaper is not affected by worker load
- Independent scaling and monitoring
- Separate lifecycle management

Usage:
    python -m src.workers.reaper
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

from dotenv import load_dotenv

env = os.getenv("ENVIRONMENT", "dev")
load_dotenv(f".env.{env}")

from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.job_reaper import job_reaper

setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
logger = get_logger(__name__)

shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    
    signal_name = signal.Signals(signum).name
    logger.info("reaper_shutdown_signal_received", signal=signal_name)
    print(f"\n⚠️  Reaper shutdown signal received ({signal_name})...")
    shutdown_requested = True


async def run_reaper():
    """Main reaper loop."""
    global shutdown_requested
    
    try:
        await job_reaper.start()
        print(f"🌾 Reaper started (interval: {job_reaper.interval}s, stale threshold: {job_reaper.stale_threshold}s)")
        
        while not shutdown_requested:
            await job_reaper._loop()
            
    except Exception as e:
        logger.error("reaper_fatal_error", error=str(e))
        print(f"💥 Reaper fatal error: {e}")
        return 1
    
    finally:
        await job_reaper.stop()
        logger.info("reaper_shutdown_complete")
        print("👋 Reaper shutdown complete")
    
    return 0


def main():
    """Entry point for reaper process."""
    print("=" * 60)
    print("  BLOGIFY JOB REAPER")
    print("=" * 60)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        exit_code = asyncio.run(run_reaper())
        if isinstance(exit_code, int):
            sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("reaper_interrupted")
    except Exception as e:
        logger.error("reaper_fatal_error", error=str(e))
        print(f"💥 Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()