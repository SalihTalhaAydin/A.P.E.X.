"""
Scheduler - Background task runner for autonomous behavior.

Runs periodic tasks inside the FastAPI lifespan using asyncio.
No external dependencies (no APScheduler, no cron).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable

from brain.config import settings

logger = logging.getLogger(__name__)

# How often the main loop checks for due tasks (seconds)
_TICK_INTERVAL = 30
_TASK_TIMEOUT = 120  # max seconds per task execution


@dataclass
class ScheduledTask:
    """Definition of a repeating task."""

    name: str
    callback: Callable[[], Awaitable[None]]
    interval_seconds: float
    next_run: float = 0.0  # monotonic time
    enabled: bool = True
    run_on_startup: bool = False
    _last_fired_date: str = field(default="", repr=False)


class Scheduler:
    """Background task scheduler running inside the FastAPI event loop."""

    def __init__(
        self,
        conversation,
        knowledge_store,
        curator=None,
    ):
        self._conversation = conversation
        self._knowledge_store = knowledge_store
        self._curator = curator
        self._tasks: list[ScheduledTask] = []
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    @property
    def task_names(self) -> list[str]:
        return [t.name for t in self._tasks]

    @property
    def running(self) -> bool:
        return self._running

    def register(
        self,
        name: str,
        callback: Callable[[], Awaitable[None]],
        interval_seconds: float,
        run_on_startup: bool = False,
        enabled: bool = True,
    ) -> None:
        """Register a periodic task."""
        now = time.monotonic()
        task = ScheduledTask(
            name=name,
            callback=callback,
            interval_seconds=interval_seconds,
            next_run=now if run_on_startup else now + interval_seconds,
            enabled=enabled,
            run_on_startup=run_on_startup,
        )
        self._tasks.append(task)
        logger.debug("Registered task: %s (every %ds)", name, interval_seconds)

    async def start(self) -> None:
        """Start the scheduler loop."""
        self._running = True
        self._register_builtin_tasks()
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info(
            "Scheduler started with %d tasks: %s",
            len(self._tasks),
            ", ".join(t.name for t in self._tasks),
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        # Cancel outstanding background tasks
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        logger.info("Scheduler stopped")

    async def _run_loop(self) -> None:
        """Main loop: check every tick which tasks are due."""
        # Small startup delay to let the server fully initialize
        await asyncio.sleep(5)
        while self._running:
            now = time.monotonic()
            for task in self._tasks:
                if task.enabled and now >= task.next_run:
                    task.next_run = now + task.interval_seconds
                    t = asyncio.create_task(self._safe_run(task))
                    self._background_tasks.add(t)
                    t.add_done_callback(self._background_tasks.discard)
            await asyncio.sleep(_TICK_INTERVAL)

    async def _safe_run(self, task: ScheduledTask) -> None:
        """Run a task with error handling — never crash the loop."""
        try:
            await asyncio.wait_for(task.callback(), timeout=_TASK_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("Task '%s' timed out after %ds", task.name, _TASK_TIMEOUT)
        except Exception as e:
            logger.error("Task '%s' failed: %s", task.name, e, exc_info=True)

    # ------------------------------------------------------------------ #
    # Builtin tasks
    # ------------------------------------------------------------------ #

    def _register_builtin_tasks(self) -> None:
        """Register all built-in scheduled tasks."""
        # Fact maintenance (direct, no LLM)
        self.register(
            "fact_decay",
            self._task_fact_decay,
            interval_seconds=86400,  # daily
        )
        self.register(
            "fact_cleanup",
            self._task_fact_cleanup,
            interval_seconds=86400,
        )

        # Curator audits
        if self._curator and settings.curator_enabled:
            self.register(
                "fact_audit",
                self._curator.audit_facts,
                interval_seconds=86400,
            )
            self.register(
                "fact_consolidation",
                self._curator.consolidate_facts,
                interval_seconds=86400,
            )
            self.register(
                "entity_audit",
                self._curator.audit_entities,
                interval_seconds=86400,
            )
            self.register(
                "automation_audit",
                self._curator.audit_automations,
                interval_seconds=604800,  # weekly
            )

        # Proactive: briefings and health checks
        self.register(
            "morning_briefing",
            self._task_morning_briefing,
            interval_seconds=60,  # checks every minute
        )
        self.register(
            "evening_briefing",
            self._task_evening_briefing,
            interval_seconds=60,
        )
        self.register(
            "health_check",
            self._task_health_check,
            interval_seconds=settings.health_check_interval_minutes * 60,
        )
        self.register(
            "reminder_check",
            self._task_reminder_check,
            interval_seconds=60,
        )

    # ------------------------------------------------------------------ #
    # Task implementations
    # ------------------------------------------------------------------ #

    async def _task_fact_decay(self) -> None:
        count = await self._knowledge_store.decay_confidence()
        if count:
            logger.info("Decayed confidence on %d facts", count)

    async def _task_fact_cleanup(self) -> None:
        count = await self._knowledge_store.cleanup_expired()
        if count:
            logger.info("Cleaned up %d expired facts", count)

    async def _task_morning_briefing(self) -> None:
        """At configured morning hour, send a briefing prompt."""
        await self._timed_briefing(
            settings.morning_briefing_hour,
            "morning_briefing",
            "[MORNING BRIEFING] Good morning. Please prepare a brief morning "
            "briefing: check the weather using get_weather(), look at today's "
            "calendar, note who's home using get_presence(), and mention anything "
            "noteworthy. Keep it concise and natural.",
        )

    async def _task_evening_briefing(self) -> None:
        """At configured evening hour, send a summary prompt."""
        await self._timed_briefing(
            settings.evening_briefing_hour,
            "evening_briefing",
            "[EVENING SUMMARY] Good evening. Please prepare a brief evening "
            "summary: what happened today, any issues that need attention, "
            "tomorrow's schedule if available. Suggest locking up and adjusting "
            "climate for the night if appropriate. Keep it concise.",
        )

    async def _timed_briefing(
        self, target_hour: int, task_name: str, message: str
    ) -> None:
        """Fire a briefing message once per day at the target hour."""
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(settings.timezone)
        except Exception:
            import datetime as _dt

            tz = _dt.timezone.utc

        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")

        # Only fire at the target hour, and only once per day
        if now.hour != target_hour:
            return

        # Check if already fired today
        task = next((t for t in self._tasks if t.name == task_name), None)
        if task and task._last_fired_date == today:
            return

        # Mark as fired
        if task:
            task._last_fired_date = today

        logger.info("Firing %s for %s", task_name, today)
        try:
            await self._conversation.handle(message, session_id="apex_scheduler")
        except Exception as e:
            logger.error("%s failed: %s", task_name, e)

    async def _task_health_check(self) -> None:
        """Periodic system health check — only alert if issues found."""
        msg = (
            "[SYSTEM HEALTH CHECK] Quick check: "
            "1. Use manage('health', 'check') to get system resource usage. "
            "2. Only report if something is concerning (CPU > 80%, disk > 90%, etc.). "
            "3. If everything is fine, don't produce any output."
        )
        try:
            await self._conversation.handle(msg, session_id="apex_scheduler")
        except Exception as e:
            logger.error("Health check failed: %s", e)

    async def _task_reminder_check(self) -> None:
        """Check for due reminders in the knowledge store."""
        try:
            now_iso = datetime.utcnow().isoformat()
            facts = await self._knowledge_store.get_all_facts(
                category="reminder", limit=20
            )
            due = [
                f
                for f in facts
                if f.get("value")
                and "expires_at" not in f  # reminders without expiry are one-time
            ]
            # For now, reminders are handled by fact expiration.
            # Future: check expires_at proximity and send reminder messages.
        except Exception as e:
            logger.debug("Reminder check: %s", e)
