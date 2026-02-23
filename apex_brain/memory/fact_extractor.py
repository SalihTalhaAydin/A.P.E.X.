"""
Fact Extractor - Background AI-powered extraction of personal facts from conversations.
Runs after each Apex conversation response (user doesn't wait for it).
Uses a cheap/fast model to keep costs low.
"""

import json
import logging
import math
from datetime import datetime

from memory.knowledge_store import KnowledgeStore

CONFIDENCE_DEFAULT = 0.7
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
Analyze this conversation and extract any NEW facts about the user. \
Only extract genuinely new or updated information. Skip small talk, \
greetings, and routine exchanges.

Categories:
- preference: Things the user likes, dislikes, prefers
- person: People the user mentions (name, relationship, details)
- event: Things that happened or will happen (with dates if mentioned)
- fact: Factual info (passwords, addresses, account numbers, etc.)
- habit: Routines, patterns, regular activities
- reminder: Things the user wants to be reminded about

If a fact has a time limit (e.g. "visiting next week", "sale ends Friday"), \
include "expires": "YYYY-MM-DD" in the JSON object. Only include expires \
for truly temporary facts, not permanent preferences.

CORRECTIONS: Watch for the user correcting or updating a previous fact. \
Look for phrases like "actually", "no, I meant", "I changed my mind", \
"not X, Y instead", "correction:", or any explicit override of earlier info. \
When a correction is detected, set "correction": true in the JSON object. \
Corrections should have high confidence (0.95-1.0) since the user is being \
explicit.

Return ONLY a JSON array. If nothing new to extract, return [].

Example output:
[
  {{"category": "preference", "key": "favorite cuisine", "value": "loves sushi", "confidence": 0.9}},
  {{"category": "person", "key": "Sarah", "value": "friend, birthday March 15", "confidence": 0.8}},
  {{"category": "event", "key": "dentist appointment", "value": "Thursday at 2pm", "confidence": 0.95, "expires": "2026-02-20"}},
  {{"category": "preference", "key": "thermostat preference", "value": "prefers 70 degrees", "confidence": 1.0, "correction": true}}
]

Conversation:
{conversation}

Extract new facts (JSON array only, no other text):"""


def _validate_confidence(raw: object, *, fact_key: str = "?") -> float:
    """Validate and clamp confidence to [0.0, 1.0]. Log warning for invalid values."""
    if raw is None:
        return CONFIDENCE_DEFAULT
    try:
        val = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid confidence value %r for fact %r, using default %.1f",
            raw,
            fact_key,
            CONFIDENCE_DEFAULT,
        )
        return CONFIDENCE_DEFAULT
    if not math.isfinite(val):
        logger.warning(
            "Non-finite confidence %r for fact %r, using default %.1f",
            raw,
            fact_key,
            CONFIDENCE_DEFAULT,
        )
        return CONFIDENCE_DEFAULT
    return max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, val))


class FactExtractor:
    def __init__(
        self, knowledge_store: KnowledgeStore, model: str = "gpt-4o-mini"
    ):
        self.knowledge_store = knowledge_store
        self.model = model

    async def extract_from_conversation(
        self, turns: list[dict], litellm_completion
    ) -> list[dict]:
        """Extract facts from recent conversation turns.

        litellm_completion: the litellm.acompletion function
        (passed to avoid circular imports).
        """
        if not turns:
            return []

        # Format conversation for the extraction prompt
        convo_text = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Apex'}: {t['content']}"
            for t in turns
            if t.get("content")
        )

        if len(convo_text) < 20:
            return []

        raw = ""
        try:
            # Escape braces in conversation text so str.format()
            # does not interpret them as placeholders (Bug #27).
            safe_convo = convo_text.replace("{", "{{").replace(
                "}", "}}"
            )
            response = await litellm_completion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": EXTRACTION_PROMPT.format(
                            conversation=safe_convo
                        ),
                    }
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            if not response.choices:
                return []
            content = response.choices[0].message.content
            if not content:
                return []
            raw = content.strip()

            # Clean up common AI response quirks
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

            if not raw or raw == "[]":
                return []

            facts = json.loads(raw)

            if not isinstance(facts, list):
                return []

            stored_count = 0
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                try:
                    category = fact.get("category", "fact")
                    key = fact.get("key", "")
                    value = fact.get("value", "")
                    confidence = _validate_confidence(
                        fact.get("confidence"),
                        fact_key=key or "?",
                    )
                    is_correction = fact.get("correction", False)

                    if not (key and value):
                        continue

                    if is_correction:
                        await self.knowledge_store.correct_fact(
                            category=category,
                            key=key,
                            new_value=value,
                            confidence=confidence,
                        )
                        logger.debug(
                            "Corrected fact: %s = %s (confidence=%.2f)",
                            key,
                            value,
                            confidence,
                        )
                    else:
                        expires = fact.get("expires")
                        # Validate expires format
                        if expires:
                            try:
                                datetime.fromisoformat(expires)
                            except (ValueError, TypeError):
                                logger.warning(
                                    "Invalid expires date '%s', ignoring",
                                    expires,
                                )
                                expires = None
                        await self.knowledge_store.store_fact(
                            category=category,
                            key=key,
                            value=value,
                            confidence=confidence,
                            source="auto",
                            expires_at=expires,
                        )
                        logger.debug(
                            "Extracted fact: %s = %s (confidence=%.2f)",
                            key,
                            value,
                            confidence,
                        )
                    stored_count += 1
                except Exception as e:
                    logger.warning(
                        "Failed to store fact '%s': %s",
                        fact.get("key", "?"),
                        e,
                    )
                    continue

            logger.info(
                "Extracted %d facts from conversation",
                stored_count,
            )
            return facts

        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse fact extraction response as JSON: %s",
                raw,
            )
            return []
        except Exception as e:
            logger.error(
                "Fact extraction error: %s",
                e,
                exc_info=True,
            )
            return []
