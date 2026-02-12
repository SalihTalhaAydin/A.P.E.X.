#!/usr/bin/env python3
"""
Suggest friendly names for Home Assistant entities using the device naming convention:
Room + Fixture/Level + Description (entity_id suffix -> Title Case with spaces).

Uses HA REST API: GET /states. No automatic renames; only prints a mapping so you can
bulk-edit in HA (Settings → Devices → Entity name) or use another tool.

Requires: HA_URL and either HA_TOKEN (long-lived) or REFRESH_TOKEN in .env or env. Loads .env from repo root if present.
Example (from repo root): put HA_URL, HA_TOKEN or REFRESH_TOKEN in .env, then run:
  python scripts/suggest_device_names.py [--domain light] [--out mapping.txt]
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

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


def get_access_token(
    ha_url: str, refresh_token: str, client_id: str
) -> str:
    """Exchange refresh token for short-lived access token."""
    data = (
        f"grant_type=refresh_token&refresh_token={refresh_token}&client_id={client_id}"
    ).encode()
    req = urllib.request.Request(
        f"{ha_url.rstrip('/')}/auth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)["access_token"]


def fetch_states(ha_url: str, token: str) -> list:
    """GET /api/states and return list of state dicts."""
    req = urllib.request.Request(
        f"{ha_url.rstrip('/')}/api/states",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def suggested_friendly_name(entity_id: str) -> str:
    """From entity_id suffix, suggest Title Case friendly name (Room Fixture Description style)."""
    suffix = entity_id.split(".")[-1]
    return suffix.replace("_", " ").title()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suggest friendly names for HA entities (convention: Room Fixture Description)."
    )
    parser.add_argument(
        "--domain",
        type=str,
        default="",
        help="Filter by domain, e.g. light, switch, climate",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Write mapping to file (entity_id | current_name | suggested_name)",
    )
    args = parser.parse_args()

    ha_url = os.environ.get(
        "HA_URL", "http://homeassistant.local:8123"
    ).rstrip("/")
    token = os.environ.get("HA_TOKEN", "").strip()
    if not token:
        refresh = os.environ.get("REFRESH_TOKEN", "").strip()
        if not refresh:
            print(
                "Set HA_TOKEN or REFRESH_TOKEN (and optionally HA_URL).",
                file=sys.stderr,
            )
            sys.exit(1)
        client_id = os.environ.get(
            "CLIENT_ID", "http://homeassistant.local:8123/"
        )
        token = get_access_token(ha_url, refresh, client_id)

    try:
        states = fetch_states(ha_url, token)
    except urllib.error.HTTPError as e:
        print(f"HA API error: {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching states: {e}", file=sys.stderr)
        sys.exit(1)

    if args.domain:
        states = [
            s
            for s in states
            if s.get("entity_id", "").startswith(f"{args.domain}.")
        ]

    lines = []
    for s in states:
        entity_id = s.get("entity_id", "")
        current = (s.get("attributes") or {}).get(
            "friendly_name"
        ) or entity_id
        suggested = suggested_friendly_name(entity_id)
        if current == suggested:
            continue  # skip already-conforming
        line = f"{entity_id} | {current} | {suggested}"
        lines.append(line)

    out_text = (
        "\n".join(lines)
        if lines
        else "# No entities to suggest (all already match convention)."
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(
                "# entity_id | current_friendly_name | suggested_friendly_name\n"
            )
            f.write(out_text)
        print(f"Wrote {len(lines)} suggestions to {args.out}")
    else:
        print(
            "# entity_id | current_friendly_name | suggested_friendly_name"
        )
        print(out_text)


if __name__ == "__main__":
    main()
