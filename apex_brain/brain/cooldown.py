"""Shared cooldown tracker for event processing."""

from __future__ import annotations

import time


class CooldownTracker:
    """Track per-key cooldowns with periodic cleanup."""

    def __init__(self, cooldown_seconds: int = 60):
        self._cooldown_seconds = cooldown_seconds
        self._cooldowns: dict[str, float] = {}

    def check(self, key: str) -> bool:
        """True if cooldown elapsed (ok to act).

        Does NOT set cooldown.
        """
        now = time.time()
        last = self._cooldowns.get(key, 0)
        return now - last >= self._cooldown_seconds

    def set(self, key: str) -> None:
        """Record that an action was taken."""
        now = time.time()
        self._cooldowns[key] = now
        # Periodic cleanup
        max_age = self._cooldown_seconds * 2
        stale = [
            k for k, ts in self._cooldowns.items() if now - ts > max_age
        ]
        for k in stale:
            del self._cooldowns[k]

    def check_and_set(self, key: str) -> bool:
        """Check cooldown and set if elapsed.

        Returns True if ok to act.
        """
        if not self.check(key):
            return False
        self.set(key)
        return True
