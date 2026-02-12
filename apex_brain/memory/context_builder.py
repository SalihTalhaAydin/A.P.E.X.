"""
Context Builder - Assembles rich context before each AI call.
Pulls together: recent conversation, relevant facts, time, calendar.
This is what makes Apex feel like it actually knows you.
"""

import datetime
from memory.conversation_store import ConversationStore
from memory.knowledge_store import KnowledgeStore
from brain.system_prompt import build_system_prompt


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
        """
        Build a full system prompt with all relevant context for the current query.
        Returns the complete system prompt string.
        """
        # 1. Current date/time
        now = datetime.datetime.now()
        current_datetime = now.strftime("%A, %B %d, %Y at %I:%M %p")

        # 2. Recent conversation turns (for continuity)
        recent_turns = await self.conversation_store.get_recent(
            n=self.recent_turns_count
        )

        # 3. Semantically relevant facts (based on what the user just said)
        relevant_facts = []
        if user_message:
            # Try semantic search first, fall back to keyword
            results = await self.knowledge_store.search_semantic(
                query=user_message, limit=self.max_facts
            )
            if not results:
                # Try keyword search as fallback
                results = await self.knowledge_store.search_keyword(
                    query=user_message, limit=self.max_facts
                )
            relevant_facts = results

        # 4. Also include high-confidence "always relevant" facts
        # (preferences, key people, important facts)
        core_facts = await self.knowledge_store.get_all_facts(limit=50)
        core_set = {f["id"] for f in relevant_facts}
        for fact in core_facts:
            if (
                fact["id"] not in core_set
                and fact.get("confidence", 0) >= 0.9
            ):
                relevant_facts.append(fact)
                if len(relevant_facts) >= self.max_facts:
                    break

        # 5. Calendar summary (placeholder -- filled when calendar tool is active)
        calendar_summary = ""

        # 6. Build the system prompt with all context injected
        return build_system_prompt(
            current_datetime=current_datetime,
            calendar_summary=calendar_summary,
            relevant_facts=relevant_facts,
            recent_turns=recent_turns,
        )
