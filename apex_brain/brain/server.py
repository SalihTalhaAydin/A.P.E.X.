"""
Apex Brain - FastAPI Server
Exposes an OpenAI-compatible API for Home Assistant
integration, plus /api/chat for testing and
/api/webhook for event-driven reactions.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
import litellm
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from memory.context_builder import ContextBuilder
from memory.conversation_store import ConversationStore
from memory.db_manager import SharedDbConnection
from memory.fact_extractor import FactExtractor
from memory.knowledge_store import KnowledgeStore
from memory.routine_store import RoutineStore
from pydantic import BaseModel, Field
from tools import discover_tools
from tools.base import TOOL_REGISTRY
from tools.knowledge import set_knowledge_store
from tools.mcp_bridge import MCPBridge
from tools.routines import set_routine_store

from brain.config import settings
from brain.conversation import Conversation
from brain.event_handler import (
    EventHandler,
    WebhookEvent,
    WebhookResponse,
)
from brain.version import __version__

logger = logging.getLogger(__name__)


async def _close_stores_if_present(
    shared_db: SharedDbConnection | None,
    routine_store,
    convo_store,
    knowledge_store,
) -> None:
    """Close store connections if present."""
    if routine_store is not None:
        await routine_store.close()
    if convo_store is not None:
        await convo_store.close()
    if knowledge_store is not None:
        await knowledge_store.close()
    if shared_db is not None:
        await shared_db.close()


# ---------------------------------------------------------
# Globals (initialized on startup)
# ---------------------------------------------------------
conversation: Conversation | None = None
event_handler: EventHandler | None = None
startup_time: float = 0


async def _check_ha_reachable() -> tuple[bool, str | None]:
    """Perform one GET to HA Core API."""
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


async def _embed_text(
    text: str,
) -> list[float] | None:
    """Generate embedding using LiteLLM."""
    try:
        response = await litellm.aembedding(
            model=settings.embedding_model,
            input=[text],
        )
        if not response.data:
            logger.warning(
                "Embedding API returned empty data for text: %s",
                text[:50],
            )
            return None
        item = response.data[0]
        if isinstance(item, dict):
            return item.get("embedding")
        return getattr(item, "embedding", None)
    except Exception as e:
        logger.error("Embedding error: %s", e)
        return None


async def _check_llm_reachable() -> None:
    """Best-effort connectivity check to the configured LLM provider."""
    model = settings.litellm_model
    if model.startswith("gpt-") or "openai" in model.lower():
        url = "https://api.openai.com/v1/models"
        label = "OpenAI"
    elif model.startswith("claude-") or "anthropic" in model.lower():
        url = "https://api.anthropic.com/v1/messages"
        label = "Anthropic"
    elif model.startswith("gemini/"):
        url = "https://generativelanguage.googleapis.com/"
        label = "Google Gemini"
    else:
        return

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            logger.info(
                "  LLM provider %s: reachable (HTTP %d)",
                label,
                r.status_code,
            )
    except Exception as e:
        logger.warning(
            "  LLM provider %s: NOT reachable (%s). "
            "Outbound API calls will fail until connectivity is restored.",
            label,
            e,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown logic."""
    global conversation, event_handler, startup_time
    startup_time = time.time()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=" * 50)
    logger.info("  Apex Brain starting up...")
    logger.info("  AI Model: %s", settings.litellm_model)
    logger.info("  Database: %s", settings.db_path)
    logger.info("  HA URL: %s", settings.ha_url)
    logger.info("=" * 50)

    # Validate API key for configured model
    model = settings.litellm_model
    if model.startswith("gpt-") or "openai" in model.lower():
        if not settings.openai_api_key:
            logger.error("Model %s requires openai_api_key.", model)
    elif model.startswith("claude-") or "anthropic" in model.lower():
        if not settings.anthropic_api_key:
            logger.error("Model %s requires anthropic_api_key.", model)
    elif model.startswith("gemini/"):
        if not settings.gemini_api_key:
            logger.error("Model %s requires gemini_api_key.", model)

    # Set API keys
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

    await _check_llm_reachable()

    shared_db: SharedDbConnection | None = None
    convo_store = None
    knowledge_store = None
    routine_store = None
    audit_store = None
    mcp_bridge: MCPBridge | None = None
    fact_cleanup_task: asyncio.Task | None = None

    try:
        # Database
        shared_db = SharedDbConnection(settings.db_path)
        await shared_db.initialize()

        # Memory stores
        convo_store = ConversationStore(shared_db)
        await convo_store.initialize()
        pruned = await convo_store.cleanup_old_turns(
            settings.conversation_retention_days
        )
        if pruned:
            logger.info("Pruned %d old conversation turns", pruned)

        knowledge_store = KnowledgeStore(shared_db)
        knowledge_store.set_embed_function(_embed_text)
        await knowledge_store.initialize()

        # Fact extractor
        fact_extractor = FactExtractor(
            knowledge_store=knowledge_store,
            model=settings.fact_extraction_model,
        )

        # Context builder
        context_builder = ContextBuilder(
            conversation_store=convo_store,
            knowledge_store=knowledge_store,
            recent_turns_count=settings.recent_turns,
            max_facts=settings.max_facts_in_context,
        )

        # Routine store
        routine_store = RoutineStore(shared_db)
        await routine_store.initialize()
        await routine_store.migrate_from_knowledge_store(knowledge_store)

        # Discover and register tools
        discover_tools()
        set_knowledge_store(knowledge_store)
        set_routine_store(routine_store)
        logger.info(
            "  Tools loaded: %s",
            ", ".join(TOOL_REGISTRY.keys()),
        )

        # Audit store
        from memory.audit_store import AuditStore
        from tools.configure import (
            set_audit_store as set_configure_audit,
        )
        from tools.manage import set_audit_store as set_manage_audit

        audit_store = AuditStore(shared_db)
        await audit_store.initialize()
        set_manage_audit(audit_store)
        set_configure_audit(audit_store)
        logger.info("  Audit store: initialized")

        # MCP bridge (optional)
        if settings.mcp_server_url:
            mcp_bridge = MCPBridge(
                url=settings.mcp_server_url,
                transport=settings.mcp_transport,
            )
            await mcp_bridge.connect()
            if mcp_bridge.connected:
                await mcp_bridge.discover_tools(
                    skip_names=set(TOOL_REGISTRY.keys()),
                )
                logger.info(
                    "  MCP tools: %d from %s",
                    mcp_bridge.tool_count,
                    settings.mcp_server_url,
                )

        # Conversation handler
        conversation = Conversation(
            conversation_store=convo_store,
            knowledge_store=knowledge_store,
            fact_extractor=fact_extractor,
            context_builder=context_builder,
            mcp_bridge=mcp_bridge,
        )

        # Event handler (webhook reactions)
        if settings.webhook_enabled:
            event_handler = EventHandler(
                conversation=conversation,
                cooldown=settings.webhook_cooldown_seconds,
            )
            logger.info("  Webhook endpoint: enabled")

        # Background fact cleanup
        from brain.fact_cleanup import FactCleanupTimer

        fact_cleanup = FactCleanupTimer(
            knowledge_store=knowledge_store,
            interval_hours=settings.fact_cleanup_interval_hours,
        )
        fact_cleanup_task = await fact_cleanup.start()

        logger.info("  Apex Brain is online.")
        logger.info("=" * 50)

    except Exception:
        logger.exception("Startup failed — cleaning up")
        if conversation:
            await conversation.shutdown()
        if mcp_bridge and mcp_bridge.connected:
            await mcp_bridge.disconnect()
        if audit_store:
            await audit_store.close()
        await _close_stores_if_present(
            shared_db, routine_store, convo_store, knowledge_store
        )
        raise

    yield

    # Shutdown
    if fact_cleanup_task and not fact_cleanup_task.done():
        fact_cleanup_task.cancel()
        try:
            await fact_cleanup_task
        except asyncio.CancelledError:
            pass
    if conversation:
        await conversation.shutdown()
    if mcp_bridge and mcp_bridge.connected:
        await mcp_bridge.disconnect()
    from tools.ha_helpers import close_ha_client
    from tools.manage import close_supervisor_client

    await close_ha_client()
    await close_supervisor_client()
    if audit_store:
        await audit_store.close()
    await _close_stores_if_present(
        shared_db, routine_store, convo_store, knowledge_store
    )
    logger.info("Apex Brain shut down.")


# ---------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------
app = FastAPI(
    title="Apex Brain",
    description=(
        "Personal AI assistant with memory and smart home control"
    ),
    version=__version__,
    lifespan=lifespan,
)


# ---------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup: float = time.time()
        self._cleanup_interval: float = 60.0

    def is_allowed(
        self, key: str, max_requests: int, window_seconds: int = 60
    ) -> bool:
        now = time.time()
        self._maybe_cleanup(now)

        cutoff = now - window_seconds
        self._requests[key] = [
            t for t in self._requests[key] if t > cutoff
        ]

        if len(self._requests[key]) >= max_requests:
            return False

        self._requests[key].append(now)
        return True

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        cutoff = now - 300
        stale_keys = [
            k
            for k, v in self._requests.items()
            if not v or all(t < cutoff for t in v)
        ]
        for k in stale_keys:
            del self._requests[k]


rate_limiter = RateLimiter()


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting to /api/chat and /api/webhook."""
    path = request.url.path

    if path == "/api/chat":
        if request.client:
            client_ip = request.client.host
        else:
            forwarded = request.headers.get("x-forwarded-for", "")
            client_ip = (
                forwarded.split(",")[0].strip() if forwarded else "unknown"
            )
        key = f"chat:{client_ip}"
        if not rate_limiter.is_allowed(
            key, max_requests=30, window_seconds=60
        ):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many requests. "
                    "Limit: 30/min for /api/chat."
                },
            )

    elif path == "/api/webhook":
        if request.client:
            client_ip = request.client.host
        else:
            forwarded = request.headers.get("x-forwarded-for", "")
            client_ip = (
                forwarded.split(",")[0].strip() if forwarded else "unknown"
            )
        key = f"webhook:{client_ip}"
        if not rate_limiter.is_allowed(
            key, max_requests=60, window_seconds=60
        ):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many requests. "
                    "Limit: 60/min for /api/webhook."
                },
            )

    return await call_next(request)


# ---------------------------------------------------------
# Models
# ---------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(..., max_length=50000)
    session_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    session_id: str


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------


@app.get("/health")
async def health():
    """Health check with HA connectivity."""
    uptime = time.time() - startup_time if startup_time else 0
    ha_ok, ha_err = await _check_ha_reachable()
    out = {
        "status": "online",
        "model": settings.litellm_model,
        "uptime_seconds": round(uptime),
        "tools_loaded": list(TOOL_REGISTRY.keys()),
        "ha_reachable": ha_ok,
        "webhook_enabled": settings.webhook_enabled,
    }
    if ha_err:
        out["ha_error"] = ha_err
    if conversation and conversation.mcp_bridge:
        bridge = conversation.mcp_bridge
        out["mcp_connected"] = bridge.connected
        out["mcp_tools"] = bridge.tool_names
    return out


@app.get("/api/debug/ha")
async def debug_ha():
    """Diagnostic: HA Core API reachable?"""
    ha_ok, ha_err = await _check_ha_reachable()
    return {
        "ha_reachable": ha_ok,
        "ha_error": ha_err,
        "ha_url": settings.ha_url,
    }


@app.post("/api/chat")
async def simple_chat(req: ChatRequest):
    """Simple chat for testing."""
    if not conversation:
        return JSONResponse(
            status_code=503,
            content={"error": "Not ready"},
        )

    try:
        response_text = await asyncio.wait_for(
            conversation.handle(req.message, req.session_id),
            timeout=180,
        )
    except TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"error": "Request timed out"},
        )
    return ChatResponse(
        response=response_text,
        session_id=req.session_id,
    )


@app.post("/api/webhook")
async def handle_webhook(event: WebhookEvent):
    """Receive events from HA automations."""
    if not settings.webhook_enabled:
        return WebhookResponse(
            status="ignored",
            message="Webhooks disabled.",
        )

    if not event_handler:
        return JSONResponse(
            status_code=503,
            content={"error": "Not ready"},
        )

    if settings.webhook_secret:
        provided = event.attributes.get("secret", "") or ""
        expected = settings.webhook_secret
        if not hmac.compare_digest(expected, provided):
            return JSONResponse(
                status_code=403,
                content={"error": "Invalid secret"},
            )

    result = await event_handler.process_event(event)
    return result


@app.get("/api/webhook/config")
async def webhook_config():
    """Return supported event types and example YAML."""
    return {
        "enabled": settings.webhook_enabled,
        "cooldown_seconds": settings.webhook_cooldown_seconds,
        "supported_event_types": [
            "motion",
            "door",
            "temperature",
            "state_changed",
        ],
    }


@app.post("/v1/chat/completions")
async def openai_compatible(request: Request):
    """OpenAI-compatible chat completions.

    Used by HA's Extended OpenAI Conversation.
    """
    if not conversation:
        return JSONResponse(
            status_code=503,
            content={"error": "Not ready"},
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON in request body"},
        )
    messages = body.get("messages", [])

    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
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

    raw_session = (
        body.get("user")
        or body.get("conversation_id")
        or request.headers.get("x-session-id")
        or request.headers.get("x-conversation-id")
    )
    sanitized = re.sub(
        r"[^a-zA-Z0-9_-]",
        "",
        str(raw_session) if raw_session else "",
    )[:64]
    session_id = sanitized or "default"

    # Voice mode: HA voice pipeline uses this endpoint.
    # Shorter timeout, reduced tool set, lighter prompt.
    voice_mode = True

    try:
        response_text = await asyncio.wait_for(
            conversation.handle(
                user_message, session_id,
                voice_mode=voice_mode,
            ),
            timeout=60,
        )
    except TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"error": "Request timed out"},
        )

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


# ---------------------------------------------------------
# Run directly: python -m brain.server
# ---------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "brain.server:app",
        host="0.0.0.0",
        port=settings.port,
        reload=True,
    )
