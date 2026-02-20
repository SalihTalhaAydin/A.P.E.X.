"""Tests for brain.conversation (Conversation orchestrator + helpers)."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain.conversation import Conversation, _looks_like_device_action_claim


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
# Module-level function: _looks_like_device_action_claim
# ===================================================================

class TestLooksLikeDeviceActionClaim:
    """Tests for the free-standing confabulation-detection helper."""

    @pytest.mark.parametrize(
        "text",
        [
            "I've turned on the kitchen light.",
            "I turned off the fan.",
            "I have cycled the switch.",
            "Turned the light on for you.",
            "Turned the lamp off.",
            "I've done it for you.",
            "I have completed the action.",
            "The system cycled the breaker.",
        ],
    )
    def test_positive_cases(self, text):
        assert _looks_like_device_action_claim(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "The weather is nice today.",
            "Sure, how can I help?",
            "Here are your calendar events.",
            "I don't have access to that device.",
            "",
        ],
    )
    def test_negative_cases(self, text):
        assert _looks_like_device_action_claim(text) is False

    def test_none_input(self):
        assert _looks_like_device_action_claim(None) is False

    def test_non_string_input(self):
        assert _looks_like_device_action_claim(123) is False


# ===================================================================
# Core handle() pipeline
# ===================================================================

class TestHandlePipeline:
    """Tests covering the top-level ``handle()`` orchestration."""

    @pytest.mark.asyncio
    async def test_handle_saves_user_turn(self, conv):
        """save_turn is called once with 'user' role and the message."""
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
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
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
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
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("OK")
            )
            await conv.handle("Turn on lights")

        conv.context_builder.build.assert_awaited_once_with("Turn on lights")

    @pytest.mark.asyncio
    async def test_handle_returns_response_text(self, conv):
        """handle() returns the final AI text."""
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("The answer is 42")
            )
            result = await conv.handle("What is the answer?")

        assert result == "The answer is 42"

    @pytest.mark.asyncio
    async def test_handle_triggers_background_fact_extraction(self, conv):
        """After responding, a background task is created for fact extraction."""
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("Done")
            )
            await conv.handle("Test message")

        # get_recent should have been called (to feed fact extraction)
        conv.conversation_store.get_recent.assert_awaited_once()
        # A background task should have been tracked
        # Wait briefly for the background task to be created and possibly finish
        await asyncio.sleep(0.05)
        # The task set should have been populated (task may already have completed
        # and been discarded, but the fact_extractor should have been invoked)


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
        tc = _make_tool_call("get_weather", {"city": "Austin"}, call_id="tc_1")
        first_resp = _make_llm_response(content=None, tool_calls=[tc])
        second_resp = _make_llm_response(content="It's sunny in Austin")

        fake_registry = {"get_weather": {}}
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.execute_tool", new_callable=AsyncMock) as mock_exec, \
             patch("brain.conversation.TOOL_REGISTRY", fake_registry):
            mock_litellm.acompletion = AsyncMock(side_effect=[first_resp, second_resp])
            mock_exec.return_value = '{"temp": 85}'

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "weather?"},
            ]
            result = await conv._ai_tool_loop(messages, tool_defs=[{"type": "function"}])

        assert result == "It's sunny in Austin"
        mock_exec.assert_awaited_once_with("get_weather", {"city": "Austin"})

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self, conv):
        """LLM returns two tool calls in one response, both are executed."""
        tc1 = _make_tool_call("get_weather", {"city": "Austin"}, call_id="tc_1")
        tc2 = _make_tool_call("get_time", {}, call_id="tc_2")
        first_resp = _make_llm_response(content=None, tool_calls=[tc1, tc2])
        second_resp = _make_llm_response(content="Weather is 85F and it's 3pm")

        fake_registry = {"get_weather": {}, "get_time": {}}
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.execute_tool", new_callable=AsyncMock) as mock_exec, \
             patch("brain.conversation.TOOL_REGISTRY", fake_registry):
            mock_litellm.acompletion = AsyncMock(side_effect=[first_resp, second_resp])
            mock_exec.side_effect = ['{"temp": 85}', '{"time": "15:00"}']

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "weather and time?"},
            ]
            result = await conv._ai_tool_loop(messages, tool_defs=[{"type": "function"}])

        assert result == "Weather is 85F and it's 3pm"
        assert mock_exec.await_count == 2

    @pytest.mark.asyncio
    async def test_max_iterations(self, conv):
        """After 15 iterations of tool calls the loop returns an error message."""
        # Every iteration returns a tool call, never text
        tc = _make_tool_call("looping_tool", {}, call_id="tc_loop")
        looping_resp = _make_llm_response(content=None, tool_calls=[tc])

        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.execute_tool", new_callable=AsyncMock) as mock_exec:
            mock_litellm.acompletion = AsyncMock(return_value=looping_resp)
            mock_exec.return_value = "result"

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "do something"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}], max_iterations=15
            )

        assert "loop" in result.lower()
        assert "rephrase" in result.lower()
        assert mock_litellm.acompletion.await_count == 15

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
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.execute_tool", new_callable=AsyncMock) as mock_exec, \
             patch("brain.conversation.TOOL_REGISTRY", fake_registry):
            mock_litellm.acompletion = AsyncMock(side_effect=[first_resp, second_resp])
            mock_exec.return_value = "ok"

            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "go"},
            ]
            result = await conv._ai_tool_loop(messages, tool_defs=[{"type": "function"}])

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
        """Text claiming 'turned on' is flagged when it's the first response."""
        # First response: confabulation claim (first response, messages len==2)
        # Second response after nudge: proper tool call
        # Third response: text answer
        confab_resp = _make_llm_response("I've turned on the lights for you.")
        tc = _make_tool_call("call_service", {"entity_id": "light.living"}, call_id="tc_1")
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response("Lights are now on.")

        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.execute_tool", new_callable=AsyncMock) as mock_exec:
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
        nudge_msg = messages[3]  # system, user, assistant(confab), user(nudge)
        assert "must use the tools" in nudge_msg["content"]

    @pytest.mark.asyncio
    async def test_nudge_retry_once(self, conv):
        """Confabulation nudge only happens once (retry_nudge_done flag)."""
        # First: confabulation -> nudge
        # Second: still confabulation -> should NOT nudge again, returns the text
        confab_resp1 = _make_llm_response("I've turned on the lights.")
        confab_resp2 = _make_llm_response("I turned off the fan.")

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[confab_resp1, confab_resp2]
            )
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "turn on lights"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        # After the first nudge, the second confabulation text is returned as-is
        # because is_first_response is now False (messages has grown beyond 2)
        assert result == "I turned off the fan."
        assert mock_litellm.acompletion.await_count == 2

    @pytest.mark.asyncio
    async def test_no_double_retry(self, conv):
        """Even if conditions appear to match again, only one nudge happens."""
        confab1 = _make_llm_response("I've turned on the lights.")
        confab2 = _make_llm_response("I turned off the fan.")

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[confab1, confab2]
            )
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "turn on lights"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        # Only 2 LLM calls: first confab -> nudge -> second confab -> return
        assert mock_litellm.acompletion.await_count == 2

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
# Explainability helpers
# ===================================================================

class TestExplainability:
    """Tests for ``_build_action_trace`` and ``_extract_facts_from_system``."""

    def test_build_action_trace_tools_only(self):
        result = Conversation._build_action_trace(
            tools_called=["get_weather", "call_service"],
            facts_used=[],
        )
        assert result == "Actions taken: get_weather, call_service"

    def test_build_action_trace_facts_only(self):
        result = Conversation._build_action_trace(
            tools_called=[],
            facts_used=["user_name", "location"],
        )
        assert result == "Based on: user_name, location"

    def test_build_action_trace_both(self):
        result = Conversation._build_action_trace(
            tools_called=["call_service"],
            facts_used=["preferred_temp"],
        )
        assert "Actions taken: call_service" in result
        assert "Based on: preferred_temp" in result
        assert " | " in result

    def test_build_action_trace_empty(self):
        result = Conversation._build_action_trace(
            tools_called=[],
            facts_used=[],
        )
        assert result == ""

    def test_build_action_trace_deduplicates_tools(self):
        result = Conversation._build_action_trace(
            tools_called=["call_service", "get_state", "call_service", "call_service"],
            facts_used=[],
        )
        assert result == "Actions taken: call_service, get_state"

    def test_extract_facts_from_system_prompt(self):
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Apex.\n"
                    "WHAT YOU KNOW ABOUT THE USER\n"
                    "- user_name: Salih\n"
                    "- location: Austin, TX\n"
                    "- preferred_temp: 72\n"
                    "END OF FACTS\n"
                ),
            },
            {"role": "user", "content": "hi"},
        ]
        facts = Conversation._extract_facts_from_system(messages)
        assert facts == ["user_name", "location", "preferred_temp"]

    def test_extract_facts_empty_when_no_section(self):
        messages = [
            {"role": "system", "content": "You are Apex. No facts here."},
            {"role": "user", "content": "hello"},
        ]
        facts = Conversation._extract_facts_from_system(messages)
        assert facts == []

    def test_extract_facts_stops_at_non_fact_line(self):
        """Parsing stops when a non-indented, non-dash line is encountered."""
        messages = [
            {
                "role": "system",
                "content": (
                    "WHAT YOU KNOW\n"
                    "- name: Alice\n"
                    "- city: Dallas\n"
                    "INSTRUCTIONS\n"
                    "- this_should_not_appear: true\n"
                ),
            },
        ]
        facts = Conversation._extract_facts_from_system(messages)
        assert facts == ["name", "city"]

    def test_extract_facts_skips_non_system_messages(self):
        """Only the first system message is parsed."""
        messages = [
            {"role": "user", "content": "WHAT YOU KNOW\n- fake: data"},
            {
                "role": "system",
                "content": "WHAT YOU KNOW\n- real_fact: value\n",
            },
        ]
        # The first system message is actually the second in the list
        facts = Conversation._extract_facts_from_system(messages)
        assert facts == ["real_fact"]

    @pytest.mark.asyncio
    async def test_action_trace_injected_on_second_call(self, conv):
        """After the first handle(), the action trace appears in the system prompt
        of the second handle() call."""
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[{"type": "function"}]), \
             patch("brain.conversation.execute_tool", new_callable=AsyncMock) as mock_exec:

            # First call: uses a tool so we get an action trace
            tc = _make_tool_call("call_service", {"entity": "light"}, call_id="tc_1")
            tool_resp = _make_llm_response(content=None, tool_calls=[tc])
            text_resp = _make_llm_response("Lights on.")
            mock_litellm.acompletion = AsyncMock(side_effect=[tool_resp, text_resp])
            mock_exec.return_value = "ok"

            await conv.handle("turn on lights", session_id="s1")
            # Give background task time to run
            await asyncio.sleep(0.05)

            # Verify the action trace was stored
            assert "call_service" in conv._action_traces.get("s1", "")

            # Second call: check that context_builder.build() result gets the trace appended
            conv.context_builder.build = AsyncMock(return_value="You are Apex.")
            normal_resp = _make_llm_response("Sure thing.")
            mock_litellm.acompletion = AsyncMock(return_value=normal_resp)

            await conv.handle("why did you do that?", session_id="s1")

            # The acompletion call should have messages where system prompt includes LAST ACTION TRACE
            call_args = mock_litellm.acompletion.call_args
            messages_sent = call_args.kwargs["messages"]
            system_content = messages_sent[0]["content"]
            assert "LAST ACTION TRACE" in system_content
            assert "call_service" in system_content


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
        conv.fact_extractor.extract_from_conversation = AsyncMock(return_value=None)
        turns = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        await conv._safe_extract_facts(turns)

        conv.fact_extractor.extract_from_conversation.assert_awaited_once()
        call_kwargs = conv.fact_extractor.extract_from_conversation.call_args.kwargs
        assert call_kwargs["turns"] == turns

    @pytest.mark.asyncio
    async def test_background_task_added_and_cleaned(self, conv):
        """Background tasks are added to the set and removed via done callback."""
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("ok")
            )
            await conv.handle("test")

        # Let background task complete
        await asyncio.sleep(0.1)
        # After completion the done_callback should have discarded the task
        assert len(conv._background_tasks) == 0


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:
    """Additional edge-case tests for completeness."""

    @pytest.mark.asyncio
    async def test_handle_default_session_id(self, conv):
        """When no session_id is passed, 'default' is used."""
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("hi")
            )
            await conv.handle("hello")

        calls = conv.conversation_store.save_turn.call_args_list
        # Both user and assistant save_turn calls use "default"
        assert calls[0].args[2] == "default"
        assert calls[1].args[2] == "default"

    @pytest.mark.asyncio
    async def test_handle_with_existing_action_trace(self, conv):
        """When an action trace exists for the session, it is appended to the system prompt."""
        conv._action_traces["s1"] = "Actions taken: call_service"

        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("ok")
            )
            await conv.handle("why?", session_id="s1")

        call_args = mock_litellm.acompletion.call_args
        messages_sent = call_args.kwargs["messages"]
        system_content = messages_sent[0]["content"]
        assert "LAST ACTION TRACE" in system_content
        assert "Actions taken: call_service" in system_content

    @pytest.mark.asyncio
    async def test_handle_no_action_trace_first_call(self, conv):
        """On first call with no prior trace, system prompt has no LAST ACTION TRACE."""
        with patch("brain.conversation.litellm") as mock_litellm, \
             patch("brain.conversation.get_openai_tool_definitions", return_value=[]):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("hi")
            )
            await conv.handle("hello", session_id="fresh")

        call_args = mock_litellm.acompletion.call_args
        messages_sent = call_args.kwargs["messages"]
        system_content = messages_sent[0]["content"]
        assert "LAST ACTION TRACE" not in system_content
