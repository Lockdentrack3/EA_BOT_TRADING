"""
Background Task Scheduler
Runs periodic tasks: account snapshots, daily reports, circuit breaker resets.
"""

import asyncio
import logging
from datetime import datetime, time as dtime

logger = logging.getLogger("scheduler")


class TaskScheduler:
    def __init__(self):
        self._tasks = []
        self._running = False

    async def start(self):
        self._running = True
        self._tasks.append(asyncio.create_task(self._heartbeat()))
        self._tasks.append(asyncio.create_task(self._daily_reset()))
        logger.info("Scheduler started")

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        logger.info("Scheduler stopped")

    async def _heartbeat(self):
        while self._running:
            await asyncio.sleep(60)
            logger.debug(f"Heartbeat | {datetime.utcnow().isoformat()}")

    async def _daily_reset(self):
        """Reset circuit breaker and snapshots at 00:01 UTC daily."""
        while self._running:
            now = datetime.utcnow()
            # Wait until next 00:01 UTC
            next_reset = datetime.combine(now.date(), dtime(0, 1))
            if next_reset <= now:
                from datetime import timedelta
                next_reset = next_reset + timedelta(days=1)
            wait_secs = (next_reset - now).total_seconds()
            await asyncio.sleep(wait_secs)

            logger.info("Daily reset triggered by scheduler")
            # Notify risk manager (imported lazily to avoid circular imports)
            try:
                from python.api.routes import risk_manager
                risk_manager.reset_circuit_breaker()
            except Exception as e:
                logger.error(f"Daily reset error: {e}")
