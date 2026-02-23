"""
Context Builder - Assembles rich context before each AI call.
Pulls together: recent conversation, relevant facts, time,
calendar, presence. This is what makes Apex feel like it
actually knows you.
"""

import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

from brain.config import settings
from brain.system_prompt import (
    _build_time_context,
    build_system_prompt,
    fetch_service_schemas,
)

from memory.conversation_store import ConversationStore
from memory.knowledge_store import KnowledgeStore


async def _safe_async(coro, label: str, default=""):
    """Run a coroutine, returning *default* on expected errors."""
    try:
        return await coro
    except (
        ImportError,
        ConnectionError,
        TimeoutError,
        OSError,
    ) as e:
        logger.warning("context_builder: %s failed: %s", label, e)
        return default


class ContextBuilder:
    def __init__(
        self,
        conversation_store: ConversationStore,
        knowledge_store: KnowledgeStore,
        recent_turns_count: int = 10,
        max_facts: int = 20,
    ):
        self.conversation_store = conversation_store
        self.knowledge_store = knowledge_store
        self.recent_turns_count = recent_turns_count
        self.max_facts = max_facts

    async def build(
        self, user_message: str, session_id: str = "default",
        voice_mode: bool = False,
    ) -> str:
        """Build a full system prompt with all context.

        voice_mode: when True, builds a lighter prompt — skips
        conversation history, service schemas, proactive hints,
        and calendar to cut prompt tokens for fast voice responses.

        All independent fetches run in parallel via
        asyncio.gather() to minimise latency.

        Returns the complete system prompt string.
        """
        # 1. Sync: timezone + time context (no I/O)
        try:
            tz = ZoneInfo(settings.timezone)
        except (KeyError, ValueError):
            logger.warning(
                "Invalid timezone '%s', falling back to UTC",
                settings.timezone,
            )
            tz = datetime.timezone.utc
        now = datetime.datetime.now(tz=tz)
        time_context = _build_time_context(now)

        # 2. Prepare parallel coroutines
        fact_limit = 5 if voice_mode else self.max_facts
        semantic_limit = max(1, fact_limit - 5)

        # Lazy imports (avoid circular / heavy imports at module level)
        from tools.ha_helpers import (
            get_area_directory,
            get_device_summary,
        )
        from tools.presence import get_presence_summary

        # --- Always-run coroutines ---
        async def _no_facts():
            return []

        coros = {
            "semantic_facts": (
                self.knowledge_store.search_semantic(
                    query=user_message,
                    limit=semantic_limit,
                )
                if user_message
                else _no_facts()
            ),
            "core_facts": self.knowledge_store.get_all_facts(
                limit=50
            ),
            "presence": _safe_async(
                get_presence_summary(), "presence"
            ),
            "device_summary": _safe_async(
                get_device_summary(), "device_summary"
            ),
            "area_directory": _safe_async(
                get_area_directory(), "area_directory"
            ),
        }

        # --- Text-mode only ---
        if not voice_mode:
            coros["recent_turns"] = (
                self.conversation_store.get_recent(
                    n=self.recent_turns_count,
                    session_id=session_id,
                )
            )
            coros["service_schemas"] = _safe_async(
                fetch_service_schemas(), "service_schemas"
            )
            if settings.google_calendar_credentials_path:
                try:
                    from tools.calendar_tool import (
                        get_today_schedule,
                    )

                    coros["calendar"] = _safe_async(
                        get_today_schedule(), "calendar"
                    )
                except ImportError:
                    pass

        # 3. Parallel fetch
        keys = list(coros.keys())
        results = await asyncio.gather(
            *coros.values(), return_exceptions=True
        )
        fetched: dict = {}
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                logger.warning(
                    "context_builder: %s raised %s", key, result
                )
                fetched[key] = [] if "facts" in key else ""
            else:
                fetched[key] = result

        # 4. Post-process facts (dedup core into semantic)
        relevant_facts = fetched.get("semantic_facts") or []
        core_facts = fetched.get("core_facts") or []
        core_set = {
            f.get("id") for f in relevant_facts if f.get("id")
        }
        for fact in core_facts:
            if len(relevant_facts) >= fact_limit:
                break
            if (
                fact.get("id") not in core_set
                and fact.get("confidence", 0) >= 0.9
            ):
                relevant_facts.append(fact)

        # 5. Build the system prompt
        return build_system_prompt(
            calendar_summary=fetched.get("calendar", ""),
            relevant_facts=relevant_facts,
            recent_turns=fetched.get("recent_turns"),
            presence_summary=fetched.get("presence", ""),
            time_context=time_context,
            device_summary=fetched.get("device_summary", ""),
            service_schemas=fetched.get("service_schemas", ""),
            area_directory=fetched.get("area_directory", ""),
            voice_mode=voice_mode,
        )
