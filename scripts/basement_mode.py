#!/usr/bin/env python3
"""
Basement mode: Audit Home Assistant and activate basement-only (family sleeping).

Jarvis-style: checks the whole setup for "smart" behavior, then plays
everything in the basement — lights, media, fans, etc. — without touching
the rest of the house.

Requires: HA_TOKEN in .env (Profile -> Security -> Long-Lived Access Tokens)
Usage: python scripts/basement_mode.py
"""
import sys
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

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

HA_URL = (os.environ.get("HA_URL") or "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN = (os.environ.get("HA_TOKEN") or "").strip()
API = f"{HA_URL}/api"
HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

try:
    import httpx
except ImportError:
    print("pip install httpx", file=sys.stderr)
    sys.exit(1)


def _parse_json(r: httpx.Response):
    if not r.text or not r.text.strip():
        return {}
    try:
        return r.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"API returned non-JSON (status={r.status_code}, "
            f"body={r.text[:100]!r}): {e}"
        ) from e


async def ha_get(path: str):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{API}{path}", headers=HEADERS)
        r.raise_for_status()
        return _parse_json(r)


async def ha_post(path: str, data: dict | None = None):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(f"{API}{path}", headers=HEADERS, json=data)
        r.raise_for_status()
        return _parse_json(r)


async def template_eval(template: str) -> str:
    """HA template API returns plain text, not JSON."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{API}/template", headers=HEADERS,
            json={"template": template}
        )
        r.raise_for_status()
        return r.text or ""


async def main():
    if not HA_TOKEN or len(HA_TOKEN) < 20:
        print(
            "⚠️  No HA_TOKEN in .env — set a long-lived token from HA Profile → Security → Create Token.",
            file=sys.stderr,
        )
        print("   Then add HA_TOKEN=... to your .env file.", file=sys.stderr)
        sys.exit(1)

    print("--- Apex Brain: Home Assistant Audit & Basement Mode ---\n")

    try:
        # 1. Config / connectivity
        config = await ha_get("/config")
        version = config.get("version", "?")
        location = config.get("location_name", "Home")
        print(f"✓ Connected to Home Assistant {version} ({location})\n")

        # 2. Areas
        areas_raw = await template_eval(
            "{% for area in areas() %}{{ area }}|{{ area_name(area) }}\n{% endfor %}"
        )
        area_lines = [l for l in areas_raw.strip().split("\n") if l]
        areas = {}
        for line in area_lines:
            parts = line.split("|", 1)
            if len(parts) == 2:
                area_id, name = parts[0].strip(), parts[1].strip()
                areas[name.lower()] = area_id

        print(f"Areas: {len(areas)}")
        for name, aid in sorted(areas.items(), key=lambda x: x[0]):
            print(f"  • {name} ({aid})")

        # 3. Find basement (collect ALL basement areas for full coverage)
        basement_ids = []
        basement_names = []
        for name, aid in areas.items():
            if "basement" in name or "bsmnt" in name:
                basement_ids.append(aid)
                basement_names.append(name.title())
        basement_id = basement_ids[0] if basement_ids else None

        if not basement_id:
            print("\n⚠️  No 'basement' area found. Known areas above.")
            print("   Assign basement devices to an area named 'Basement' in HA Settings → Areas.")
            return

        print(f"\n✓ Basement area(s): {', '.join(basement_ids)}\n")

        # 4. Entities in basement (area_entities returns entity_id strings)
        by_domain = {}
        try:
            parts = []
            for name in basement_names:
                parts.append(
                    "{% for eid in area_entities('" + name + "') %}"
                    "{{ eid }}|{{ eid.split('.')[0] }}\n"
                    "{% endfor %}"
                )
            ent_template = "\n".join(parts)
            ents_raw = await template_eval(ent_template)
            basement_entities = []
            for line in (ents_raw or "").strip().split("\n"):
                if "|" in line:
                    eid, domain = line.split("|", 1)
                    basement_entities.append((eid.strip(), domain.strip()))
            for eid, dom in basement_entities:
                by_domain.setdefault(dom, []).append(eid)
        except Exception:
            pass  # area_entities may fail on older HA; service calls with area_id still work

        if by_domain:
            print("Basement entities:")
            for dom in sorted(by_domain.keys()):
                items = by_domain[dom]
                print(f"  {dom}: {len(items)} — {', '.join(items[:5])}{'…' if len(items) > 5 else ''}")
        else:
            print("Basement entities: (will use area_id for service calls)")

        # 5. Jarvis-style audit: automations, scenes
        states = await ha_get("/states")
        states_list = states if isinstance(states, list) else []
        automation_list = [s for s in states_list if s.get("entity_id", "").startswith("automation.")]
        scene_list = [s for s in states_list if s.get("entity_id", "").startswith("scene.")]

        print(f"\n--- Smart Home Audit ---")
        print(f"  Automations: {len(automation_list)}")
        print(f"  Scenes: {len(scene_list)}")

        # 6. Turn on basement (lights, switches, media, fans) — all basement areas
        actions = []
        for bid in basement_ids:
            try:
                await ha_post(
                    "/services/light/turn_on",
                    {"area_id": bid, "brightness_pct": 70},
                )
            except Exception:
                pass
        if basement_ids:
            actions.append("Lights on (70%)")

        for bid in basement_ids:
            try:
                await ha_post("/services/fan/turn_on", {"area_id": bid})
                actions.append("Fans on")
                break
            except Exception:
                pass

        for bid in basement_ids:
            try:
                await ha_post("/services/switch/turn_on", {"area_id": bid})
                actions.append("Switches on")
                break
            except Exception:
                pass

        # Media players often need entity_id; try area_id first, else per-entity
        for eid in by_domain.get("media_player", []):
            try:
                await ha_post(
                    "/services/media_player/turn_on",
                    {"entity_id": eid},
                )
                await asyncio.sleep(0.3)
                actions.append(f"Media player on")
                break  # One is enough for "play everything"
            except Exception:
                pass

        print(f"\n--- Basement activated (family sleeping upstairs) ---")
        for a in actions:
            print(f"  ✓ {a}")
        if not actions:
            print("  (No controllable entities in basement — lights, switches, fans, media)")

        print("\n✓ Done. Basement is ready. Rest of the house untouched.")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            print("✗ Auth failed — token invalid or expired.", file=sys.stderr)
        else:
            print(f"✗ HA API error {e.response.status_code}: {e.response.text[:200]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
