"""
Conversation Orchestrator - The heart of Apex.
Handles the full flow: context build -> AI call -> tool loop -> response.
Triggers background fact extraction after each conversation.
"""

import asyncio
import json
import traceback

import litellm
from memory.context_builder import ContextBuilder
from memory.conversation_store import ConversationStore
from memory.fact_extractor import FactExtractor
from memory.knowledge_store import KnowledgeStore
from tools.base import execute_tool, get_openai_tool_definitions

from brain.config import settings


def _looks_like_device_action_claim(content: str) -> bool:
    """True if the text reads like the AI claiming it performed a device action."""
    if not content or not isinstance(content, str):
        return False
    lower = content.lower()
    phrases = (
        "cycled",
        "turned off",
        "turned on",
        "turned the light",
        "turned the lamp",
        "i've ",
        "i have ",
    )
    return any(p in lower for p in phrases)


class Conversation:
    def __init__(
        self,
        conversation_store: ConversationStore,
        knowledge_store: KnowledgeStore,
        fact_extractor: FactExtractor,
        context_builder: ContextBuilder,
    ):
        self.conversation_store = conversation_store
        self.knowledge_store = knowledge_store
        self.fact_extractor = fact_extractor
        self.context_builder = context_builder

        # Set API keys for LiteLLM
        if settings.openai_api_key:
            litellm.openai_key = settings.openai_api_key
        if settings.anthropic_api_key:
            litellm.anthropic_key = settings.anthropic_api_key

        # Silence litellm's verbose logging
        litellm.suppress_debug_info = True

    async def handle(
        self, user_message: str, session_id: str = "default"
    ) -> str:
        """
        Process a user message through the full Apex pipeline.
        Returns the final response text.
        """
        # 1. Save user turn
        await self.conversation_store.save_turn(
            "user", user_message, session_id
        )

        # 2. Build rich context (recent history + relevant facts + time)
        system_prompt = await self.context_builder.build(user_message)

        # 3. Prepare messages for the AI
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 4. Get tool definitions
        tool_defs = get_openai_tool_definitions()

        # 5. Call AI with tool loop
        response_text = await self._ai_tool_loop(messages, tool_defs)

        # 6. Save assistant response
        await self.conversation_store.save_turn(
            "assistant", response_text, session_id
        )

        # 7. Background fact extraction (user doesn't wait)
        recent = await self.conversation_store.get_recent(
            n=4, session_id=session_id
        )
        asyncio.create_task(self._safe_extract_facts(recent))

        return response_text

    async def _ai_tool_loop(
        self,
        messages: list[dict],
        tool_defs: list[dict],
        max_iterations: int = 10,
    ) -> str:
        """Call the AI, handle tool calls, repeat until we get a text response."""
        retry_nudge_done = False
        for iteration in range(max_iterations):
            try:
                kwargs = {
                    "model": settings.litellm_model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 2000,
                }
                if tool_defs:
                    kwargs["tools"] = tool_defs
                    kwargs["tool_choice"] = "auto"

                response = await litellm.acompletion(**kwargs)
            except Exception as e:
                return f"Error reaching AI: {e}"

            msg = response.choices[0].message
            is_first_response = len(messages) == 2  # only system + user

            # If no tool calls, we have our answer (or a confabulation)
            if not msg.tool_calls:
                text = msg.content or "Done."
                print(
                    f"  [AI] Text response (no tools called): {text[:150]}"
                )
                if is_first_response:
                    print("  [AI] First response had 0 tool calls.")
                if _looks_like_device_action_claim(text):
                    print(
                        "  [AI] WARNING: Responded with text only (no tool calls); "
                        "possible confabulation."
                    )
                    # One retry: nudge the model to use tools
                    if (
                        tool_defs
                        and not retry_nudge_done
                        and is_first_response
                    ):
                        retry_nudge_done = True
                        messages.append(msg.model_dump())
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "You must use the tools to perform the action. "
                                    "Do not reply with a summary only."
                                ),
                            },
                        )
                        continue
                return text

            # Process tool calls
            if is_first_response:
                print(f"  [AI] First response had {len(msg.tool_calls)} tool calls.")
            messages.append(msg.model_dump())

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                print(
                    f"  [Tool] {fn_name}({json.dumps(args, default=str)[:500]})"
                )

                result = await execute_tool(fn_name, args)
                print(f"  [Tool Result] {fn_name} -> {str(result)[:300]}")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    }
                )

        return "I ran into a loop processing your request. Could you rephrase?"

    async def _safe_extract_facts(self, recent_turns: list[dict]):
        """Safely run fact extraction in the background."""
        try:
            await self.fact_extractor.extract_from_conversation(
                turns=recent_turns,
                litellm_completion=litellm.acompletion,
            )
        except Exception as e:
            print(f"[FactExtractor] Background error: {e}")
            traceback.print_exc()
