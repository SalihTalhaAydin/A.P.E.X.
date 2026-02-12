"""
Apex Brain - FastAPI Server
Exposes an OpenAI-compatible API for Home Assistant integration,
plus a simple /api/chat endpoint for direct testing.
"""

import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
import litellm
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from memory.context_builder import ContextBuilder
from memory.conversation_store import ConversationStore
from memory.fact_extractor import FactExtractor
from memory.knowledge_store import KnowledgeStore
from pydantic import BaseModel
from tools import discover_tools
from tools.base import TOOL_REGISTRY
from tools.knowledge import set_knowledge_store

from brain.config import settings
from brain.conversation import Conversation
from brain.version import __version__

# --------------------------------------------------------------------------
# Globals (initialized on startup)
# --------------------------------------------------------------------------
conversation: Conversation | None = None
startup_time: float = 0


async def _check_ha_reachable() -> tuple[bool, str | None]:
    """
    Perform one GET to HA Core API from this process (add-on or local).
    Returns (success, error_message). Uses same URL/headers as smart home tools.
    Timeout 3s so health/debug endpoints do not block long.
    """
    url = f"{settings.ha_api_url}/config"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url, headers=settings.ha_headers)
            if r.status_code == 200:
                return True, None
            return False, f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:200]


async def _embed_text(text: str) -> list[float] | None:
    """Generate embedding using LiteLLM. Used by knowledge store."""
    try:
        response = await litellm.aembedding(
            model=settings.embedding_model,
            input=[text],
        )
        return response.data[0]["embedding"]
    except Exception as e:
        print(f"[Embedding] Error: {e}")
        return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown logic."""
    global conversation, startup_time
    startup_time = time.time()

    print("=" * 50)
    print("  Apex Brain starting up...")
    print(f"  AI Model: {settings.litellm_model}")
    print(f"  Database: {settings.db_path}")
    print(f"  HA URL: {settings.ha_url}")
    print("=" * 50)

    # Set API keys
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

    # Initialize memory stores
    convo_store = ConversationStore(settings.db_path)
    await convo_store.initialize()

    knowledge_store = KnowledgeStore(settings.db_path)
    knowledge_store.set_embed_function(_embed_text)
    await knowledge_store.initialize()

    # Initialize fact extractor
    fact_extractor = FactExtractor(
        knowledge_store=knowledge_store,
        model=settings.fact_extraction_model,
    )

    # Initialize context builder
    context_builder = ContextBuilder(
        conversation_store=convo_store,
        knowledge_store=knowledge_store,
        recent_turns_count=settings.recent_turns,
        max_facts=settings.max_facts_in_context,
    )

    # Discover and register tools
    discover_tools()
    set_knowledge_store(knowledge_store)
    print(f"  Tools loaded: {', '.join(TOOL_REGISTRY.keys())}")

    # Create conversation handler
    conversation = Conversation(
        conversation_store=convo_store,
        knowledge_store=knowledge_store,
        fact_extractor=fact_extractor,
        context_builder=context_builder,
    )

    print("  Apex Brain is online.")
    print("=" * 50)

    yield

    # Shutdown
    await convo_store.close()
    await knowledge_store.close()
    print("Apex Brain shut down.")


# --------------------------------------------------------------------------
# FastAPI app
# --------------------------------------------------------------------------
app = FastAPI(
    title="Apex Brain",
    description="Personal AI assistant with memory and smart home control",
    version=__version__,
    lifespan=lifespan,
)


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    session_id: str


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint. Includes HA connectivity when running as add-on."""
    uptime = time.time() - startup_time if startup_time else 0
    ha_ok, ha_err = await _check_ha_reachable()
    out = {
        "status": "online",
        "model": settings.litellm_model,
        "uptime_seconds": round(uptime),
        "tools_loaded": list(TOOL_REGISTRY.keys()),
        "ha_reachable": ha_ok,
    }
    if ha_err:
        out["ha_error"] = ha_err
    return out


@app.get("/api/debug/ha")
async def debug_ha():
    """
    Diagnostic: can this instance reach the Home Assistant Core API?
    Uses the same URL and token as smart home tools. Useful after "light didn't work".
    """
    ha_ok, ha_err = await _check_ha_reachable()
    return {
        "ha_reachable": ha_ok,
        "ha_error": ha_err,
        "ha_url": settings.ha_url,
    }


@app.post("/api/chat")
async def simple_chat(req: ChatRequest):
    """
    Simple chat endpoint for testing and direct integrations.
    POST {"message": "turn off the lights"} -> {"response": "Done."}
    """
    if not conversation:
        return JSONResponse(
            status_code=503, content={"error": "Not ready"}
        )

    response_text = await conversation.handle(req.message, req.session_id)
    return ChatResponse(response=response_text, session_id=req.session_id)


@app.post("/v1/chat/completions")
async def openai_compatible(request: Request):
    """
    OpenAI-compatible chat completions endpoint.
    This is what HA's Extended OpenAI Conversation integration talks to.
    We extract the user's message, process it through Apex, and return
    in OpenAI's expected format.
    """
    if not conversation:
        return JSONResponse(
            status_code=503, content={"error": "Not ready"}
        )

    body = await request.json()
    messages = body.get("messages", [])

    # Extract the last user message
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multimodal format
                for part in content:
                    if (
                        isinstance(part, dict)
                        and part.get("type") == "text"
                    ):
                        user_message = part.get("text", "")
                        break
            else:
                user_message = content
            break

    if not user_message:
        return JSONResponse(
            status_code=400,
            content={"error": "No user message found"},
        )

    # Process through Apex
    response_text = await conversation.handle(user_message)

    # Return in OpenAI chat completion format
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": settings.litellm_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


# --------------------------------------------------------------------------
# Run directly: python -m brain.server
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "brain.server:app",
        host="0.0.0.0",
        port=settings.port,
        reload=True,
    )
