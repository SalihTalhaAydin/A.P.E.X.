"""
Decision Engine - Rule-based event significance filter.

Sits between raw HA events and the conversation orchestrator.
Pure rule-based (zero LLM cost) — drops noise, scores significance,
and only lets meaningful events through to the AI.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from brain.config import settings

logger = logging.getLogger(__name__)

# Critical domains: unavailability should NOT be dropped
_CRITICAL_DOMAINS = (
    "lock",
    "alarm_control_panel",
    "camera",
    "cover",
)


@dataclass
class EventDecision:
    """Result of evaluating an event's significance."""

    should_process: bool
    significance_score: float  # 0.0 to 1.0
    reason: str
    priority: str  # "low", "medium", "high", "critical"


class DecisionEngine:
    """Rule-based event significance filter.

    First pass is pure rule-based (zero LLM cost).
    Only events scoring above threshold get sent to the LLM.
    """

    def __init__(
        self,
        cooldown_seconds: int = 60,
        significance_threshold: float = 0.3,
        knowledge_store=None,
        sensor_noise_threshold: float = 0.5,
    ):
        self._cooldown_seconds = cooldown_seconds
        self._significance_threshold = significance_threshold
        self._knowledge_store = knowledge_store
        self._sensor_noise_threshold = sensor_noise_threshold
        self._cooldowns: dict[str, float] = {}
        self._cooldown_lock = asyncio.Lock()

    async def evaluate(self, event) -> EventDecision:
        """Evaluate an event's significance. Returns a decision."""
        # Cleanup expired cooldowns on every evaluation (even when we early-exit)
        self._cleanup_cooldowns(time.time())
        # Layer 1: Hard drop rules (zero cost)
        drop_reason = self._hard_filter(event)
        if drop_reason:
            return EventDecision(False, 0.0, drop_reason, "low")

        # Layer 2: Fast cooldown check (early exit; atomic acquire happens below)
        cooldown_key = f"{event.event_type}:{event.entity_id}"
        if not self._check_cooldown(cooldown_key):
            return EventDecision(False, 0.0, "cooldown active", "low")

        # Layer 3: Significance scoring (rule-based)
        score, priority = self._score_significance(event)

        # Layer 4: Context enrichment
        if self._knowledge_store and score >= 0.2:
            score = await self._enrich_with_context(event, score)

        should_process = score >= self._significance_threshold
        if should_process:
            # Atomic check-and-set: first caller wins, concurrent callers get False
            if not await self._try_acquire_cooldown(cooldown_key):
                should_process = False
                reason = "cooldown (concurrent)"
            else:
                reason = "passed filters"
        else:
            reason = "below threshold"
        return EventDecision(should_process, score, reason, priority)

    def _hard_filter(self, event) -> str:
        """Drop events that are never interesting. Zero cost."""
        entity = event.entity_id
        old = (event.old_state or "").strip().lower()
        new = (event.new_state or "").strip().lower()

        # Same state (no real change)
        if old and new and old == new:
            return "no state change"

        # Unavailable bounces — allow critical domains
        domain = entity.split(".")[0] if "." in entity else ""
        if new == "unavailable":
            if domain not in _CRITICAL_DOMAINS:
                return "device went unavailable"
        # Recovery from unavailable: always process (users need to know when
        # devices come back online; BUG-88)
        # Removed drop for "recovery from unavailable"

        # Sensor noise: numeric sensors with tiny deltas
        if entity.startswith("sensor."):
            try:
                delta = abs(float(new) - float(old))
                if delta < self._sensor_noise_threshold:
                    return f"sensor noise (delta={delta:.2f})"
            except (ValueError, TypeError):
                pass

        # Update entities (just version strings)
        if entity.startswith("update."):
            return "update entity"

        # Weather forecast updates (too frequent)
        if entity.startswith("weather."):
            return "weather update"

        # Binary sensors that chatter (connectivity, ping)
        if "connectivity" in entity or "ping" in entity:
            return "connectivity sensor"

        return ""

    def _check_cooldown(self, key: str) -> bool:
        """True if cooldown elapsed (ok to proceed to scoring). Fast path only."""
        now = time.time()
        last = self._cooldowns.get(key, 0)
        if now - last < self._cooldown_seconds:
            return False
        self._cleanup_cooldowns(now)
        return True

    async def _try_acquire_cooldown(self, key: str) -> bool:
        """Atomically check and set cooldown. First caller wins (True); concurrent callers get False."""
        async with self._cooldown_lock:
            now = time.time()
            last = self._cooldowns.get(key, 0)
            if now - last < self._cooldown_seconds:
                return False
            self._cooldowns[key] = now
            self._cleanup_cooldowns(now)
            return True

    def _cleanup_cooldowns(self, now: float) -> None:
        """Remove stale cooldown entries."""
        max_age = self._cooldown_seconds * 2
        stale = [
            k for k, ts in self._cooldowns.items() if now - ts > max_age
        ]
        for k in stale:
            del self._cooldowns[k]

    def _score_significance(self, event) -> tuple[float, str]:
        """Score event significance 0.0-1.0 using rules."""
        entity = event.entity_id
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(settings.timezone)
        except Exception:
            tz = timezone.utc
            logger.debug(
                "Could not load timezone '%s', using UTC",
                settings.timezone,
            )
        hour = datetime.now(tz).hour
        score = 0.3  # base score for passing hard filter

        # Security events: always high (cover = garage doors, security-relevant)
        if any(
            d in entity
            for d in (
                "lock.",
                "alarm_control_panel.",
                "camera.",
                "cover.",
            )
        ):
            return 0.9, "critical"

        # Door/window sensors
        if any(kw in entity for kw in ("door", "window", "contact")):
            score = 0.7
            if hour >= 22 or hour < 6:
                score = 0.95  # late night = critical
            return (
                score,
                "high" if score > 0.8 else "medium",
            )

        # Motion sensors
        if "motion" in entity or "occupancy" in entity:
            if hour >= 22 or hour < 6:
                return 0.8, "high"
            return 0.4, "medium"

        # Person entities (presence changes)
        if entity.startswith("person."):
            return 0.85, "high"

        # Device state changes (lights, switches, media)
        if entity.startswith(("light.", "switch.", "media_player.")):
            return 0.35, "low"

        # Climate changes
        if entity.startswith("climate."):
            return 0.35, "medium"

        return score, "medium"

    async def _enrich_with_context(
        self, event, base_score: float
    ) -> float:
        """Boost score if entity is in user's knowledge."""
        try:
            entity_name = event.entity_id.split(".")[-1]
            facts = await self._knowledge_store.search_keyword(
                entity_name, limit=3
            )
            if facts:
                return min(base_score + 0.2, 1.0)
        except Exception as e:
            logger.debug("Context enrichment failed: %s", e)
        return base_score
