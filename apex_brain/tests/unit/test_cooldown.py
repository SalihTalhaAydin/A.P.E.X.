"""
Tests for CooldownTracker — per-key cooldown with periodic cleanup (Bug 13 / P3-GAP-4).
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from brain.cooldown import CooldownTracker


@pytest.fixture
def tracker():
    """Create a CooldownTracker with 1-second cooldown for fast tests."""
    return CooldownTracker(cooldown_seconds=1)


class TestCheck:
    """Tests for check() — returns True if cooldown elapsed, does NOT set cooldown."""

    def test_first_check_passes(self, tracker):
        """First check for any key returns True (no cooldown set yet)."""
        assert tracker.check("light.kitchen") is True
        assert tracker.check("light.bedroom") is True

    def test_check_after_set_fails_immediately(self, tracker):
        """Check immediately after set returns False."""
        tracker.set("light.kitchen")
        assert tracker.check("light.kitchen") is False

    def test_check_after_cooldown_elapsed_passes(self):
        """Check after cooldown seconds returns True."""
        with patch("time.time", return_value=100.0):
            t = CooldownTracker(cooldown_seconds=1)
            t.set("x")
        assert t._cooldowns["x"] == 100.0
        with patch("time.time", return_value=101.5):  # 1.5 seconds later
            assert t.check("x") is True

    def test_check_does_not_set_cooldown(self, tracker):
        """check() alone does not record the key — repeated checks keep passing."""
        assert tracker.check("orphan") is True
        assert tracker.check("orphan") is True
        assert "orphan" not in tracker._cooldowns


class TestSet:
    """Tests for set() — records that an action was taken."""

    def test_set_records_key(self, tracker):
        """set() stores the key with current timestamp."""
        before = time.time()
        tracker.set("light.living")
        after = time.time()
        assert "light.living" in tracker._cooldowns
        assert before <= tracker._cooldowns["light.living"] <= after + 0.1

    def test_set_overwrites_previous(self, tracker):
        """set() overwrites previous timestamp for same key."""
        tracker.set("light.kitchen")
        ts1 = tracker._cooldowns["light.kitchen"]
        time.sleep(0.05)
        tracker.set("light.kitchen")
        ts2 = tracker._cooldowns["light.kitchen"]
        assert ts2 >= ts1


class TestCheckAndSet:
    """Tests for check_and_set() — check and set atomically."""

    def test_first_call_returns_true(self, tracker):
        """First check_and_set returns True and sets cooldown."""
        assert tracker.check_and_set("light.kitchen") is True
        assert "light.kitchen" in tracker._cooldowns

    def test_second_call_immediately_returns_false(self, tracker):
        """Second check_and_set before cooldown elapses returns False."""
        assert tracker.check_and_set("light.kitchen") is True
        assert tracker.check_and_set("light.kitchen") is False

    def test_after_cooldown_returns_true_again(self):
        """After cooldown elapses, check_and_set returns True again."""
        with patch("time.time", side_effect=[100.0, 100.0, 100.0, 101.5, 101.5]):
            t = CooldownTracker(cooldown_seconds=1)
            assert t.check_and_set("x") is True   # sets at t=100
            assert t.check_and_set("x") is False  # still at t=100
            assert t.check_and_set("x") is True   # 1.5s later


class TestCleanup:
    """Tests for periodic cleanup of stale cooldown entries."""

    def test_cleanup_removes_stale_entries(self):
        """set() cleans up entries older than 2x cooldown."""
        with patch("time.time", return_value=100.0):
            t = CooldownTracker(cooldown_seconds=10)
            t._cooldowns["old"] = 74.0   # 26 seconds ago (100 - 74 = 26 > 20)
            t._cooldowns["recent"] = 96.0  # 4 seconds ago (100 - 96 = 4 < 20)
        with patch("time.time", return_value=100.0):
            t.set("new")  # Triggers cleanup; max_age = 20
        assert "old" not in t._cooldowns
        assert "recent" in t._cooldowns
        assert "new" in t._cooldowns
