"""Tests for the dynamic system prompt builder."""

import datetime

from brain.system_prompt import (
    _build_proactive_hints,
    _build_time_context,
    build_system_prompt,
)


def test_time_context_morning():
    """Morning is 5-12."""
    now = datetime.datetime(2026, 2, 17, 8, 30)
    ctx = _build_time_context(now)
    assert ctx["period"] == "morning"
    assert ctx["season"] == "winter"


def test_time_context_afternoon():
    """Afternoon is 12-17."""
    now = datetime.datetime(2026, 6, 15, 14, 0)
    ctx = _build_time_context(now)
    assert ctx["period"] == "afternoon"
    assert ctx["season"] == "summer"


def test_time_context_evening():
    """Evening is 17-21."""
    now = datetime.datetime(2026, 9, 21, 19, 0)
    ctx = _build_time_context(now)
    assert ctx["period"] == "evening"
    assert ctx["season"] == "fall"


def test_time_context_night():
    """Night is 21-5."""
    now = datetime.datetime(2026, 3, 10, 23, 0)
    ctx = _build_time_context(now)
    assert ctx["period"] == "night"
    assert ctx["season"] == "spring"


def test_season_winter():
    for m in (12, 1, 2):
        now = datetime.datetime(2026, m, 15, 12, 0)
        assert _build_time_context(now)["season"] == "winter"


def test_season_spring():
    for m in (3, 4, 5):
        now = datetime.datetime(2026, m, 15, 12, 0)
        assert _build_time_context(now)["season"] == "spring"


def test_season_summer():
    for m in (6, 7, 8):
        now = datetime.datetime(2026, m, 15, 12, 0)
        assert _build_time_context(now)["season"] == "summer"


def test_season_fall():
    for m in (9, 10, 11):
        now = datetime.datetime(2026, m, 15, 12, 0)
        assert _build_time_context(now)["season"] == "fall"


def test_proactive_hints_morning():
    """Morning hints mention weather/schedule."""
    ctx = {"period": "morning", "season": "winter"}
    hints = _build_proactive_hints(time_ctx=ctx)
    assert "weather" in hints.lower() or "schedule" in hints.lower()


def test_proactive_hints_evening():
    """Evening hints mention winding down."""
    ctx = {"period": "evening", "season": "summer"}
    hints = _build_proactive_hints(time_ctx=ctx)
    assert "evening" in hints.lower() or "winding" in hints.lower()


def test_proactive_hints_calendar():
    """Calendar triggers a calendar hint."""
    hints = _build_proactive_hints(
        calendar="Meeting at 3pm"
    )
    assert "calendar" in hints.lower()


def test_proactive_hints_empty():
    """No hints when no context is provided."""
    hints = _build_proactive_hints()
    assert hints == ""


def test_build_prompt_includes_presence():
    """Presence summary appears in prompt."""
    prompt = build_system_prompt(
        presence_summary="Salih: home, Alena: away"
    )
    assert "WHO'S HOME" in prompt
    assert "Salih: home" in prompt


def test_build_prompt_includes_time_context():
    """Time context replaces raw datetime."""
    ctx = {
        "period": "morning",
        "season": "winter",
        "formatted": "Monday, February 17, 2026 at 08:30 AM",
    }
    prompt = build_system_prompt(time_context=ctx)
    assert "TIME & CONTEXT" in prompt
    assert "Morning" in prompt
    assert "winter" in prompt


def test_build_prompt_includes_calendar():
    """Calendar summary appears in prompt."""
    prompt = build_system_prompt(
        calendar_summary="9:00 AM: Team standup"
    )
    assert "TODAY'S SCHEDULE" in prompt
    assert "Team standup" in prompt


def test_build_prompt_includes_routines_section():
    """Routines section is in the template."""
    prompt = build_system_prompt()
    assert "ROUTINES" in prompt
    assert "define_routine" in prompt


def test_build_prompt_includes_automation_section():
    """Automation tools are in the template."""
    prompt = build_system_prompt()
    assert "list_automations" in prompt
    assert "activate_scene" in prompt
