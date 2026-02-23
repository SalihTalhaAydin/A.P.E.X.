"""
Curator - Self-curation logic for Apex's managed artifacts.

Provides audit functions that the scheduler calls periodically to
keep facts, automations, and entities clean and consolidated.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class Curator:
    """Self-curation logic for Apex's managed artifacts."""

    def __init__(self, conversation, knowledge_store):
        self._conversation = conversation
        self._knowledge_store = knowledge_store

    # ------------------------------------------------------------------ #
    # Fact maintenance (runs directly, no LLM needed)
    # ------------------------------------------------------------------ #

    async def audit_facts(self) -> str:
        """Daily: decay confidence, cleanup expired, prune very low confidence,
        find contradictions. Returns a summary string."""
        report_parts = []

        # 1. Run confidence decay
        try:
            decayed = await self._knowledge_store.decay_confidence()
            if decayed:
                report_parts.append(f"Decayed {decayed} stale facts")
        except Exception as e:
            logger.error("Fact decay failed: %s", e)

        # 2. Clean expired
        try:
            expired = await self._knowledge_store.cleanup_expired()
            if expired:
                report_parts.append(f"Removed {expired} expired facts")
        except Exception as e:
            logger.error("Expired cleanup failed: %s", e)

        # 3. Prune very low confidence facts
        try:
            from brain.config import settings

            threshold = settings.fact_min_confidence_prune
            low_conf = (
                await self._knowledge_store.get_low_confidence_facts(
                    threshold, limit=50
                )
            )
            if low_conf:
                pruned = 0
                for fact in low_conf:
                    fact_id = fact.get("id")
                    if fact_id is None:
                        logger.warning(
                            "Fact missing 'id', skipping: %s", fact
                        )
                        continue
                    try:
                        deleted = await self._knowledge_store.delete_fact_by_id(
                            fact_id
                        )
                        if deleted:
                            pruned += 1
                    except Exception as e:
                        logger.warning(
                            "Failed to prune fact %s: %s", fact_id, e
                        )
                if pruned:
                    report_parts.append(
                        f"Pruned {pruned} very low confidence facts"
                    )
        except Exception as e:
            logger.error("Low confidence prune failed: %s", e)

        # 4. Find and resolve contradictions
        try:
            contradictions = (
                await self._knowledge_store.get_contradictory_facts()
            )
            if contradictions:
                resolved = await self._resolve_contradictions(
                    contradictions
                )
                report_parts.append(
                    f"Resolved {resolved} contradictory fact pairs"
                )
        except Exception as e:
            logger.error("Contradiction resolution failed: %s", e)

        result = (
            "; ".join(report_parts) if report_parts else "Facts healthy"
        )
        logger.info("Fact audit: %s", result)
        return result

    async def _resolve_contradictions(
        self, contradictions: list[tuple[dict, dict]]
    ) -> int:
        """Resolve contradictory facts: higher confidence wins, then recency."""
        resolved = 0
        for fact_a, fact_b in contradictions:
            try:
                id_a = fact_a.get("id")
                id_b = fact_b.get("id")
                if id_a is None or id_b is None:
                    logger.warning(
                        "Contradiction fact missing 'id', skipping: %s vs %s",
                        fact_a,
                        fact_b,
                    )
                    continue
                # Higher confidence wins
                if fact_a.get("confidence", 0) > fact_b.get(
                    "confidence", 0
                ):
                    await self._knowledge_store.delete_fact_by_id(id_b)
                elif fact_b.get("confidence", 0) > fact_a.get(
                    "confidence", 0
                ):
                    await self._knowledge_store.delete_fact_by_id(id_a)
                else:
                    # Same confidence: keep more recent (parse timestamps)
                    ts_a = fact_a.get("updated_at") or ""
                    ts_b = fact_b.get("updated_at") or ""
                    try:
                        keep_a = datetime.fromisoformat(
                            ts_a
                        ) >= datetime.fromisoformat(ts_b)
                    except (ValueError, TypeError):
                        # Cannot parse timestamps; string comparison is wrong for
                        # non-ISO or mixed formats. Conservatively skip resolution.
                        continue
                    if keep_a:
                        await self._knowledge_store.delete_fact_by_id(id_b)
                    else:
                        await self._knowledge_store.delete_fact_by_id(id_a)
                resolved += 1
            except Exception as e:
                logger.error("Failed to resolve contradiction: %s", e)
        return resolved

    # ------------------------------------------------------------------ #
    # AI-driven audits (send message to conversation orchestrator)
    # ------------------------------------------------------------------ #

    async def audit_automations(self) -> None:
        """Weekly: ask the AI to audit automations for unused, conflicts, merges."""
        msg = (
            "[SYSTEM AUDIT] Please audit the Home Assistant automations. "
            "1. List all automations using list_automations(). "
            "2. For each automation, check when it last triggered using history(). "
            "3. Flag any that haven't triggered in 90+ days as candidates for disabling. "
            "4. Look for automations with similar triggers that could be merged. "
            "5. Report your findings concisely. If everything looks good, just say so."
        )
        try:
            await self._conversation.handle(msg, session_id="apex_curator")
        except Exception as e:
            logger.error("Automation audit failed: %s", e)

    async def audit_entities(self) -> None:
        """Daily: ask the AI to check for stale/unavailable entities."""
        msg = (
            "[SYSTEM AUDIT] Quick entity health check: "
            "1. Use discover(what='entities') and look for entities stuck in 'unavailable' state. "
            "2. Note any that seem problematic. "
            "3. Only report if you find issues — if everything looks healthy, just log it briefly."
        )
        try:
            await self._conversation.handle(msg, session_id="apex_curator")
        except Exception as e:
            logger.error("Entity audit failed: %s", e)

    async def consolidate_facts(self) -> str:
        """Find and resolve contradictory facts (standalone call)."""
        try:
            contradictions = (
                await self._knowledge_store.get_contradictory_facts()
            )
            if not contradictions:
                return "No contradictions found"
            resolved = await self._resolve_contradictions(contradictions)
            return f"Resolved {resolved} contradictory fact pairs"
        except Exception as e:
            logger.error("Fact consolidation failed: %s", e)
            return f"Consolidation error: {e}"
