#!/usr/bin/env python3
"""
Update Apex Brain add-on options via Supervisor API (WebSocket).
Merges options from .env (e.g. GEMINI_API_KEY -> gemini_api_key) and POSTs to Supervisor.
Loads .env from repo root. Usage: python scripts/ha_update_addon_options.py
"""

import asyncio
import json
import os
import sys

# Load .env from repo root
_script_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_script_dir)
_env_path = os.path.join(_repo_root, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)

HA_URL = os.environ.get("HA_URL", "http://192.168.68.113:8123").rstrip("/")
HA_TOKEN = (os.environ.get("HA_TOKEN") or "").strip()
ADDON_SLUG = "14fc29d6_apex_brain"

try:
    import websockets
except ImportError:
    print("pip install websockets", file=sys.stderr)
    sys.exit(1)


async def main():
    if not HA_TOKEN or len(HA_TOKEN) < 20:
        print("Set HA_TOKEN in .env", file=sys.stderr)
        sys.exit(1)

    ws_url = HA_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"

    async with websockets.connect(ws_url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            print("Auth failed:", auth, file=sys.stderr)
            sys.exit(1)

        # 1. GET addon info (includes options)
        await ws.send(
            json.dumps({
                "id": 1,
                "type": "supervisor/api",
                "endpoint": f"/addons/{ADDON_SLUG}/info",
                "method": "get",
            })
        )
        r1 = json.loads(await ws.recv())
        if not r1.get("success"):
            print("GET addon info failed:", r1.get("error", r1))
            return

        data = (r1.get("result") or {}).get("data") or {}
        options = dict(data.get("options") or {})

        # Schema defaults (from config.yaml) if options empty (e.g. addon not yet configured)
        DEFAULTS = {
            "litellm_model": "gemini/gemini-2.5-pro",
            "openai_api_key": "",
            "anthropic_api_key": "",
            "gemini_api_key": "",
            "embedding_model": "text-embedding-3-small",
            "fact_extraction_model": "gpt-4o-mini",
            "recent_turns": 10,
            "max_facts_in_context": 20,
        }
        for k, v in DEFAULTS.items():
            options.setdefault(k, v)

        print("Current options keys:", list(options.keys()))

        # 2. Merge in gemini_api_key from env (GEMINI_API_KEY or GOOGLE_API_KEY)
        gemini_key = (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        ).strip()
        if gemini_key:
            options["gemini_api_key"] = gemini_key
            print("Merging gemini_api_key from GEMINI_API_KEY (len=%d)" % len(gemini_key))
        else:
            print("GEMINI_API_KEY not set in .env, skipping merge")

        # 3. POST updated options (WebSocket uses "data", Supervisor expects options in data.options)
        await ws.send(
            json.dumps({
                "id": 2,
                "type": "supervisor/api",
                "endpoint": f"/addons/{ADDON_SLUG}/options",
                "method": "post",
                "data": {"options": options},
            })
        )
        r2 = json.loads(await ws.recv())
        if r2.get("success"):
            print("Options updated successfully.")
        else:
            print("POST options failed:", r2.get("error", r2))

        # 4. Restart add-on to apply new options
        await ws.send(
            json.dumps({
                "id": 3,
                "type": "supervisor/api",
                "endpoint": f"/addons/{ADDON_SLUG}/info",
                "method": "get",
            })
        )
        r3 = json.loads(await ws.recv())
        state = (r3.get("result") or {}).get("data", {}).get("state", "")

        if state in ("started", "started, watchdog"):
            await ws.send(
                json.dumps({
                    "id": 4,
                    "type": "supervisor/api",
                    "endpoint": f"/addons/{ADDON_SLUG}/restart",
                    "method": "post",
                })
            )
            r4 = json.loads(await ws.recv())
            if r4.get("success"):
                print("Add-on restarted (options applied).")
            else:
                print("Restart failed:", r4.get("error", r4))


if __name__ == "__main__":
    asyncio.run(main())
