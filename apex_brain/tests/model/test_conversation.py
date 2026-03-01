"""Tests for brain.conversation (Conversation orchestrator + helpers)."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from brain.conversation import Conversation

# ---------------------------------------------------------------------------
# Helpers: build realistic LiteLLM-style mock responses
# ---------------------------------------------------------------------------


def _make_tool_call(name: str, arguments: dict, call_id: str = "tc_1"):
    """Create a mock tool_call object matching litellm's structure."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_llm_response(content: str = "Hello!", tool_calls=None):
    """Return an object shaped like ``litellm.acompletion()`` result.

    ``response.choices[0].message.content``
    ``response.choices[0].message.tool_calls``
    ``response.choices[0].message.model_dump()``
    """
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or None

    def _model_dump():
        dump = {"role": "assistant", "content": content}
        if tool_calls:
            dump["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
        return dump

    msg.model_dump = _model_dump

    response = MagicMock()
    response.choices = [SimpleNamespace(message=msg)]
    return response


# ---------------------------------------------------------------------------
# Fixture: build a Conversation with all deps mocked
# ---------------------------------------------------------------------------


@pytest.fixture
def conv():
    """Return a Conversation instance with fully mocked dependencies."""
    conversation_store = AsyncMock()
    conversation_store.save_turn = AsyncMock()
    conversation_store.get_recent = AsyncMock(return_value=[])

    knowledge_store = AsyncMock()
    fact_extractor = AsyncMock()
    fact_extractor.extract_from_conversation = AsyncMock()

    context_builder = AsyncMock()
    context_builder.build = AsyncMock(return_value="You are Apex.")

    with patch("brain.conversation.settings") as mock_settings:
        mock_settings.openai_api_key = ""
        mock_settings.anthropic_api_key = ""
        mock_settings.litellm_model = "test-model"

        c = Conversation(
            conversation_store=conversation_store,
            knowledge_store=knowledge_store,
            fact_extractor=fact_extractor,
            context_builder=context_builder,
        )
    return c


# ===================================================================
# Core handle() pipeline
# ===================================================================


class TestHandlePipeline:
    """Tests covering the top-level ``handle()`` orchestration."""

    @pytest.mark.asyncio
    async def test_handle_saves_user_turn(self, conv):
        """save_turn is called once with 'user' role and the message."""
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("Hi there")
            )
            await conv.handle("Hello", session_id="s1")

        # First call should be the user turn
        calls = conv.conversation_store.save_turn.call_args_list
        assert calls[0].args == ("user", "Hello", "s1")

    @pytest.mark.asyncio
    async def test_handle_saves_assistant_turn(self, conv):
        """save_turn is called a second time with 'assistant' and the response."""
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("Bot reply")
            )
            result = await conv.handle("Hey", session_id="s1")

        calls = conv.conversation_store.save_turn.call_args_list
        assert calls[1].args == ("assistant", "Bot reply", "s1")
        assert result == "Bot reply"

    @pytest.mark.asyncio
    async def test_handle_builds_context(self, conv):
        """context_builder.build is called with the user message."""
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("OK")
            )
            await conv.handle("Turn on lights")

        conv.context_builder.build.assert_awaited_once_with(
            "Turn on lights", session_id="default",
            voice_mode=False,
        )

    @pytest.mark.asyncio
    async def test_handle_returns_response_text(self, conv):
        """handle() returns the final AI text."""
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("The answer is 42")
            )
            result = await conv.handle("What is the answer?")

        assert result == "The answer is 42"

    @pytest.mark.asyncio
    async def test_handle_triggers_background_fact_extraction(self, conv):
        """After responding, a background task is created for fact extraction."""
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("Done")
            )
            await conv.handle("Test message")

        # get_recent should have been called (to feed fact extraction)
        conv.conversation_store.get_recent.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_mcp_bridge_raise_still_returns_response(
        self, conv
    ):
        """When mcp_bridge.get_openai_tool_definitions raises, handle() still returns."""
        mock_bridge = MagicMock()
        mock_bridge.connected = True
        mock_bridge.get_openai_tool_definitions.side_effect = RuntimeError(
            "MCP broken"
        )
        conv.mcp_bridge = mock_bridge

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("Fallback response")
            )
            result = await conv.handle("Hello", session_id="s1")

        assert result == "Fallback response"
        await asyncio.sleep(0.05)


# ===================================================================
# AI tool loop
# ===================================================================


class TestAIToolLoop:
    """Tests for ``_ai_tool_loop``."""

    @pytest.mark.asyncio
    async def test_text_response_no_tools(self, conv):
        """When the LLM returns text with no tool_calls, return it directly."""
        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("Simple answer")
            )
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ]
            result = await conv._ai_tool_loop(messages, tool_defs=[])

        assert result == "Simple answer"

    @pytest.mark.asyncio
    async def test_single_tool_call(self, conv):
        """LLM calls one tool, then returns text on the next iteration."""
        tc = _make_tool_call(
            "get_weather", {"city": "Austin"}, call_id="tc_1"
        )
        first_resp = _make_llm_response(content=None, tool_calls=[tc])
        second_resp = _make_llm_response(content="It's sunny in Austin")

        fake_registry = {"get_weather": {}}
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.execute_tool", new_callable=AsyncMock
            ) as mock_exec,
            patch("brain.conversation.TOOL_REGISTRY", fake_registry),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[first_resp, second_resp]
            )
            mock_exec.return_value = '{"temp": 85}'

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "weather?"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        assert result == "It's sunny in Austin"
        mock_exec.assert_awaited_once_with(
            "get_weather", {"city": "Austin"}
        )

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self, conv):
        """LLM returns two tool calls in one response, both are executed."""
        tc1 = _make_tool_call(
            "get_weather", {"city": "Austin"}, call_id="tc_1"
        )
        tc2 = _make_tool_call("get_time", {}, call_id="tc_2")
        first_resp = _make_llm_response(
            content=None, tool_calls=[tc1, tc2]
        )
        second_resp = _make_llm_response(
            content="Weather is 85F and it's 3pm"
        )

        fake_registry = {"get_weather": {}, "get_time": {}}
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.execute_tool", new_callable=AsyncMock
            ) as mock_exec,
            patch("brain.conversation.TOOL_REGISTRY", fake_registry),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[first_resp, second_resp]
            )
            mock_exec.side_effect = ['{"temp": 85}', '{"time": "15:00"}']

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "weather and time?"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        assert result == "Weather is 85F and it's 3pm"
        assert mock_exec.await_count == 2

    @pytest.mark.asyncio
    async def test_max_iterations(self, conv):
        """After 15 iterations of tool calls the loop returns an error message."""
        # Every iteration returns a tool call, never text
        tc = _make_tool_call("looping_tool", {}, call_id="tc_loop")
        looping_resp = _make_llm_response(content=None, tool_calls=[tc])

        fake_registry = {"looping_tool": {}}
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.execute_tool", new_callable=AsyncMock
            ) as mock_exec,
            patch("brain.conversation.TOOL_REGISTRY", fake_registry),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=looping_resp)
            mock_exec.return_value = "result"

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "do something"},
            ]
            result = await conv._ai_tool_loop(
                messages,
                tool_defs=[{"type": "function"}],
                max_iterations=15,
            )

        assert isinstance(result, str)
        assert "loop" in result.lower()
        assert "rephrase" in result.lower()
        assert mock_litellm.acompletion.await_count == 15
        # Verify execute_tool was called each iteration
        assert mock_exec.await_count == 15

    @pytest.mark.asyncio
    async def test_malformed_tool_json(self, conv):
        """Invalid JSON in tool arguments defaults to empty dict."""
        tc = MagicMock()
        tc.id = "tc_bad"
        tc.function.name = "some_tool"
        tc.function.arguments = "NOT VALID JSON{{{"

        first_resp = _make_llm_response(content=None, tool_calls=[tc])
        second_resp = _make_llm_response(content="Handled it")

        fake_registry = {"some_tool": {}}
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.execute_tool", new_callable=AsyncMock
            ) as mock_exec,
            patch("brain.conversation.TOOL_REGISTRY", fake_registry),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[first_resp, second_resp]
            )
            mock_exec.return_value = "ok"

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "go"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        # execute_tool should have been called with empty dict for args
        mock_exec.assert_awaited_once_with("some_tool", {})
        assert result == "Handled it"

    @pytest.mark.asyncio
    async def test_llm_failure(self, conv):
        """When litellm.acompletion raises, the loop returns an error string."""
        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=RuntimeError("API timeout")
            )
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ]
            result = await conv._ai_tool_loop(messages, tool_defs=[])

        assert "Error reaching AI" in result
        assert "API timeout" in result

    @pytest.mark.asyncio
    async def test_no_tool_defs_omits_tools_kwarg(self, conv):
        """When tool_defs is empty, 'tools' and 'tool_choice' are not passed."""
        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("No tools here")
            )
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ]
            await conv._ai_tool_loop(messages, tool_defs=[])

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert "tools" not in call_kwargs
        assert "tool_choice" not in call_kwargs

    @pytest.mark.asyncio
    async def test_tool_defs_present_includes_tools_kwarg(self, conv):
        """When tool_defs is non-empty, 'tools' and 'tool_choice' are passed."""
        tool_defs = [{"type": "function", "function": {"name": "foo"}}]

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("With tools")
            )
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ]
            await conv._ai_tool_loop(messages, tool_defs=tool_defs)

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["tools"] == tool_defs
        assert call_kwargs["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_tool_choice_required_for_action_requests(self, conv):
        """tool_choice='required' when user requests a device action."""
        tc = _make_tool_call("do", {"domain": "light"}, call_id="tc_1")
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response("Lights off.")

        fake_registry = {"do": {}}
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.execute_tool", new_callable=AsyncMock
            ) as mock_exec,
            patch("brain.conversation.TOOL_REGISTRY", fake_registry),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            mock_exec.return_value = "ok"

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "turn off the lights"},
            ]
            tool_defs = [{"type": "function", "function": {"name": "do"}}]
            await conv._ai_tool_loop(messages, tool_defs=tool_defs)

        # First call: action request, no tools called yet -> required
        first_call_kwargs = mock_litellm.acompletion.call_args_list[
            0
        ].kwargs
        assert first_call_kwargs["tool_choice"] == "required"
        # Second call: tools already called -> auto (let model summarise)
        second_call_kwargs = mock_litellm.acompletion.call_args_list[
            1
        ].kwargs
        assert second_call_kwargs["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_tool_choice_auto_for_non_action(self, conv):
        """tool_choice='auto' for normal non-action queries."""
        tool_defs = [{"type": "function", "function": {"name": "foo"}}]

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("The weather is sunny.")
            )
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "what's the weather?"},
            ]
            await conv._ai_tool_loop(messages, tool_defs=tool_defs)

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_none_content_becomes_done(self, conv):
        """If msg.content is None and no tool_calls, the fallback is 'Done.'."""
        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None)
            )
            # Need to set tool_calls to None explicitly
            resp = _make_llm_response(content=None)
            resp.choices[0].message.content = None
            resp.choices[0].message.tool_calls = None
            mock_litellm.acompletion = AsyncMock(return_value=resp)

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ]
            result = await conv._ai_tool_loop(messages, tool_defs=[])

        assert result == "Done."


# ===================================================================
# Confabulation guard
# ===================================================================


class TestConfabulationGuard:
    """Tests for the confabulation-detection retry logic."""

    @pytest.mark.asyncio
    async def test_detects_turned_on(self, conv):
        """Text claiming 'turned on' triggers nudge and retries with tools."""
        confab_resp = _make_llm_response(
            "I've turned on the lights for you."
        )
        tc = _make_tool_call(
            "call_service", {"entity_id": "light.living"}, call_id="tc_1"
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response("Lights are now on.")

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.execute_tool", new_callable=AsyncMock
            ) as mock_exec,
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[confab_resp, tool_resp, final_resp]
            )
            mock_exec.return_value = "ok"

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "turn on lights"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        assert result == "Lights are now on."
        # The nudge added a user message telling the model to use tools
        nudge_msg = messages[
            3
        ]  # system, user, assistant(confab), user(nudge)
        assert "MUST call a tool" in nudge_msg["content"]

    @pytest.mark.asyncio
    async def test_detects_jarvis_style_confab(self, conv):
        """JARVIS-style phrasing ('lights are now off') triggers nudge."""
        confab_resp = _make_llm_response(
            "Very well. The basement lights are now off."
        )
        tc = _make_tool_call(
            "do",
            {
                "domain": "light",
                "service": "turn_off",
                "targets": {"area_id": "basement"},
            },
            call_id="tc_1",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response("Done — basement lights off.")

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.execute_tool", new_callable=AsyncMock
            ) as mock_exec,
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[confab_resp, tool_resp, final_resp]
            )
            mock_exec.return_value = "ok"

            messages = [
                {"role": "system", "content": "sys"},
                {
                    "role": "user",
                    "content": "turn off the basement lights",
                },
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        assert result == "Done — basement lights off."
        assert mock_litellm.acompletion.await_count == 3

    @pytest.mark.asyncio
    async def test_nudge_retries_up_to_max(self, conv):
        """Confabulation nudge happens up to _MAX_CONFAB_NUDGES times."""
        confab1 = _make_llm_response("I've turned on the lights.")
        confab2 = _make_llm_response("I turned off the fan.")
        confab3 = _make_llm_response("Done, lights are set.")

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[confab1, confab2, confab3]
            )
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "turn on lights"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        # After 2 nudges (max), the third confabulation is returned
        assert result == "Done, lights are set."
        assert mock_litellm.acompletion.await_count == 3

    @pytest.mark.asyncio
    async def test_no_excessive_retry(self, conv):
        """Nudge retries are capped; no infinite loop."""
        responses = [
            _make_llm_response("I've turned on the lights."),
            _make_llm_response("I turned off the fan."),
            _make_llm_response("All set — lights are on."),
        ]

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=responses)
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "turn on lights"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        # Exactly 3 LLM calls: confab -> nudge -> confab -> nudge -> return
        assert mock_litellm.acompletion.await_count == 3

    @pytest.mark.asyncio
    async def test_allows_normal_text(self, conv):
        """Non-device-action text passes through without any nudge."""
        normal_resp = _make_llm_response("The weather is nice today.")

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=normal_resp)
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "what's the weather?"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        assert result == "The weather is nice today."
        # Only one LLM call (no retry)
        assert mock_litellm.acompletion.await_count == 1

    @pytest.mark.asyncio
    async def test_confab_guard_no_nudge_without_tool_defs(self, conv):
        """When tool_defs is empty, confabulation does not trigger nudge."""
        confab_resp = _make_llm_response("I've turned on the lights.")

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=confab_resp)
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "turn on lights"},
            ]
            result = await conv._ai_tool_loop(messages, tool_defs=[])

        # Returns the confabulated text since there are no tools to nudge toward
        assert result == "I've turned on the lights."
        assert mock_litellm.acompletion.await_count == 1


# ===================================================================
# Background tasks
# ===================================================================


class TestBackgroundTasks:
    """Tests for ``_safe_extract_facts`` and background task management."""

    @pytest.mark.asyncio
    async def test_safe_extract_facts_handles_exception(self, conv):
        """If fact extraction raises, the exception is caught and logged."""
        conv.fact_extractor.extract_from_conversation = AsyncMock(
            side_effect=RuntimeError("DB connection lost")
        )
        # Should NOT raise
        await conv._safe_extract_facts([{"role": "user", "content": "hi"}])

        # Verify extract_from_conversation was called
        conv.fact_extractor.extract_from_conversation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_safe_extract_facts_calls_extractor(self, conv):
        """Normal case: facts are extracted without error."""
        conv.fact_extractor.extract_from_conversation = AsyncMock(
            return_value=None
        )
        turns = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        await conv._safe_extract_facts(turns)

        conv.fact_extractor.extract_from_conversation.assert_awaited_once()
        call_kwargs = (
            conv.fact_extractor.extract_from_conversation.call_args.kwargs
        )
        assert call_kwargs["turns"] == turns

    @pytest.mark.asyncio
    async def test_background_task_added_and_cleaned(self, conv):
        """Background tasks are added to the set and removed via done callback."""
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("ok")
            )
            await conv.handle("test")

        # Let background task complete
        await asyncio.sleep(0.1)
        # After completion the done_callback should have discarded the task
        assert len(conv._background_tasks) == 0


# ===================================================================
# Per-session locking (BUG 2 regression)
# ===================================================================


class TestSessionLocking:
    """Regression tests for per-session locking to prevent concurrent interleaving."""

    @pytest.mark.asyncio
    async def test_concurrent_handle_same_session_no_interleaving(
        self, conv
    ):
        """Two concurrent handle() calls with same session_id must run serially."""
        save_order: list[tuple[str, str, str]] = []

        async def record_save_turn(
            role: str, content: str, session_id: str = "default"
        ):
            save_order.append((role, content, session_id))

        conv.conversation_store.save_turn = AsyncMock(
            side_effect=record_save_turn
        )
        conv.conversation_store.get_recent = AsyncMock(return_value=[])

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response("Response A"),
                    _make_llm_response("Response B"),
                ]
            )
            await asyncio.gather(
                conv.handle("Message A", session_id="shared"),
                conv.handle("Message B", session_id="shared"),
            )

        assert len(save_order) == 4
        roles = [r for r, _, _ in save_order]
        assert roles == ["user", "assistant", "user", "assistant"]
        contents = {c for _, c, _ in save_order}
        assert contents == {
            "Message A",
            "Message B",
            "Response A",
            "Response B",
        }

    @pytest.mark.asyncio
    async def test_concurrent_handle_different_sessions_allowed(
        self, conv
    ):
        """Different session_ids can run in parallel; no cross-session blocking."""
        save_order: list[tuple[str, str, str]] = []

        async def record_save_turn(
            role: str, content: str, session_id: str = "default"
        ):
            save_order.append((role, content, session_id))

        conv.conversation_store.save_turn = AsyncMock(
            side_effect=record_save_turn
        )
        conv.conversation_store.get_recent = AsyncMock(return_value=[])

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response("R1"),
                    _make_llm_response("R2"),
                ]
            )
            await asyncio.gather(
                conv.handle("M1", session_id="session_1"),
                conv.handle("M2", session_id="session_2"),
            )

        assert len(save_order) == 4
        roles_and_sessions = [(r, s) for r, _, s in save_order]
        assert ("user", "session_1") in roles_and_sessions
        assert ("user", "session_2") in roles_and_sessions
        assert ("assistant", "session_1") in roles_and_sessions
        assert ("assistant", "session_2") in roles_and_sessions


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Additional edge-case tests for completeness."""

    @pytest.mark.asyncio
    async def test_handle_default_session_id(self, conv):
        """When no session_id is passed, 'default' is used."""
        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("hi")
            )
            await conv.handle("hello")

        calls = conv.conversation_store.save_turn.call_args_list
        # Both user and assistant save_turn calls use "default"
        assert calls[0].args[2] == "default"
        assert calls[1].args[2] == "default"

    @pytest.mark.asyncio
    async def test_handle_concurrent_same_session_serialized(self, conv):
        """Concurrent handles with the same session_id are serialized (no interleaving)."""
        # Track order of save_turn calls; concurrent calls would interleave user/assistant
        save_order: list[tuple[str, str]] = []

        async def track_save(role: str, content: str, sid: str):
            save_order.append((role, sid))
            await asyncio.sleep(0.02)  # Allow other coroutines to run

        conv.conversation_store.save_turn = AsyncMock(
            side_effect=track_save
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("response")
            )
            # Run two handles with same session_id concurrently
            await asyncio.gather(
                conv.handle("msg1", session_id="shared"),
                conv.handle("msg2", session_id="shared"),
            )

        # With per-session lock: each handle does user then assistant atomically
        # Expect: (user,shared), (assistant,shared), (user,shared), (assistant,shared)
        user_indices = [
            i for i, (r, _) in enumerate(save_order) if r == "user"
        ]
        asst_indices = [
            i for i, (r, _) in enumerate(save_order) if r == "assistant"
        ]
        assert len(user_indices) == 2 and len(asst_indices) == 2
        assert (
            user_indices[0]
            < asst_indices[0]
            < user_indices[1]
            < asst_indices[1]
        )
