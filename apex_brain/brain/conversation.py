"""
Conversation Orchestrator - The heart of Apex.
Handles the full flow: context build -> AI call -> tool loop -> response.
Triggers background fact extraction after each conversation.
"""

import asyncio
import json
import logging
import re

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

# Maximum nudge retries when confabulation is detected
_MAX_CONFAB_NUDGES = 2

# ------------------------------------------------------------------
# Confabulation & action-request detection
# ------------------------------------------------------------------

# AI response: claims a device action was performed without using tools
_CONFAB_CLAIM_RE = re.compile(
    r"(?:"
    # Direct action verbs (past tense)
    r"turned\s+(?:off|on|the)|switched\s+(?:off|on|the)|"
    r"powered\s+(?:off|on|down|up)|shut\s+(?:off|down|it)|"
    # State claims ("lights are now off", "should be off")
    r"(?:is|are|should\s+be)\s+(?:now\s+)?(?:off|on|locked"
    r"|unlocked|open(?:ed)?|closed|armed|disarmed|set"
    r"|adjusted|dimmed)|"
    # Completion claims ("it is done", "taken care of")
    r"(?:it\s+is|it's|that's|all)\s+done|"
    r"taken\s+care\s+of|all\s+set|"
    r"that\s+should\s+have|corrected\s+the|"
    # First-person past claims ("I've …", "I have …")
    r"i've\s+|i\s+have\s+|"
    # Specific device action verbs
    r"cycled|adjusted\s+the|dimmed\s+the|brightened\s+the|"
    r"activated\s+the|deactivated\s+the|"
    r"locked\s+the|unlocked\s+the|"
    r"opened\s+the|closed\s+the|"
    r"set\s+the\s+.{1,30}\s+to"
    r")",
    re.IGNORECASE,
)

# User message: requests a device/service action
_ACTION_REQUEST_RE = re.compile(
    r"(?:"
    r"turn\s+(?:on|off)|switch\s+(?:on|off)|"
    r"(?:dim|brighten)\b|"
    r"(?:lock|unlock)\b|"
    r"(?:open|close)\s+(?:the|my|all)|"
    r"set\s+.{1,40}\s+to\b|"
    r"(?:arm|disarm)\b|"
    r"shut\s+(?:off|down)|power\s+(?:on|off|down|up)|"
    r"lights?\s+(?:on|off)"
    r")",
    re.IGNORECASE,
)

# User message: correction after a failed action
_CORRECTION_RE = re.compile(
    r"(?:"
    r"still\s+(?:on|off|open|closed|locked|unlocked"
    r"|running|not)|"
    r"didn.t\s+(?:work|turn|change|happen)|"
    r"(?:they|it|that).{0,3}\s+(?:still|not)\s+"
    r"(?:on|off|done|working|changed)|"
    r"(?:are|is)\s+(?:still|not)\s+"
    r"(?:on|off|open|closed|locked|unlocked|changed)|"
    r"try\s+again|do\s+it\s+again|"
    r"you\s+didn|that\s+didn|"
    r"(?:no|nope|um)[,.]?\s*(?:they|it|still)"
    r")",
    re.IGNORECASE,
)


def _looks_like_device_action_claim(content: str) -> bool:
    """Check if text claims a device action was performed."""
    if not content or not isinstance(content, str):
        return False
    return bool(_CONFAB_CLAIM_RE.search(content))


def _user_expects_action(content: str) -> bool:
    """Check if user message requests an action or corrects a failed one."""
    if not content or not isinstance(content, str):
        return False
    return bool(
        _ACTION_REQUEST_RE.search(content)
        or _CORRECTION_RE.search(content)
    )


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
        nudge_count = 0
        tools_called: list[str] = []

        # Detect if user message expects a device action
        user_msg = next(
            (
                m.get("content", "")
                for m in messages
                if m.get("role") == "user"
            ),
            "",
        )
        user_wants_action = _user_expects_action(user_msg)

        for _iteration in range(max_iterations):
            try:
                kwargs = {
                    "model": settings.litellm_model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 2000,
                }
                if tool_defs:
                    kwargs["tools"] = tool_defs
                    # Force tool use when user expects a device
                    # action and no tools have been called yet.
                    # After tools run, switch back to auto so
                    # the model can summarise the result.
                    if (
                        (user_wants_action or nudge_count > 0)
                        and not tools_called
                    ):
                        kwargs["tool_choice"] = "required"
                    else:
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

                # Detect confabulation: AI claims action or user
                # expects action, but no tools were called yet.
                # If tools HAVE been called, the AI is just
                # summarising — not confabulating.
                if not tools_called:
                    is_confab = _looks_like_device_action_claim(
                        text
                    )
                    unmet_action = user_wants_action
                else:
                    is_confab = False
                    unmet_action = False

                if is_confab:
                    logger.warning(
                        "Responded with text only (no tool "
                        "calls); possible confabulation."
                    )
                if unmet_action:
                    logger.warning(
                        "User expects device action but no "
                        "tools were called."
                    )

                if (
                    (is_confab or unmet_action)
                    and tool_defs
                    and nudge_count < _MAX_CONFAB_NUDGES
                ):
                    nudge_count += 1
                    messages.append(msg.model_dump())
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "You MUST call a tool to perform "
                                "the action — do not describe or "
                                "claim it; actually call 'do', "
                                "'control_area', or the appropriate "
                                "tool right now."
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
            tool_names_this_turn = [
                tc.function.name for tc in msg.tool_calls
            ]
            logger.info(
                "LLM requested %d tool call(s): %s",
                len(msg.tool_calls),
                ", ".join(tool_names_this_turn),
            )
            messages.append(msg.model_dump())

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                logger.info(
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
