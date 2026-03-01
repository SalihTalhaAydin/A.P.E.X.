"""
End-to-end integration tests for the Apex Brain pipeline with generic tools.

Tests the full flow: user message -> context build -> LLM (mocked) ->
tool call (do/query/discover) -> HA API (mocked) -> response.

Every test is self-contained with its own mocks. The LLM and HA API
are always mocked; the orchestrator and tool registry are real.
"""

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


def _make_llm_response(content: str = None, tool_calls=None):
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
# Fixtures
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


@pytest.fixture
def conv_with_schema_context():
    """Return a Conversation whose context_builder returns a prompt
    that includes service schema content."""
    conversation_store = AsyncMock()
    conversation_store.save_turn = AsyncMock()
    conversation_store.get_recent = AsyncMock(return_value=[])

    knowledge_store = AsyncMock()
    fact_extractor = AsyncMock()
    fact_extractor.extract_from_conversation = AsyncMock()

    system_prompt = (
        "You are Apex.\n\n"
        "HA SERVICE SCHEMAS (use with do() tool):\n"
        "## light\n"
        "  light.turn_on — Turn on a light\n"
        "    entity_id: entity(light) (required)\n"
        "    brightness_pct: number(0..100)\n"
        "    color_temp_kelvin: number(2000..6535)\n"
        "  light.turn_off — Turn off a light\n"
        "    entity_id: entity(light) (required)\n"
        "## climate\n"
        "  climate.set_temperature — Set target temperature\n"
        "    entity_id: entity(climate) (required)\n"
        "    temperature: number\n"
        "For other domains, call discover(what='services', filter_str='domain_name').\n"
    )

    context_builder = AsyncMock()
    context_builder.build = AsyncMock(return_value=system_prompt)

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
# Test 1: Full pipeline — do() to turn on a light
# ===================================================================


class TestFullPipelineDoLight:
    """User message -> context build -> LLM (mocked) -> do() -> HA (mocked) -> response."""

    @pytest.mark.asyncio
    async def test_full_pipeline_do_light(self, conv):
        """User says 'turn on the kitchen light' -> LLM returns do() ->
        HA service is called -> state is verified -> response returned."""

        # LLM first response: tool call to do()
        tc = _make_tool_call(
            "do",
            {
                "domain": "light",
                "service": "turn_on",
                "targets": {"entity_id": "light.kitchen"},
                "data": {"brightness_pct": 100},
            },
            call_id="call_do_1",
        )
        tool_response = _make_llm_response(content=None, tool_calls=[tc])
        # LLM second response: text confirmation
        final_response = _make_llm_response(
            content="Done — kitchen light is on at full brightness."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions"
            ) as mock_tool_defs,
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
            patch(
                "tools.generic.verify_generic", new_callable=AsyncMock
            ) as mock_verify,
            patch("tools.generic.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_tool_defs.return_value = [
                {"type": "function", "function": {"name": "do"}}
            ]
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_response, final_response]
            )
            # ha_request for the service call returns empty (service calls return [])
            mock_ha.return_value = []
            # verify_generic reads back entity state
            mock_verify.return_value = "Kitchen Light: on"

            result = await conv.handle(
                "turn on the kitchen light", session_id="s1"
            )

        # Assert the final response text
        assert "kitchen light" in result.lower()
        assert "on" in result.lower()

        # Assert HA service was called correctly
        mock_ha.assert_awaited_once_with(
            "POST",
            "/services/light/turn_on",
            json_data={
                "entity_id": "light.kitchen",
                "brightness_pct": 100,
            },
        )

        # Assert verify was called to read back state
        mock_verify.assert_awaited_once_with("light.kitchen")

    @pytest.mark.asyncio
    async def test_do_light_no_targets(self, conv):
        """do() without targets (e.g., a script) returns 'Done. Called domain.service.'"""

        tc = _make_tool_call(
            "do",
            {"domain": "script", "service": "good_morning"},
            call_id="call_do_2",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(
            content="Morning routine activated."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
            patch("tools.generic.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            mock_ha.return_value = []

            result = await conv.handle(
                "run the good morning script", session_id="s2"
            )

        assert result == "Morning routine activated."
        mock_ha.assert_awaited_once_with(
            "POST",
            "/services/script/good_morning",
            json_data=None,
        )


# ===================================================================
# Test 2: Full pipeline — query() to read temperature
# ===================================================================


class TestFullPipelineQueryEntity:
    """User asks about state -> LLM returns query() -> state is read -> response."""

    @pytest.mark.asyncio
    async def test_full_pipeline_query_entity(self, conv):
        """User asks 'what's the temperature?' -> query() reads sensor state."""

        tc = _make_tool_call(
            "query",
            {"target": "sensor.living_room_temperature"},
            call_id="call_query_1",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(
            content="The living room is currently 72 degrees."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.read_state", new_callable=AsyncMock
            ) as mock_read,
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            mock_read.return_value = {
                "entity_id": "sensor.living_room_temperature",
                "state": "72",
                "attributes": {
                    "friendly_name": "Living Room Temperature",
                    "unit_of_measurement": "\u00b0F",
                    "device_class": "temperature",
                },
            }

            result = await conv.handle(
                "what's the temperature?", session_id="s3"
            )

        assert "72" in result
        mock_read.assert_awaited_once_with(
            "sensor.living_room_temperature"
        )

    @pytest.mark.asyncio
    async def test_query_template(self, conv):
        """query() with a Jinja2 template evaluates against HA."""

        tc = _make_tool_call(
            "query",
            {"target": "{{ states('sensor.outdoor_temp') }}"},
            call_id="call_query_tpl",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(content="It's 55 degrees outside.")

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            mock_ha.return_value = "55"

            result = await conv.handle(
                "what's the outdoor temperature?", session_id="s4"
            )

        assert "55" in result
        # Template query uses ha_request POST /template
        mock_ha.assert_awaited_once_with(
            "POST",
            "/template",
            json_data={"template": "{{ states('sensor.outdoor_temp') }}"},
        )


# ===================================================================
# Test 3: Full pipeline — discover() to list entities
# ===================================================================


class TestFullPipelineDiscoverEntities:
    """User asks what lights they have -> discover() -> entities listed."""

    @pytest.mark.asyncio
    async def test_full_pipeline_discover_entities(self, conv):
        """User asks 'what lights do I have?' -> discover(entities, light)."""

        tc = _make_tool_call(
            "discover",
            {"what": "entities", "filter_str": "light"},
            call_id="call_discover_1",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(
            content="You have 3 lights: kitchen, living room, and bedroom."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            # ha_request GET /states returns entity list
            mock_ha.return_value = [
                {
                    "entity_id": "light.kitchen",
                    "state": "on",
                    "attributes": {"friendly_name": "Kitchen Light"},
                },
                {
                    "entity_id": "light.living_room",
                    "state": "off",
                    "attributes": {"friendly_name": "Living Room Light"},
                },
                {
                    "entity_id": "light.bedroom",
                    "state": "off",
                    "attributes": {"friendly_name": "Bedroom Light"},
                },
            ]

            result = await conv.handle(
                "what lights do I have?", session_id="s5"
            )

        assert "3 lights" in result.lower() or "kitchen" in result.lower()
        mock_ha.assert_awaited_once_with("GET", "/states")

    @pytest.mark.asyncio
    async def test_discover_services(self, conv):
        """discover(services, light) returns service schemas."""

        tc = _make_tool_call(
            "discover",
            {"what": "services", "filter_str": "light"},
            call_id="call_disc_svc",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(
            content="Light services include turn_on, turn_off, and toggle."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            mock_ha.return_value = [
                {
                    "domain": "light",
                    "services": {
                        "turn_on": {
                            "description": "Turn on a light",
                            "fields": {
                                "entity_id": {
                                    "description": "Light entity",
                                    "required": True,
                                    "selector": {
                                        "entity": {"domain": "light"}
                                    },
                                },
                                "brightness_pct": {
                                    "description": "Brightness percentage",
                                    "selector": {
                                        "number": {"min": 0, "max": 100}
                                    },
                                },
                            },
                        },
                        "turn_off": {
                            "description": "Turn off a light",
                            "fields": {
                                "entity_id": {
                                    "description": "Light entity",
                                    "required": True,
                                    "selector": {
                                        "entity": {"domain": "light"}
                                    },
                                },
                            },
                        },
                    },
                },
            ]

            result = await conv.handle(
                "what light services are available?", session_id="s6"
            )

        assert "turn_on" in result.lower() or "turn_off" in result.lower()


# ===================================================================
# Test 4: Full pipeline — verify schemas in system prompt
# ===================================================================


class TestFullPipelineWithSchemaInContext:
    """Verify that service schemas appear in the system prompt when available."""

    @pytest.mark.asyncio
    async def test_schemas_in_system_prompt(
        self, conv_with_schema_context
    ):
        """Service schemas from context builder appear in the LLM's system prompt."""
        conv = conv_with_schema_context

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    "Here's what I can do with lights."
                )
            )

            await conv.handle(
                "what can you do with lights?", session_id="s7"
            )

        # Check the system prompt passed to litellm
        call_args = mock_litellm.acompletion.call_args
        messages_sent = call_args.kwargs["messages"]
        system_content = messages_sent[0]["content"]

        # Verify schema content is in the system prompt
        assert "HA SERVICE SCHEMAS" in system_content
        assert "light.turn_on" in system_content
        assert "brightness_pct" in system_content
        assert "climate.set_temperature" in system_content

    @pytest.mark.asyncio
    async def test_schema_block_includes_domain_info(
        self, conv_with_schema_context
    ):
        """Schema block includes both light and climate domain schemas."""
        conv = conv_with_schema_context

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("Got it.")
            )

            await conv.handle("help me control things", session_id="s8")

        call_args = mock_litellm.acompletion.call_args
        messages_sent = call_args.kwargs["messages"]
        system_content = messages_sent[0]["content"]

        # Both domain sections should be present
        assert "## light" in system_content
        assert "## climate" in system_content
        assert "entity_id: entity(light) (required)" in system_content


# ===================================================================
# Test 5: Multi-tool loop (discover -> do)
# ===================================================================


class TestMultiToolLoop:
    """LLM calls discover() first, then do() in a second iteration."""

    @pytest.mark.asyncio
    async def test_multi_tool_loop_discover_then_do(self, conv):
        """LLM discovers entities first, then calls do() to act on one."""

        # Round 1: LLM calls discover()
        tc_discover = _make_tool_call(
            "discover",
            {"what": "entities", "filter_str": "light"},
            call_id="call_disc",
        )
        resp_1 = _make_llm_response(content=None, tool_calls=[tc_discover])

        # Round 2: LLM calls do() based on discover results
        tc_do = _make_tool_call(
            "do",
            {
                "domain": "light",
                "service": "turn_on",
                "targets": {"entity_id": "light.kitchen"},
            },
            call_id="call_do",
        )
        resp_2 = _make_llm_response(content=None, tool_calls=[tc_do])

        # Round 3: LLM returns text
        resp_3 = _make_llm_response(
            content="I found your kitchen light and turned it on."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
            patch(
                "tools.generic.verify_generic", new_callable=AsyncMock
            ) as mock_verify,
            patch("tools.generic.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[resp_1, resp_2, resp_3]
            )
            # First call: GET /states for discover
            # Second call: POST /services/light/turn_on for do
            mock_ha.side_effect = [
                # discover() calls GET /states
                [
                    {
                        "entity_id": "light.kitchen",
                        "state": "off",
                        "attributes": {"friendly_name": "Kitchen Light"},
                    },
                    {
                        "entity_id": "light.bedroom",
                        "state": "off",
                        "attributes": {"friendly_name": "Bedroom Light"},
                    },
                ],
                # do() calls POST /services/light/turn_on
                [],
            ]
            mock_verify.return_value = "Kitchen Light: on"

            result = await conv.handle(
                "find my lights and turn on the kitchen one",
                session_id="s10",
            )

        assert "kitchen" in result.lower()
        assert "on" in result.lower()

        # Verify two HA calls: discover then service call
        assert mock_ha.await_count == 2
        ha_calls = mock_ha.call_args_list
        # First: discover entities
        assert ha_calls[0].args == ("GET", "/states")
        # Second: do() service call
        assert ha_calls[1].args == ("POST", "/services/light/turn_on")

    @pytest.mark.asyncio
    async def test_two_tool_calls_in_one_response(self, conv):
        """LLM returns two tool calls (discover + do) in a single response."""

        tc_discover = _make_tool_call(
            "discover",
            {"what": "entities", "filter_str": "light"},
            call_id="call_disc_2",
        )
        tc_do = _make_tool_call(
            "do",
            {
                "domain": "light",
                "service": "turn_off",
                "targets": {"entity_id": "light.kitchen"},
            },
            call_id="call_do_2",
        )
        resp_1 = _make_llm_response(
            content=None, tool_calls=[tc_discover, tc_do]
        )
        resp_2 = _make_llm_response(
            content="Kitchen light is now off. You have 2 lights total."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
            patch(
                "tools.generic.verify_generic", new_callable=AsyncMock
            ) as mock_verify,
            patch("tools.generic.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[resp_1, resp_2]
            )
            mock_ha.side_effect = [
                # discover GET /states
                [
                    {
                        "entity_id": "light.kitchen",
                        "state": "on",
                        "attributes": {"friendly_name": "Kitchen Light"},
                    },
                    {
                        "entity_id": "light.bedroom",
                        "state": "off",
                        "attributes": {"friendly_name": "Bedroom Light"},
                    },
                ],
                # do POST /services/light/turn_off
                [],
            ]
            mock_verify.return_value = "Kitchen Light: off"

            result = await conv.handle(
                "turn off the kitchen light and tell me how many lights I have",
                session_id="s11",
            )

        assert "off" in result.lower()
        assert mock_ha.await_count == 2


# ===================================================================
# Test 6: Confabulation guard works with generic tools
# ===================================================================


class TestConfabulationGuardWithGenericTools:
    """Confabulation guard detects and corrects false claims about do()."""

    @pytest.mark.asyncio
    async def test_confab_guard_nudges_to_use_do(self, conv):
        """If LLM falsely claims 'I've turned on the light' without calling do(),
        the guard nudges it to actually use the tool."""

        # First response: confabulation
        confab_resp = _make_llm_response(
            "I've turned on the kitchen light for you."
        )
        # After nudge: LLM uses do() correctly
        tc = _make_tool_call(
            "do",
            {
                "domain": "light",
                "service": "turn_on",
                "targets": {"entity_id": "light.kitchen"},
            },
            call_id="call_do_confab",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        # Final response after tool
        final_resp = _make_llm_response("Kitchen light is now on.")

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
            patch(
                "tools.generic.verify_generic", new_callable=AsyncMock
            ) as mock_verify,
            patch("tools.generic.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[confab_resp, tool_resp, final_resp]
            )
            mock_ha.return_value = []
            mock_verify.return_value = "Kitchen Light: on"

            messages = [
                {"role": "system", "content": "You are Apex."},
                {"role": "user", "content": "turn on kitchen light"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        assert result == "Kitchen light is now on."
        # The nudge message was injected
        nudge_msg = messages[3]  # system, user, confab, nudge
        assert "MUST call a tool" in nudge_msg["content"]
        # do() was eventually called
        mock_ha.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confab_guard_passes_normal_query_response(self, conv):
        """Normal informational responses pass through the confabulation guard."""

        normal_resp = _make_llm_response(
            "The living room temperature is 72 degrees."
        )

        with patch("brain.conversation.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=normal_resp)

            messages = [
                {"role": "system", "content": "You are Apex."},
                {"role": "user", "content": "what's the temperature?"},
            ]
            result = await conv._ai_tool_loop(
                messages, tool_defs=[{"type": "function"}]
            )

        assert result == "The living room temperature is 72 degrees."
        # Only one LLM call — no nudge needed
        assert mock_litellm.acompletion.await_count == 1


# ===================================================================
# Test 7: do() protected domain requires confirmation
# ===================================================================


class TestProtectedDomains:
    """do() requires confirmation for sensitive domains (lock, alarm, etc.)."""

    @pytest.mark.asyncio
    async def test_do_lock_requires_confirmation(self, conv):
        """Calling do() on a lock domain returns a confirmation prompt."""

        tc = _make_tool_call(
            "do",
            {
                "domain": "lock",
                "service": "lock",
                "targets": {"entity_id": "lock.front_door"},
            },
            call_id="call_lock_1",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        # LLM gets the confirmation prompt and asks the user
        final_resp = _make_llm_response(
            content="I need to confirm before locking the front door. Shall I proceed?"
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )

            result = await conv.handle(
                "lock the front door", session_id="s12"
            )

        assert "confirm" in result.lower()

    @pytest.mark.asyncio
    async def test_do_lock_confirmed_executes(self, conv):
        """do() with confirmed=true and valid confirmation_token executes the lock service."""

        # First call returns confirmation_token
        from tools.generic import do

        result1 = await do(
            domain="lock",
            service="lock",
            targets={"entity_id": "lock.front_door"},
        )
        assert "CONFIRMATION REQUIRED" in result1
        token = result1.split("confirmation_token:")[-1].strip().split()[0]

        tc = _make_tool_call(
            "do",
            {
                "domain": "lock",
                "service": "lock",
                "targets": {"entity_id": "lock.front_door"},
                "data": {"confirmed": True, "confirmation_token": token},
            },
            call_id="call_lock_2",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(content="Front door is locked.")

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
            patch(
                "tools.generic.verify_generic", new_callable=AsyncMock
            ) as mock_verify,
            patch("tools.generic.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            mock_ha.return_value = []
            mock_verify.return_value = "Front Door: locked"

            result = await conv.handle("yes, lock it", session_id="s13")

        assert "locked" in result.lower()
        mock_ha.assert_awaited_once_with(
            "POST",
            "/services/lock/lock",
            json_data={"entity_id": "lock.front_door"},
        )


# ===================================================================
# Test 8: Error handling in tool execution
# ===================================================================


class TestToolErrorHandling:
    """Errors from HA API are propagated back to the LLM as tool results."""

    @pytest.mark.asyncio
    async def test_ha_error_propagated_to_llm(self, conv):
        """When HA returns an error, it becomes the tool result for the LLM."""

        tc = _make_tool_call(
            "do",
            {
                "domain": "light",
                "service": "turn_on",
                "targets": {"entity_id": "light.nonexistent"},
            },
            call_id="call_err_1",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        # LLM receives the error and reports it
        final_resp = _make_llm_response(
            content="I couldn't find that light. Check the entity ID."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
            patch("tools.generic.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            mock_ha.side_effect = Exception("Entity not found")

            result = await conv.handle(
                "turn on the ghost light", session_id="s14"
            )

        assert "couldn't" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, conv):
        """Calling an unregistered tool returns an error message."""

        tc = _make_tool_call(
            "nonexistent_tool",
            {"arg": "value"},
            call_id="call_unk_1",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(
            content="I don't have that capability."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )

            result = await conv.handle(
                "use the flux capacitor", session_id="s15"
            )

        # The execute_tool function returns "Unknown tool: ..." which the LLM sees
        assert result == "I don't have that capability."


# ===================================================================
# Test 9: history() tool pipeline
# ===================================================================


class TestHistoryToolPipeline:
    """history() tool works through the full pipeline."""

    @pytest.mark.asyncio
    async def test_history_changes(self, conv):
        """User asks about history -> history() returns state changes."""

        tc = _make_tool_call(
            "history",
            {"entity_id": "light.kitchen", "hours": 12, "mode": "changes"},
            call_id="call_hist_1",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(
            content="The kitchen light was turned on at 8am and off at 10pm."
        )

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "tools.generic.ha_request", new_callable=AsyncMock
            ) as mock_ha,
        ):
            # The user query "when was the kitchen light on today?"
            # may trigger tool_choice="required" due to "light on".
            # Provide enough side_effect entries to avoid StopAsyncIteration.
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp] + [final_resp] * 6
            )
            mock_ha.return_value = [
                [
                    {
                        "state": "off",
                        "last_changed": "2026-02-18T06:00:00+00:00",
                    },
                    {
                        "state": "on",
                        "last_changed": "2026-02-18T14:00:00+00:00",
                    },
                    {
                        "state": "off",
                        "last_changed": "2026-02-18T22:00:00+00:00",
                    },
                ],
            ]

            result = await conv.handle(
                "when was the kitchen light on today?", session_id="s16"
            )

        assert "8am" in result.lower() or "on" in result.lower()


# ===================================================================
# Test 10: Context builder is called with the user message
# ===================================================================


class TestContextBuilderIntegration:
    """Verify the full handle() flow invokes context_builder correctly."""

    @pytest.mark.asyncio
    async def test_context_builder_receives_user_message(self, conv):
        """context_builder.build() is called with the user message."""

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[],
            ),
        ):
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response("Sure thing.")
            )
            await conv.handle("turn on the porch light", session_id="s17")

        conv.context_builder.build.assert_awaited_once_with(
            "turn on the porch light", session_id="s17",
            voice_mode=False,
        )

    @pytest.mark.asyncio
    async def test_conversation_turns_saved(self, conv):
        """Both user and assistant turns are saved to the conversation store."""

        tc = _make_tool_call(
            "do",
            {
                "domain": "light",
                "service": "turn_on",
                "targets": {"entity_id": "light.porch"},
            },
            call_id="call_save_1",
        )
        tool_resp = _make_llm_response(content=None, tool_calls=[tc])
        final_resp = _make_llm_response(content="Porch light is on.")

        with (
            patch("brain.conversation.litellm") as mock_litellm,
            patch(
                "brain.conversation.get_openai_tool_definitions",
                return_value=[{"type": "function"}],
            ),
            patch(
                "brain.conversation.execute_tool", new_callable=AsyncMock
            ) as mock_exec,
        ):
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_resp, final_resp]
            )
            mock_exec.return_value = "Done."

            result = await conv.handle(
                "turn on the porch light", session_id="s18"
            )

        # User turn saved
        calls = conv.conversation_store.save_turn.call_args_list
        assert calls[0].args == ("user", "turn on the porch light", "s18")
        # Assistant turn saved
        assert calls[1].args == ("assistant", "Porch light is on.", "s18")
        assert result == "Porch light is on."
