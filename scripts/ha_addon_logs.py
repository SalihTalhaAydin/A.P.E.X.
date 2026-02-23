#!/usr/bin/env python3
"""Fetch Apex Brain add-on logs via Supervisor API."""

import asyncio
import json
import os

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

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN = (os.environ.get("HA_TOKEN") or "").strip()
ADDON_SLUG = "14fc29d6_apex_brain"

import websockets


async def main():
    ws_url = HA_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
    async with websockets.connect(ws_url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            print("Auth failed")
            return
        await ws.send(json.dumps({
            "id": 1,
            "type": "supervisor/api",
            "endpoint": f"/addons/{ADDON_SLUG}/logs",
            "method": "get",
        }))
        r = json.loads(await ws.recv())
        if not r.get("success"):
            print("Error:", r.get("error", r))
            return
        res = r.get("result") or {}
        data = res.get("data", res)
        if isinstance(data, str):
            lines = data.strip().split("\n")
            print("\n".join(lines[-80:]))
        elif data:
            print(str(data)[:3000])
        else:
            print("(no log data)")


if __name__ == "__main__":
    asyncio.run(main())
