#!/usr/bin/env python3
"""
One-off diagnostic: list all light entities and their state (on/off/unavailable).
Uses HA REST API. Run from repo root with .env containing HA_URL and HA_TOKEN or REFRESH_TOKEN.
"""

import json
import os
import urllib.request

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

HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = (os.environ.get("HA_TOKEN") or "").strip()
REFRESH_TOKEN = (os.environ.get("REFRESH_TOKEN") or "").strip()
CLIENT_ID = os.environ.get("CLIENT_ID", (HA_URL + "/") if HA_URL else "")


def get_access_token():
    if HA_TOKEN:
        return HA_TOKEN
    if not REFRESH_TOKEN or not HA_URL:
        return None
    data = (
        f"grant_type=refresh_token&refresh_token={REFRESH_TOKEN}&client_id={CLIENT_ID}"
    ).encode()
    req = urllib.request.Request(
        f"{HA_URL}/auth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)["access_token"]


def fetch_states():
    token = get_access_token()
    if not token:
        raise SystemExit("Set HA_TOKEN or REFRESH_TOKEN (and HA_URL) in .env")
    req = urllib.request.Request(
        f"{HA_URL}/api/states",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def main():
    if not HA_URL:
        raise SystemExit("Set HA_URL in .env")
    states = fetch_states()
    lights = [s for s in states if (s.get("entity_id") or "").startswith("light.")]
    lights.sort(key=lambda s: s.get("entity_id", ""))
    unavailable = [s for s in lights if (s.get("state") or "").lower() == "unavailable"]
    print(f"HA URL: {HA_URL}")
    print(f"Light entities: {len(lights)} total, {len(unavailable)} unavailable\n")
    for s in lights:
        eid = s.get("entity_id", "?")
        state = s.get("state", "?")
        name = (s.get("attributes") or {}).get("friendly_name") or eid
        if state.lower() == "unavailable":
            print(f"  UNAVAILABLE  {eid}  ({name})")
        else:
            print(f"  {state:12}  {eid}  ({name})")
    if unavailable:
        print(f"\n--- Unavailable count: {len(unavailable)} ---")
        print("Check Settings → System → Logs for 'kasa' or 'tplink'; set DHCP reservations for Kasa devices.")


if __name__ == "__main__":
    main()
