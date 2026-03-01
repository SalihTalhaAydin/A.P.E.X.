"""
Background timer for fact maintenance.
Handles: confidence decay, expired fact cleanup,
low-confidence pruning. Runs on a fixed interval.
"""

import asyncio
import logging

from memory.knowledge_store import KnowledgeStore

logger = logging.getLogger(__name__)


class FactCleanupTimer:
    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        interval_hours: int = 24,
    ):
        self._knowledge_store = knowledge_store
        self._interval = interval_hours * 3600

    async def start(self) -> asyncio.Task:
        """Start the background cleanup loop. Returns the task."""
        task = asyncio.create_task(self._loop())
        return task

    async def _loop(self) -> None:
        """Periodically run cleanup."""
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._cleanup()
            except Exception as e:
                logger.warning("Fact cleanup error: %s", e)

    async def _cleanup(self) -> None:
        """Run all maintenance tasks."""
        decayed = await self._knowledge_store.decay_confidence()
        cleaned = await self._knowledge_store.cleanup_expired()

        logger.info(
            "Fact cleanup: %d decayed, %d expired removed",
            decayed or 0,
            cleaned or 0,
        )
