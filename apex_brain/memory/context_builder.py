"""
Context Builder - Assembles rich context before each AI call.
Pulls together: recent conversation, relevant facts, time,
calendar, presence. This is what makes Apex feel like it
actually knows you.
"""

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
        self, user_message: str, session_id: str = "default"
    ) -> str:
        """Build a full system prompt with all context.

        Returns the complete system prompt string.
        """
        # 1. Current date/time + time context
        # Only catch KeyError (unknown timezone / ZoneInfoNotFoundError) and ValueError (bad format).
        # Do NOT catch ImportError, RuntimeError, or Exception — those must propagate.
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

        # 2. Recent conversation turns (for continuity)
        recent_turns = await self.conversation_store.get_recent(
            n=self.recent_turns_count,
            session_id=session_id,
        )

        # 3. Semantically relevant facts (search_semantic falls back to
        #    search_keyword internally when embeddings are unavailable)
        # Reserve slots for high-confidence core facts (BUG-128)
        semantic_limit = max(1, self.max_facts - 5)
        relevant_facts = []
        if user_message:
            relevant_facts = await self.knowledge_store.search_semantic(
                query=user_message,
                limit=semantic_limit,
            )

        # 4. High-confidence core facts (always add; reserve ensured above)
        core_facts = await self.knowledge_store.get_all_facts(limit=50)
        core_set = {f.get("id") for f in relevant_facts if f.get("id")}
        for fact in core_facts:
            if len(relevant_facts) >= self.max_facts:
                break
            if (
                fact.get("id") not in core_set
                and fact.get("confidence", 0) >= 0.9
            ):
                relevant_facts.append(fact)

        # 4.5. Presence: who is home?
        presence_summary = ""
        try:
            from tools.presence import (
                get_presence_summary,
            )

            presence_summary = await get_presence_summary()
        except (ImportError, ConnectionError, TimeoutError, OSError) as e:
            logger.warning("context_builder: Failed to fetch presence: %s", e)

        # 4.6. Device discovery: current entity names
        device_summary = ""
        try:
            from tools.ha_helpers import (
                get_device_summary,
            )

            device_summary = await get_device_summary()
        except (ImportError, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(
                "context_builder: Failed to fetch device summary: %s", e
            )

        # 4.7. Service schemas for top domains
        service_schemas = ""
        try:
            service_schemas = await fetch_service_schemas()
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning(
                "context_builder: Failed to fetch service schemas: %s", e
            )

        # 5. Calendar summary
        calendar_summary = ""
        try:
            if settings.google_calendar_credentials_path:
                from tools.calendar_tool import (
                    get_today_schedule,
                )

                calendar_summary = await get_today_schedule()
        except (ImportError, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(
                "context_builder: Failed to fetch calendar: %s", e
            )

        # 6. Build the system prompt
        return build_system_prompt(
            calendar_summary=calendar_summary,
            relevant_facts=relevant_facts,
            recent_turns=recent_turns,
            presence_summary=presence_summary,
            time_context=time_context,
            device_summary=device_summary,
            service_schemas=service_schemas,
        )
