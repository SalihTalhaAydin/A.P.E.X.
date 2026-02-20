"""
Conversation Orchestrator - The heart of Apex.
Handles the full flow: context build -> AI call -> tool loop -> response.
Triggers background fact extraction after each conversation.
"""

import asyncio
import json
import logging

import litellm

logger = logging.getLogger(__name__)
from memory.context_builder import ContextBuilder
from memory.conversation_store import ConversationStore
from memory.fact_extractor import FactExtractor
from memory.knowledge_store import KnowledgeStore
from tools.base import (
    TOOL_REGISTRY,
    execute_tool,
    get_openai_tool_definitions,
)

from brain.config import settings


def _looks_like_device_action_claim(content: str) -> bool:
    """Check if text claims a device action was performed."""
    if not content or not isinstance(content, str):
        return False
    lower = content.lower()
    phrases = (
        "cycled",
        "turned off",
        "turned on",
        "turned the light",
        "turned the lamp",
        "i've ",
        "i have ",
    )
    return any(p in lower for p in phrases)


class Conversation:
    def __init__(
        self,
        conversation_store: ConversationStore,
        knowledge_store: KnowledgeStore,
        fact_extractor: FactExtractor,
        context_builder: ContextBuilder,
        mcp_bridge=None,
    ):
        self.conversation_store = conversation_store
        self.knowledge_store = knowledge_store
        self.fact_extractor = fact_extractor
        self.context_builder = context_builder
        self.mcp_bridge = mcp_bridge

        # Explainability: track action trace per session
        self._action_traces: dict[str, str] = {}

        # Background tasks: keep references so GC doesn't collect them
        self._background_tasks: set = set()

        # Set API keys for LiteLLM
        if settings.openai_api_key:
            litellm.openai_key = settings.openai_api_key
        if settings.anthropic_api_key:
            litellm.anthropic_key = settings.anthropic_api_key

        # Silence litellm's verbose logging
        litellm.suppress_debug_info = True

    async def handle(
        self, user_message: str, session_id: str = "default"
    ) -> str:
        """
        Process a user message through the full Apex pipeline.
        Returns the final response text.
        """
        # 1. Save user turn
        await self.conversation_store.save_turn(
            "user", user_message, session_id
        )

        # 2. Build rich context (recent history + relevant facts + time)
        system_prompt = await self.context_builder.build(
            user_message
        )

        # 2.5. Inject last action trace for explainability
        last_trace = self._action_traces.get(session_id, "")
        if last_trace:
            system_prompt += (
                "\n\nLAST ACTION TRACE (reference if the user "
                "asks why you did something):\n"
                f"{last_trace}"
            )

        # 3. Prepare messages for the AI
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 4. Get tool definitions (native + MCP)
        tool_defs = get_openai_tool_definitions()
        if self.mcp_bridge and self.mcp_bridge.connected:
            tool_defs = (
                tool_defs
                + self.mcp_bridge.get_openai_tool_definitions()
            )

        # 5. Call AI with tool loop
        response_text = await self._ai_tool_loop(
            messages, tool_defs, session_id=session_id
        )

        # 6. Save assistant response
        await self.conversation_store.save_turn(
            "assistant", response_text, session_id
        )

        # 7. Background fact extraction (user doesn't wait)
        recent = await self.conversation_store.get_recent(
            n=4, session_id=session_id
        )
        task = asyncio.create_task(self._safe_extract_facts(recent))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return response_text

    async def _ai_tool_loop(
        self,
        messages: list[dict],
        tool_defs: list[dict],
        max_iterations: int = 15,
        session_id: str = "default",
    ) -> str:
        """Call AI, handle tool calls, repeat until text."""
        retry_nudge_done = False
        tools_called: list[str] = []
        for _iteration in range(max_iterations):
            try:
                kwargs = {
                    "model": settings.litellm_model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 2000,
                }
                if tool_defs:
                    kwargs["tools"] = tool_defs
                    kwargs["tool_choice"] = "auto"

                response = await litellm.acompletion(**kwargs)
            except Exception as e:
                logger.exception("AI call failed: %s", e)
                return f"Error reaching AI: {e}"

            msg = response.choices[0].message
            # only system + user so far?
            is_first_response = len(messages) == 2

            # If no tool calls, we have our answer (or a confabulation)
            if not msg.tool_calls:
                text = msg.content or "Done."
                logger.debug(
                    "Text response (no tools called): %s", text[:150]
                )
                if is_first_response:
                    logger.debug("First response had 0 tool calls.")
                if _looks_like_device_action_claim(text):
                    logger.warning(
                        "Responded with text only (no tool calls); "
                        "possible confabulation."
                    )
                    # One retry: nudge the model to use tools
                    if (
                        tool_defs
                        and not retry_nudge_done
                        and is_first_response
                    ):
                        retry_nudge_done = True
                        messages.append(msg.model_dump())
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "You must use the tools to "
                                    "perform the action. Do not "
                                    "reply with a summary only."
                                ),
                            },
                        )
                        continue

                # Build and store action trace for explainability
                facts_used = self._extract_facts_from_system(messages)
                self._action_traces[session_id] = self._build_action_trace(
                    tools_called, facts_used
                )
                if self._action_traces[session_id]:
                    logger.debug(
                        "Action trace: %s", self._action_traces[session_id]
                    )
                return text

            # Process tool calls
            if is_first_response:
                logger.debug(
                    "First response had %d tool calls.",
                    len(msg.tool_calls),
                )
            messages.append(msg.model_dump())

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                logger.debug(
                    "Tool call: %s(%s)",
                    fn_name,
                    json.dumps(args, default=str)[:500],
                )

                # Route: native tool or MCP tool
                if fn_name in TOOL_REGISTRY:
                    result = await execute_tool(
                        fn_name, args
                    )
                elif (
                    self.mcp_bridge
                    and self.mcp_bridge.has_tool(fn_name)
                ):
                    result = (
                        await self.mcp_bridge.execute_tool(
                            fn_name, args
                        )
                    )
                else:
                    result = (
                        f"Unknown tool: {fn_name}"
                    )
                logger.debug(
                    "Tool result: %s -> %s",
                    fn_name,
                    str(result)[:300],
                )

                # Track for explainability
                tools_called.append(fn_name)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    }
                )

        return (
            "I ran into a loop processing your request. "
            "Could you rephrase?"
        )

    async def _safe_extract_facts(self, recent_turns: list[dict]):
        """Safely run fact extraction in the background."""
        try:
            await self.fact_extractor.extract_from_conversation(
                turns=recent_turns,
                litellm_completion=litellm.acompletion,
            )
        except Exception as e:
            logger.error(
                "FactExtractor background error: %s",
                e,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Explainability helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_action_trace(
        tools_called: list[str],
        facts_used: list[str],
    ) -> str:
        """Build a human-readable trace of why actions were taken."""
        trace_parts: list[str] = []
        if tools_called:
            unique = list(dict.fromkeys(tools_called))
            trace_parts.append(
                f"Actions taken: {', '.join(unique)}"
            )
        if facts_used:
            trace_parts.append(
                f"Based on: {', '.join(facts_used)}"
            )
        return " | ".join(trace_parts) if trace_parts else ""

    @staticmethod
    def _extract_facts_from_system(
        messages: list[dict],
    ) -> list[str]:
        """Pull fact keys from the WHAT YOU KNOW section."""
        facts: list[str] = []
        for m in messages:
            if m.get("role") != "system":
                continue
            content = m.get("content", "")
            in_section = False
            for line in content.splitlines():
                if line.startswith("WHAT YOU KNOW"):
                    in_section = True
                    continue
                if in_section:
                    if line.startswith("- "):
                        key = line.split(":")[0].lstrip("- ").strip()
                        if key:
                            facts.append(key)
                    elif line and not line.startswith(" "):
                        break
            break  # only first system message
        return facts
