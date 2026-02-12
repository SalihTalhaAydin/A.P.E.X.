#!/usr/bin/env python3
"""
Refresh the add-on store and update the Apex Brain add-on to the latest version.
Use after pushing new code to GitHub so HA Supervisor sees the new version.

Requires: HA_TOKEN (long-lived) or REFRESH_TOKEN in env. Optional: HA_URL.
Loads .env from repo root if present (same directory as script's parent).
Usage: python scripts/ha_update_apex_addon.py
"""

import asyncio
import json
import os
import sys

# Load .env from repo root (parent of scripts/)
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

# Default: try HA IP from local network (override with HA_URL or use homeassistant.local)
HA_URL = os.environ.get("HA_URL", "http://192.168.68.113:8123").rstrip("/")
HA_TOKEN = (os.environ.get("HA_TOKEN") or "").strip()
REFRESH_TOKEN = (os.environ.get("REFRESH_TOKEN") or "").strip()
CLIENT_ID = os.environ.get("CLIENT_ID", HA_URL + "/")
ADDON_SLUG = "14fc29d6_apex_brain"

try:
    import websockets
except ImportError:
    print("pip install websockets", file=sys.stderr)
    sys.exit(1)


def get_access_token():
    if HA_TOKEN and len(HA_TOKEN) > 20:
        return HA_TOKEN
    if not REFRESH_TOKEN:
        return None
    import urllib.request

    data = (
        f"grant_type=refresh_token&refresh_token={REFRESH_TOKEN}&client_id={CLIENT_ID}"
    ).encode()
    req = urllib.request.Request(
        HA_URL + "/auth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())["access_token"]
    except Exception as e:
        print(f"Refresh token failed: {e}", file=sys.stderr)
        return None


async def main():
    token = get_access_token()
    if not token:
        print(
            "Set HA_TOKEN (or REFRESH_TOKEN) in .env or environment. Long-lived token: HA Profile → Security → Create Token.",
            file=sys.stderr,
        )
        sys.exit(1)

    ws_url = HA_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"

    async with websockets.connect(ws_url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            print("Auth failed:", auth, file=sys.stderr)
            sys.exit(1)

        # 1. Reload add-on store so Supervisor fetches latest from GitHub
        await ws.send(
            json.dumps(
                {"id": 1, "type": "supervisor/api", "endpoint": "/addons/reload", "method": "post"}
            )
        )
        r1 = json.loads(await ws.recv())
        if not r1.get("success", True):
            print("Reload store failed:", r1.get("error", r1))
        else:
            print("Store reloaded.")

        # 2. Get add-on info (current version, update_available)
        await ws.send(
            json.dumps(
                {
                    "id": 2,
                    "type": "supervisor/api",
                    "endpoint": f"/addons/{ADDON_SLUG}/info",
                    "method": "get",
                }
            )
        )
        r2 = json.loads(await ws.recv())
        data = (r2.get("result") or {}).get("data") or {}
        version = data.get("version", "?")
        version_latest = data.get("version_latest", "?")
        update_available = data.get("update_available", False)
        state = data.get("state", "?")

        print(f"Add-on: {ADDON_SLUG}")
        print(f"  Installed version: {version}")
        print(f"  Latest version:    {version_latest}")
        print(f"  State:             {state}")
        print(f"  Update available:  {update_available}")

        if update_available:
            # 3. Update the add-on (install latest from store)
            await ws.send(
                json.dumps(
                    {
                        "id": 3,
                        "type": "supervisor/api",
                        "endpoint": f"/addons/{ADDON_SLUG}/update",
                        "method": "post",
                    }
                )
            )
            r3 = json.loads(await ws.recv())
            if r3.get("success", True):
                print("Update started successfully. Restart the add-on from HA UI if needed.")
            else:
                print("Update failed:", r3.get("error", r3))
        else:
            if version != version_latest:
                print("No update available yet. Wait a minute and run again, or use Rebuild in HA UI.")
            else:
                print("Add-on is already on the latest version.")


if __name__ == "__main__":
    asyncio.run(main())
