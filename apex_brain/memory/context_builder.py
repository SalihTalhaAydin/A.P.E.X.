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

    async def build(self, user_message: str) -> str:
        """Build a full system prompt with all context.

        Returns the complete system prompt string.
        """
        # 1. Current date/time + time context
        try:
            tz = ZoneInfo(settings.timezone)
        except (KeyError, Exception):
            logger.warning(
                "Invalid timezone '%s', falling back to UTC",
                settings.timezone,
            )
            tz = datetime.timezone.utc
        now = datetime.datetime.now(tz=tz)
        time_context = _build_time_context(now)

        # 2. Recent conversation turns (for continuity)
        recent_turns = await self.conversation_store.get_recent(
            n=self.recent_turns_count
        )

        # 3. Semantically relevant facts
        relevant_facts = []
        if user_message:
            results = await self.knowledge_store.search_semantic(
                query=user_message,
                limit=self.max_facts,
            )
            if not results:
                results = await self.knowledge_store.search_keyword(
                    query=user_message,
                    limit=self.max_facts,
                )
            relevant_facts = results

        # 4. High-confidence core facts
        core_facts = await self.knowledge_store.get_all_facts(limit=50)
        core_set = {f["id"] for f in relevant_facts}
        for fact in core_facts:
            if len(relevant_facts) >= self.max_facts:
                break
            if (
                fact["id"] not in core_set
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
        except Exception:
            logger.warning(
                "context_builder: Failed to fetch presence", exc_info=True
            )

        # 4.6. Device discovery: current entity names
        device_summary = ""
        try:
            from tools.ha_helpers import (
                get_device_summary,
            )

            device_summary = await get_device_summary()
        except Exception:
            logger.warning(
                "context_builder: Failed to fetch device summary",
                exc_info=True,
            )

        # 4.7. Service schemas for top domains
        service_schemas = ""
        try:
            service_schemas = await fetch_service_schemas()
        except Exception:
            logger.warning(
                "context_builder: Failed to fetch service schemas",
                exc_info=True,
            )

        # 5. Calendar summary
        calendar_summary = ""
        try:
            if settings.google_calendar_credentials_path:
                from tools.calendar_tool import (
                    get_today_schedule,
                )

                calendar_summary = await get_today_schedule()
        except Exception:
            logger.warning(
                "context_builder: Failed to fetch calendar", exc_info=True
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
