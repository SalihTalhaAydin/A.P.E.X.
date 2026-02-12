"""
Fact Extractor - Background AI-powered extraction of personal facts from conversations.
Runs after each Apex conversation response (user doesn't wait for it).
Uses a cheap/fast model to keep costs low.
"""

import json
import traceback

from memory.knowledge_store import KnowledgeStore

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

Return ONLY a JSON array. If nothing new to extract, return [].

Example output:
[
  {{"category": "preference", "key": "favorite cuisine", "value": "loves sushi", "confidence": 0.9}},
  {{"category": "person", "key": "Sarah", "value": "friend, birthday March 15", "confidence": 0.8}}
]

Conversation:
{conversation}

Extract new facts (JSON array only, no other text):"""


class FactExtractor:
    def __init__(
        self, knowledge_store: KnowledgeStore, model: str = "gpt-4o-mini"
    ):
        self.knowledge_store = knowledge_store
        self.model = model

    async def extract_from_conversation(
        self, turns: list[dict], litellm_completion
    ):
        """
        Extract facts from recent conversation turns.
        litellm_completion: the litellm.acompletion function (passed to avoid circular imports).
        """
        if not turns:
            return

        # Format conversation for the extraction prompt
        convo_text = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Apex'}: {t['content']}"
            for t in turns
            if t.get("content")
        )

        if len(convo_text) < 20:
            return  # Too short, nothing to extract

        try:
            response = await litellm_completion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": EXTRACTION_PROMPT.format(
                            conversation=convo_text
                        ),
                    }
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            raw = response.choices[0].message.content.strip()

            # Clean up common AI response quirks
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]  # remove ```json line
                raw = raw.rsplit("```", 1)[0]  # remove closing ```
            raw = raw.strip()

            if not raw or raw == "[]":
                return

            facts = json.loads(raw)

            if not isinstance(facts, list):
                return

            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                category = fact.get("category", "fact")
                key = fact.get("key", "")
                value = fact.get("value", "")
                confidence = fact.get("confidence", 0.7)

                if key and value:
                    await self.knowledge_store.store_fact(
                        category=category,
                        key=key,
                        value=value,
                        confidence=confidence,
                        source="auto",
                    )

        except json.JSONDecodeError:
            pass  # AI returned non-JSON, skip silently
        except Exception as e:
            print(f"[FactExtractor] Error: {e}")
            traceback.print_exc()
