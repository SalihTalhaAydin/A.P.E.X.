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
    r"powered\s+(?:off|on|down|up)|shut\s+(?:off|down)|"
    # State claims ("lights are now off", "should be off")
    # Note: bare "on" and "set" are excluded from the is/are pattern
    # because they cause false positives ("meeting is on Monday",
    # "alarm is set for 7am"). They require "now" or "to" qualifiers.
    r"(?:is|are|should\s+be)\s+(?:now\s+)?(?:off|locked"
    r"|unlocked|open(?:ed)?|closed|armed|disarmed"
    r"|adjusted|dimmed)|"
    # "is/are now on/set" — require "now" to avoid false positives
    r"(?:is|are|should\s+be)\s+now\s+(?:on|set)|"
    # "should be on/off now" (word-order variant)
    r"should\s+be\s+(?:on|off)\s+now|"
    # "is/are set to <value>" — device value assignment
    r"(?:is|are)\s+set\s+to\b|"
    # Completion claims ("it is done", "taken care of")
    r"(?:it\s+is|it's|that's)\s+done|"
    r"taken\s+care\s+of|"
    # "all set" only at end of text or before punctuation/dash;
    # not "all set for tomorrow" (negative lookahead excludes "for")
    r"all\s+set(?!\s+for)(?:\s*[.!,;\u2014\u2013\-]|\s*$)|"
    r"all\s+done|"
    # First-person past claims ("I've turned…", "I have set…")
    r"i've\s+(?:turned|set|locked|unlocked|opened|closed|"
    r"adjusted|activated|dimmed|toggled|armed|disarmed|switched|powered)|"
    r"i\s+have\s+(?:turned|set|locked|unlocked|opened|closed|"
    r"adjusted|activated|dimmed|toggled|armed|disarmed|switched|powered)|"
    # Specific device action verbs
    r"\bcycled\b|adjusted\s+the|dimmed\s+the|brightened\s+the|"
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


# Tools that actually perform device/HA actions (vs discovery/query)
_ACTION_TOOLS = frozenset(
    {
        "do",
        "control_area",
        "control_light",
        "control_climate",
        "control_media",
        "control_cover",
        "control_fan",
        "control_lock",
        "control_switch",
        "control_alarm",
        "call_service",
        "activate_scene",
        "trigger_automation",
        "execute_script",
        "set_input_helper",
    }
)

# Tool result phrases that indicate the action did NOT succeed
_TOOL_FAILURE_PHRASES = (
    "no ",
    "entities found",
    "no entities",
    "not found",
    "error:",
    "entity not found",
    "could not",
    "cannot ",
    "failed",
)


def _looks_like_device_action_claim(content: str) -> bool:
    """Check if text claims a device action was performed."""
    if not content or not isinstance(content, str):
        return False
    return bool(_CONFAB_CLAIM_RE.search(content))


def _tool_result_indicates_failure(result: str) -> bool:
    """Check if a tool result indicates the action did not succeed."""
    if not result or not isinstance(result, str):
        return False
    lower = result.lower()
    return any(phrase in lower for phrase in _TOOL_FAILURE_PHRASES)


def _last_tool_result(messages: list[dict]) -> str:
    """Return the content of the most recent tool result message."""
    for m in reversed(messages):
        if m.get("role") == "tool":
            return m.get("content", "") or ""
    return ""


_INFO_QUESTION_RE = re.compile(
    r"^\s*(?:when|what\s+time|how\s+long|how\s+often|how\s+many"
    r"|was\s+the|were\s+the|is\s+the|are\s+the)\b",
    re.IGNORECASE,
)


def _tc_name(tc) -> str:
    """Safely get function name from a tool call (object or dict)."""
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        return fn.get("name", "") if isinstance(fn, dict) else ""
    try:
        fn = getattr(tc, "function", None)
        return getattr(fn, "name", "") or "" if fn else ""
    except (AttributeError, TypeError):
        return ""


def _tc_args(tc) -> str:
    """Safely get function arguments string from a tool call (object or dict)."""
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        return fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
    try:
        fn = getattr(tc, "function", None)
        return getattr(fn, "arguments", "{}") or "{}" if fn else "{}"
    except (AttributeError, TypeError):
        return "{}"


def _tc_id(tc) -> str:
    """Safely get tool_call_id from a tool call (object or dict)."""
    if isinstance(tc, dict):
        return tc.get("id", "") or ""
    try:
        return getattr(tc, "id", "") or ""
    except (AttributeError, TypeError):
        return ""


def _safe_get_tool_calls(msg) -> list:
    """Safely extract tool_calls from an LLM response message.
    Handles object (attr) and dict (get); treats None, [], missing key
    as no tool calls. Normalizes across providers with varying shapes.
    """
    if msg is None:
        return []

    def _normalize(val):
        if val is None:
            return []
        if isinstance(val, list):
            return val
        return [val]

    if isinstance(msg, dict):
        for key in ("tool_calls", "tool_call"):
            val = msg.get(key)
            if val is not None and val != []:
                return _normalize(val)
        return []

    try:
        for attr in ("tool_calls", "tool_call"):
            val = getattr(msg, attr, None)
            if val is not None and val != []:
                return _normalize(val)
        return []
    except (AttributeError, TypeError):
        return []


def _user_expects_action(content: str) -> bool:
    """Check if user message requests an action or corrects a failed one."""
    if not content or not isinstance(content, str):
        return False
    # Informational questions about state/history are not action requests
    if _INFO_QUESTION_RE.search(content):
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

        # Explainability: track action trace per session (bounded to prevent leak)
        self._action_traces: dict[str, str] = {}
        self._max_action_traces: int = 200

        # Per-session locks to prevent concurrent handle() interleaving
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._max_session_locks: int = 100
        self._session_locks_meta: asyncio.Lock = asyncio.Lock()

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
        Per-session locking prevents interleaving when concurrent requests
        share the same session_id.
        """
        # Get or create per-session lock (evict oldest when over capacity)
        async with self._session_locks_meta:
            if session_id not in self._session_locks:
                while len(self._session_locks) >= self._max_session_locks:
                    oldest = next(iter(self._session_locks))
                    del self._session_locks[oldest]
                self._session_locks[session_id] = asyncio.Lock()
            lock = self._session_locks[session_id]

        async with lock:
            return await self._handle_locked(user_message, session_id)

    async def _handle_locked(
        self, user_message: str, session_id: str
    ) -> str:
        """Run the full pipeline. Caller must hold the session lock."""
        # 1. Save user turn
        await self.conversation_store.save_turn(
            "user", user_message, session_id
        )

        # 2. Build rich context (recent history + relevant facts + time)
        system_prompt = await self.context_builder.build(
            user_message, session_id=session_id
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
            try:
                mcp_tools = self.mcp_bridge.get_openai_tool_definitions()
                if isinstance(mcp_tools, list):
                    tool_defs = tool_defs + mcp_tools
            except Exception as e:
                logger.warning("Failed to get MCP tool definitions: %s", e)

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
        total_chars = sum(
            len((t.get("content") or "")) for t in recent
        )
        if total_chars >= 50:  # skip for very short exchanges (ok, thanks, etc)
            task = asyncio.create_task(self._safe_extract_facts(recent))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return response_text

    async def shutdown(self) -> None:
        """Cancel and await all background fact-extraction tasks on shutdown."""
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            results = await asyncio.gather(
                *self._background_tasks, return_exceptions=True
            )
            for result in results:
                if isinstance(result, Exception) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    logger.warning("Fact extraction shutdown error: %s", result)
        self._background_tasks.clear()
        logger.info("Conversation background tasks shut down")

    async def _llm_call_with_retry(
        self,
        _max_retries: int = 3,
        _base_delay: float = 2.0,
        **kwargs,
    ):
        """Call litellm.acompletion with retry on rate limits."""
        from litellm.exceptions import RateLimitError

        for attempt in range(_max_retries):
            try:
                return await litellm.acompletion(**kwargs)
            except RateLimitError:
                if attempt == _max_retries - 1:
                    raise
                delay = _base_delay * (2**attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d), retrying in %.1fs...",
                    attempt + 1,
                    _max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("Unreachable: retry loop exhausted")

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
                        user_wants_action or nudge_count > 0
                    ) and not tools_called:
                        kwargs["tool_choice"] = "required"
                    else:
                        kwargs["tool_choice"] = "auto"

                response = await self._llm_call_with_retry(**kwargs)
            except Exception as e:
                logger.exception("AI call failed: %s", e)
                return f"Error reaching AI: {e}"

            if not response.choices:
                logger.error("LLM returned empty choices list")
                return "Error: AI returned an empty response."
            msg = response.choices[0].message
            tool_calls = _safe_get_tool_calls(msg)
            # only system + user so far?
            is_first_response = len(messages) == 2

            # If no tool calls, we have our answer (or a confabulation)
            if not tool_calls:
                text = msg.content or "Done."
                logger.debug(
                    "Text response (no tools called): %s", text[:150]
                )
                if is_first_response:
                    logger.debug("First response had 0 tool calls.")

                # Detect confabulation: AI claims action or user
                # expects action, but no tools were called yet.
                # If tools HAVE been called, the AI is just
                # summarising — not confabulating (unless tool failed).
                last_result = _last_tool_result(messages)
                if not tools_called:
                    is_confab = _looks_like_device_action_claim(text)
                    unmet_action = user_wants_action
                else:
                    is_confab = False
                    unmet_action = False
                    # User wanted action but only non-action tools
                    # (e.g. discover) were called — still unmet
                    if user_wants_action and not any(
                        t in _ACTION_TOOLS for t in tools_called
                    ):
                        unmet_action = True
                    # Tool reported failure but AI claims success
                    if (
                        _tool_result_indicates_failure(last_result)
                        and _looks_like_device_action_claim(text)
                    ):
                        is_confab = True
                        logger.warning(
                            "Tool reported failure but AI claimed success."
                        )

                if is_confab:
                    logger.warning(
                        "Responded with text only (no tool "
                        "calls); possible confabulation."
                    )
                if unmet_action:
                    logger.warning(
                        "User expects device action but no "
                        "action tools were called."
                    )

                if (
                    (is_confab or unmet_action)
                    and tool_defs
                    and nudge_count < _MAX_CONFAB_NUDGES
                ):
                    nudge_count += 1
                    messages.append(msg.model_dump())
                    nudge_content = (
                        "The tool reported no entities found or an error. "
                        "You must NOT claim success. Tell the user what "
                        "actually happened."
                        if is_confab and last_result
                        else (
                            "You MUST call a tool to perform "
                            "the action — do not describe or "
                            "claim it; actually call 'do', "
                            "'control_area', or the appropriate "
                            "tool right now."
                        )
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": nudge_content,
                        },
                    )
                    continue

                # Build and store action trace for explainability
                facts_used = self._extract_facts_from_system(messages)
                self._action_traces[session_id] = self._build_action_trace(
                    tools_called, facts_used
                )
                # Evict oldest entries if trace dict grows
                while len(self._action_traces) > self._max_action_traces:
                    oldest_key = next(iter(self._action_traces))
                    del self._action_traces[oldest_key]
                if self._action_traces.get(session_id):
                    logger.debug(
                        "Action trace: %s", self._action_traces[session_id]
                    )
                return text

            # Process tool calls (guard: tool_calls may be None/empty from provider)
            tool_names_this_turn = [n for tc in tool_calls if (n := _tc_name(tc))]
            logger.info(
                "LLM requested %d tool call(s): %s",
                len(tool_calls),
                ", ".join(tool_names_this_turn),
            )
            messages.append(msg.model_dump())

            for tc in tool_calls:
                fn_name = _tc_name(tc)
                if not fn_name:
                    logger.warning("Skipping tool call with missing function name")
                    continue
                try:
                    args = json.loads(_tc_args(tc))
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to parse tool args for %s: %s",
                        fn_name,
                        _tc_args(tc)[:200],
                    )
                    args = {}

                logger.info(
                    "Tool call: %s(%s)",
                    fn_name,
                    json.dumps(args, default=str)[:500],
                )

                # Route: native tool or MCP tool
                if fn_name in TOOL_REGISTRY:
                    result = await execute_tool(fn_name, args)
                elif self.mcp_bridge and self.mcp_bridge.has_tool(fn_name):
                    result = await self.mcp_bridge.execute_tool(
                        fn_name, args
                    )
                else:
                    result = f"Unknown tool: {fn_name}"
                # INFO for diagnostics: tool results must be visible when debugging
                # "turn off X" claims-success-but-nothing-happened issues
                logger.info(
                    "Tool result: %s -> %s",
                    fn_name,
                    str(result)[:500],
                )

                # Track for explainability
                tools_called.append(fn_name)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": _tc_id(tc),
                        "content": str(result),
                    }
                )

        # Build and store action trace before max_iterations exit
        # (explainability: user can see which tools were called)
        facts_used = self._extract_facts_from_system(messages)
        self._action_traces[session_id] = self._build_action_trace(
            tools_called, facts_used
        )
        while len(self._action_traces) > self._max_action_traces:
            oldest_key = next(iter(self._action_traces))
            del self._action_traces[oldest_key]

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
            trace_parts.append(f"Actions taken: {', '.join(unique)}")
        if facts_used:
            trace_parts.append(f"Based on: {', '.join(facts_used)}")
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
