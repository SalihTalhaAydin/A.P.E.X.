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
    get_voice_tool_definitions,
)

from brain.config import settings

# Maximum nudge retries when confabulation is detected
_MAX_CONFAB_NUDGES = 2

# ------------------------------------------------------------------
# Confabulation detection (simplified)
# ------------------------------------------------------------------

# AI claims a device action was performed
_CONFAB_CLAIM_RE = re.compile(
    r"(?:"
    r"turned\s+(?:off|on)|switched\s+(?:off|on)|"
    r"(?:is|are)\s+now\s+(?:on|off|set|locked|unlocked)|"
    r"(?:it\s+is|it's|that's)\s+done|"
    r"taken\s+care\s+of|all\s+done|"
    r"i've\s+(?:turned|set|locked|unlocked|opened|closed|"
    r"adjusted|activated|dimmed|toggled|armed|disarmed|switched)"
    r")",
    re.IGNORECASE,
)

# User requests a device action
_ACTION_REQUEST_RE = re.compile(
    r"(?:"
    r"turn\s+(?:on|off)|switch\s+(?:on|off)|"
    r"(?:dim|brighten)\b|(?:lock|unlock)\b|"
    r"(?:open|close)\s+(?:the|my|all)|"
    r"set\s+.{1,40}\s+to\b|"
    r"(?:arm|disarm)\b|"
    r"shut\s+(?:off|down)|power\s+(?:on|off|down|up)|"
    r"lights?\s+(?:on|off)"
    r")",
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
    """Safely get function arguments string from a tool call."""
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        return fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
    try:
        fn = getattr(tc, "function", None)
        return getattr(fn, "arguments", "{}") or "{}" if fn else "{}"
    except (AttributeError, TypeError):
        return "{}"


def _tc_id(tc) -> str:
    """Safely get tool_call_id from a tool call."""
    if isinstance(tc, dict):
        return tc.get("id", "") or ""
    try:
        return getattr(tc, "id", "") or ""
    except (AttributeError, TypeError):
        return ""


def _safe_get_tool_calls(msg) -> list:
    """Safely extract tool_calls from an LLM response message."""
    if msg is None:
        return []

    if isinstance(msg, dict):
        val = msg.get("tool_calls")
        if isinstance(val, list) and val:
            return val
        return []

    try:
        val = getattr(msg, "tool_calls", None)
        if isinstance(val, list) and val:
            return val
        return []
    except (AttributeError, TypeError):
        return []


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
        self,
        user_message: str,
        session_id: str = "default",
        voice_mode: bool = False,
    ) -> str:
        """
        Process a user message through the full Apex pipeline.
        Returns the final response text.
        Per-session locking prevents interleaving when concurrent requests
        share the same session_id.

        voice_mode: when True, uses reduced tool set and
        shorter max_tokens for faster responses.
        """
        # Get or create per-session lock
        async with self._session_locks_meta:
            if session_id not in self._session_locks:
                while len(self._session_locks) >= self._max_session_locks:
                    oldest = next(iter(self._session_locks))
                    del self._session_locks[oldest]
                self._session_locks[session_id] = asyncio.Lock()
            lock = self._session_locks[session_id]

        async with lock:
            return await self._handle_locked(
                user_message, session_id, voice_mode
            )

    async def _handle_locked(
        self, user_message: str, session_id: str,
        voice_mode: bool = False,
    ) -> str:
        """Run the full pipeline. Caller must hold the session lock."""
        # 1. Save user turn
        await self.conversation_store.save_turn(
            "user", user_message, session_id
        )

        # 2. Build context (recent history + facts + time + devices)
        system_prompt = await self.context_builder.build(
            user_message, session_id=session_id,
            voice_mode=voice_mode,
        )

        # 3. Prepare messages for the AI
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 4. Get tool definitions (native + MCP)
        if voice_mode:
            tool_defs = get_voice_tool_definitions()
        else:
            tool_defs = get_openai_tool_definitions()
            if self.mcp_bridge and self.mcp_bridge.connected:
                try:
                    mcp_tools = (
                        self.mcp_bridge.get_openai_tool_definitions()
                    )
                    if isinstance(mcp_tools, list):
                        tool_defs = tool_defs + mcp_tools
                except Exception as e:
                    logger.warning(
                        "Failed to get MCP tool definitions: %s", e
                    )

        # 5. Call AI with tool loop
        response_text = await self._ai_tool_loop(
            messages, tool_defs, session_id=session_id,
            voice_mode=voice_mode,
        )

        # 6. Save assistant response
        await self.conversation_store.save_turn(
            "assistant", response_text, session_id
        )

        # 7. Background fact extraction
        recent = await self.conversation_store.get_recent(
            n=4, session_id=session_id
        )
        total_chars = sum(len(t.get("content") or "") for t in recent)
        if total_chars >= 50:
            task = asyncio.create_task(self._safe_extract_facts(recent))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return response_text

    async def shutdown(self) -> None:
        """Cancel and await all background tasks on shutdown."""
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
                    logger.warning(
                        "Background task shutdown error: %s",
                        result,
                    )
        self._background_tasks.clear()
        logger.info("Conversation background tasks shut down")

    async def _llm_call_with_retry(
        self,
        _max_retries: int = 3,
        _base_delay: float = 2.0,
        **kwargs,
    ):
        """Call litellm.acompletion with retry on transient errors."""
        import openai
        from litellm.exceptions import RateLimitError

        _RETRYABLE = (
            RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            ConnectionError,
            TimeoutError,
        )

        for attempt in range(_max_retries):
            try:
                return await litellm.acompletion(**kwargs)
            except _RETRYABLE as exc:
                if attempt == _max_retries - 1:
                    raise
                delay = _base_delay * (2**attempt)
                logger.warning(
                    "%s (attempt %d/%d), retrying in %.1fs...",
                    type(exc).__name__,
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
        voice_mode: bool = False,
    ) -> str:
        """Call AI, handle tool calls, repeat until text response."""
        nudge_count = 0
        tools_called: list[str] = []

        # Voice mode: fewer iterations, shorter output
        if voice_mode:
            max_iterations = min(max_iterations, 5)

        # Detect if user message requests a device action
        user_msg = next(
            (
                m.get("content", "")
                for m in messages
                if m.get("role") == "user"
            ),
            "",
        )
        user_wants_action = (
            bool(_ACTION_REQUEST_RE.search(user_msg))
            if user_msg
            else False
        )

        for _iteration in range(max_iterations):
            try:
                kwargs = {
                    "model": settings.litellm_model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 500 if voice_mode else 2000,
                }
                if tool_defs:
                    kwargs["tools"] = tool_defs
                    # Force tool use when user expects action
                    # and no tools have been called yet
                    if (
                        user_wants_action or nudge_count > 0
                    ) and not tools_called:
                        kwargs["tool_choice"] = "required"
                    else:
                        kwargs["tool_choice"] = "auto"

                response = await self._llm_call_with_retry(**kwargs)
            except Exception as e:
                logger.exception("AI call failed: %s", e)
                import openai as _openai

                model = settings.litellm_model
                if isinstance(
                    e,
                    (
                        _openai.APIConnectionError,
                        ConnectionError,
                    ),
                ):
                    return (
                        f"Connection error reaching {model}. "
                        "Check your API key and network."
                    )
                elif isinstance(e, _openai.AuthenticationError):
                    return f"Auth failed for {model}. Check your API key."
                else:
                    return f"Error reaching AI ({model}): {e}"

            if not response.choices:
                return "Error: AI returned an empty response."

            msg = response.choices[0].message
            tool_calls = _safe_get_tool_calls(msg)

            # No tool calls — we have our answer
            if not tool_calls:
                text = msg.content or "Done."

                # Confabulation check: AI claims action but
                # never called any tools
                if (
                    not tools_called
                    and _CONFAB_CLAIM_RE.search(text)
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
                                "the action — do not just claim "
                                "it was done. Call 'do' or the "
                                "appropriate tool now."
                            ),
                        },
                    )
                    continue

                return text

            # Process tool calls
            tool_names = [n for tc in tool_calls if (n := _tc_name(tc))]
            logger.info(
                "LLM requested %d tool(s): %s",
                len(tool_calls),
                ", ".join(tool_names),
            )
            messages.append(msg.model_dump())

            for tc in tool_calls:
                fn_name = _tc_name(tc)
                if not fn_name:
                    continue
                try:
                    args = json.loads(_tc_args(tc))
                except json.JSONDecodeError:
                    args = {}

                logger.info(
                    "Tool: %s(%s)",
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

                logger.info(
                    "Result: %s -> %s",
                    fn_name,
                    str(result)[:500],
                )

                tools_called.append(fn_name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": _tc_id(tc),
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
