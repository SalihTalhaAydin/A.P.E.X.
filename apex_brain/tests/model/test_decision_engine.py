"""Tests for the Decision Engine - event significance filter."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain.decision_engine import DecisionEngine, EventDecision


def _freeze_hour(hour: int):
    """Context manager to freeze datetime.now().hour for deterministic scoring."""
    mock_dt = MagicMock()
    mock_now = MagicMock()
    mock_now.hour = hour
    mock_dt.now.return_value = mock_now
    return patch("brain.decision_engine.datetime", mock_dt)


@pytest.fixture(autouse=True)
def freeze_daytime_for_scoring(request):
    """Freeze time to 2 PM for scoring tests — avoids wall-clock flakiness (Bug 48)."""
    cls_name = getattr(request.cls, "__name__", "")
    if cls_name in ("TestSignificanceScoring", "TestEvaluate"):
        with _freeze_hour(14):
            yield
    else:
        yield


class FakeEvent:
    """Minimal event for testing (matches WebhookEvent interface)."""

    def __init__(
        self, entity_id: str, new_state: str = "",
        old_state: str = "", event_type: str = "state_changed",
        attributes: dict | None = None,
    ):
        self.entity_id = entity_id
        self.new_state = new_state
        self.old_state = old_state
        self.event_type = event_type
        self.attributes = attributes or {}


# ------------------------------------------------------------------ #
# Hard filter tests
# ------------------------------------------------------------------ #
class TestHardFilter:
    def setup_method(self):
        self.engine = DecisionEngine()

    def test_same_state_dropped(self):
        event = FakeEvent("light.kitchen", new_state="on", old_state="on")
        assert self.engine._hard_filter(event) == "no state change"

    def test_unavailable_new_dropped(self):
        event = FakeEvent("light.kitchen", new_state="unavailable", old_state="on")
        assert self.engine._hard_filter(event) == "device went unavailable"

    def test_recovery_from_unavailable_dropped(self):
        event = FakeEvent("light.kitchen", new_state="on", old_state="unavailable")
        assert self.engine._hard_filter(event) == "recovery from unavailable"

    def test_sensor_noise_dropped(self):
        event = FakeEvent("sensor.temperature", new_state="72.1", old_state="72.0")
        result = self.engine._hard_filter(event)
        assert "sensor noise" in result

    def test_sensor_significant_change_passes(self):
        event = FakeEvent("sensor.temperature", new_state="75.0", old_state="72.0")
        assert self.engine._hard_filter(event) == ""

    def test_update_entity_dropped(self):
        event = FakeEvent("update.core", new_state="2025.1", old_state="2025.0")
        assert self.engine._hard_filter(event) == "update entity"

    def test_weather_dropped(self):
        event = FakeEvent("weather.home", new_state="cloudy", old_state="sunny")
        assert self.engine._hard_filter(event) == "weather update"

    def test_connectivity_sensor_dropped(self):
        event = FakeEvent("binary_sensor.router_connectivity", new_state="on", old_state="off")
        assert self.engine._hard_filter(event) == "connectivity sensor"

    def test_ping_sensor_dropped(self):
        event = FakeEvent("binary_sensor.server_ping", new_state="on", old_state="off")
        assert self.engine._hard_filter(event) == "connectivity sensor"

    def test_real_state_change_passes(self):
        event = FakeEvent("light.kitchen", new_state="on", old_state="off")
        assert self.engine._hard_filter(event) == ""

    def test_door_event_passes(self):
        event = FakeEvent("binary_sensor.front_door", new_state="on", old_state="off")
        assert self.engine._hard_filter(event) == ""

    def test_empty_old_state_passes(self):
        event = FakeEvent("light.kitchen", new_state="on", old_state="")
        assert self.engine._hard_filter(event) == ""

    def test_custom_noise_threshold(self):
        engine = DecisionEngine(sensor_noise_threshold=1.0)
        event = FakeEvent("sensor.temp", new_state="72.8", old_state="72.0")
        assert "sensor noise" in engine._hard_filter(event)

    def test_non_numeric_sensor_passes(self):
        event = FakeEvent("sensor.status", new_state="active", old_state="idle")
        assert self.engine._hard_filter(event) == ""


# ------------------------------------------------------------------ #
# Significance scoring tests
# ------------------------------------------------------------------ #
class TestSignificanceScoring:
    def setup_method(self):
        self.engine = DecisionEngine()

    def test_lock_entity_critical(self):
        event = FakeEvent("lock.front_door", new_state="unlocked", old_state="locked")
        score, priority = self.engine._score_significance(event)
        assert score == 0.9
        assert priority == "critical"

    def test_alarm_entity_critical(self):
        event = FakeEvent("alarm_control_panel.home", new_state="disarmed", old_state="armed_away")
        score, priority = self.engine._score_significance(event)
        assert score == 0.9
        assert priority == "critical"

    def test_door_sensor_medium_to_high(self):
        event = FakeEvent("binary_sensor.front_door", new_state="on", old_state="off")
        score, priority = self.engine._score_significance(event)
        assert score >= 0.7
        assert priority in ("medium", "high")

    def test_person_entity_high(self):
        event = FakeEvent("person.salih", new_state="home", old_state="not_home")
        score, priority = self.engine._score_significance(event)
        assert score == 0.85
        assert priority == "high"

    def test_light_entity_low(self):
        event = FakeEvent("light.kitchen", new_state="on", old_state="off")
        score, priority = self.engine._score_significance(event)
        assert score == 0.25
        assert priority == "low"

    def test_switch_entity_low(self):
        event = FakeEvent("switch.fan", new_state="on", old_state="off")
        score, priority = self.engine._score_significance(event)
        assert score == 0.25
        assert priority == "low"

    def test_climate_entity_medium(self):
        event = FakeEvent("climate.thermostat", new_state="heat", old_state="off")
        score, priority = self.engine._score_significance(event)
        assert score == 0.35
        assert priority == "medium"

    def test_unknown_entity_base_score(self):
        event = FakeEvent("input_boolean.test", new_state="on", old_state="off")
        score, priority = self.engine._score_significance(event)
        assert score == 0.3
        assert priority == "medium"

    def test_motion_sensor_day(self):
        """Motion sensors get 0.4/medium during daytime (frozen at 14:00)."""
        event = FakeEvent("binary_sensor.hallway_motion", new_state="on", old_state="off")
        score, priority = self.engine._score_significance(event)
        assert score == 0.4
        assert priority == "medium"

    def test_door_sensor_night_score_critical(self):
        """Door sensors get 0.95/high at night (Bug 48: deterministic with frozen time)."""
        with _freeze_hour(23):
            event = FakeEvent(
                "binary_sensor.front_door", new_state="on", old_state="off"
            )
            score, priority = self.engine._score_significance(event)
        assert score == 0.95
        assert priority == "high"

    def test_motion_sensor_night_high(self):
        """Motion sensors get 0.8/high at night (Bug 48: deterministic with frozen time)."""
        with _freeze_hour(23):
            event = FakeEvent(
                "binary_sensor.hallway_motion", new_state="on", old_state="off"
            )
            score, priority = self.engine._score_significance(event)
        assert score == 0.8
        assert priority == "high"


# ------------------------------------------------------------------ #
# Cooldown tests
# ------------------------------------------------------------------ #
class TestCooldown:
    def test_first_event_passes(self):
        engine = DecisionEngine(cooldown_seconds=60)
        assert engine._check_cooldown("test:entity") is True

    def test_second_event_blocked(self):
        engine = DecisionEngine(cooldown_seconds=60)
        # check returns True (cooldown not active)
        assert engine._check_cooldown("test:entity") is True
        # set the cooldown
        engine._cooldowns["test:entity"] = time.time()
        # now it should be blocked
        assert engine._check_cooldown("test:entity") is False

    def test_different_keys_independent(self):
        engine = DecisionEngine(cooldown_seconds=60)
        engine._cooldowns["test:entity_a"] = time.time()
        assert engine._check_cooldown("test:entity_b") is True

    def test_cooldown_expires(self):
        engine = DecisionEngine(cooldown_seconds=1)
        engine._cooldowns["test:entity"] = time.time()
        # Manually expire the cooldown
        engine._cooldowns["test:entity"] = time.time() - 2
        assert engine._check_cooldown("test:entity") is True


# ------------------------------------------------------------------ #
# Full evaluate() integration tests
# ------------------------------------------------------------------ #
class TestEvaluate:
    @pytest.mark.asyncio
    async def test_noise_event_dropped(self):
        engine = DecisionEngine()
        event = FakeEvent("sensor.temp", new_state="72.1", old_state="72.0")
        decision = await engine.evaluate(event)
        assert not decision.should_process
        assert decision.significance_score == 0.0

    @pytest.mark.asyncio
    async def test_light_below_threshold(self):
        engine = DecisionEngine(significance_threshold=0.3)
        event = FakeEvent("light.kitchen", new_state="on", old_state="off")
        decision = await engine.evaluate(event)
        assert not decision.should_process
        assert decision.significance_score == 0.25

    @pytest.mark.asyncio
    async def test_door_above_threshold(self):
        engine = DecisionEngine(significance_threshold=0.3)
        event = FakeEvent("binary_sensor.front_door", new_state="on", old_state="off")
        decision = await engine.evaluate(event)
        assert decision.should_process
        assert decision.significance_score >= 0.7

    @pytest.mark.asyncio
    async def test_person_above_threshold(self):
        engine = DecisionEngine()
        event = FakeEvent("person.salih", new_state="home", old_state="not_home")
        decision = await engine.evaluate(event)
        assert decision.should_process
        assert decision.significance_score == 0.85

    @pytest.mark.asyncio
    async def test_lock_above_threshold(self):
        engine = DecisionEngine()
        event = FakeEvent("lock.front", new_state="unlocked", old_state="locked")
        decision = await engine.evaluate(event)
        assert decision.should_process
        assert decision.priority == "critical"

    @pytest.mark.asyncio
    async def test_cooldown_blocks_repeated(self):
        engine = DecisionEngine(cooldown_seconds=60)
        event = FakeEvent("binary_sensor.front_door", new_state="on", old_state="off")
        d1 = await engine.evaluate(event)
        d2 = await engine.evaluate(event)
        assert d1.should_process
        assert not d2.should_process

    @pytest.mark.asyncio
    async def test_context_enrichment_boosts_score(self):
        mock_ks = AsyncMock()
        mock_ks.search_keyword = AsyncMock(return_value=[{"key": "thermostat", "value": "likes 72"}])
        engine = DecisionEngine(
            significance_threshold=0.5,
            knowledge_store=mock_ks,
        )
        event = FakeEvent("climate.thermostat", new_state="heat", old_state="off")
        decision = await engine.evaluate(event)
        # Base score 0.35 + 0.2 boost = 0.55, above 0.5 threshold
        assert decision.should_process
        assert decision.significance_score == 0.55

    @pytest.mark.asyncio
    async def test_context_enrichment_no_facts(self):
        mock_ks = AsyncMock()
        mock_ks.search_keyword = AsyncMock(return_value=[])
        engine = DecisionEngine(
            significance_threshold=0.5,
            knowledge_store=mock_ks,
        )
        event = FakeEvent("climate.thermostat", new_state="heat", old_state="off")
        decision = await engine.evaluate(event)
        # Base score 0.35, no boost, below 0.5
        assert not decision.should_process

    @pytest.mark.asyncio
    async def test_context_enrichment_error_graceful(self):
        mock_ks = AsyncMock()
        mock_ks.search_keyword = AsyncMock(side_effect=Exception("db error"))
        engine = DecisionEngine(knowledge_store=mock_ks)
        event = FakeEvent("climate.thermostat", new_state="heat", old_state="off")
        decision = await engine.evaluate(event)
        # Should not crash, just use base score
        assert decision.significance_score == 0.35


class TestEventDecision:
    def test_dataclass_fields(self):
        d = EventDecision(
            should_process=True,
            significance_score=0.8,
            reason="test",
            priority="high",
        )
        assert d.should_process is True
        assert d.significance_score == 0.8
        assert d.reason == "test"
        assert d.priority == "high"
