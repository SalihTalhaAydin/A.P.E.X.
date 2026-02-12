#!/usr/bin/env python3
"""
Assign HA devices to areas and set entity/device names per the device naming convention
(Room + Fixture/Level + Description). Uses WebSocket config APIs.

SAFE FLOW (recommended):
  1. Run with --dry-run first to see exactly what would change (no writes).
  2. Review the printed device and entity updates.
  3. Run without --dry-run to apply; you will be asked to confirm before any changes.

Requires: HA_TOKEN (long-lived) or REFRESH_TOKEN, and HA_URL in .env or env (never hardcode tokens). Loads .env from repo root if present. pip install websockets.
"""

import argparse
import asyncio
import json
import os
import re
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

# Optional: use websockets if available
try:
    import websockets
except ImportError:
    websockets = None

# ---------------------------------------------------------------------------
# Config from env only (never hardcode tokens)
# ---------------------------------------------------------------------------
HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = (
    os.environ.get("HA_TOKEN") or ""
).strip()  # Long-lived access token (preferred)
REFRESH_TOKEN = (os.environ.get("REFRESH_TOKEN") or "").strip()
# Client ID must match what was used when refresh token was created (often homeassistant.local)
CLIENT_ID = os.environ.get("CLIENT_ID", "http://homeassistant.local:8123/")
WS_URL = (
    HA_URL.replace("http://", "ws://").replace("https://", "wss://")
    + "/api/websocket"
)

# User's area names (normalized lowercase for matching)
USER_AREAS = [
    "my office",
    "basement kitchen",
    "gym",
    "basement living area",
    "entrance guest room",
    "entrance bathroom",
    "laundry room",
    "laundry",
    "kitchen",
    "sunroom",
    "dining room",
    "sunroom/dining room",
    "mark's playroom",
    "playroom",
    "cinema room",
    "living room",
    "cinema",
    "master bedroom",
    "master bathroom",
    "closet",
    "alona's office",
    "mark's room",
    "guest room",
    "guest bathroom",
    "stairs",
    "stair",
]

# Keywords to disambiguate (e.g. "office" -> my office vs alona's office)
CONTEXT_KEYWORDS = {
    "basement": [
        "my office",
        "basement kitchen",
        "gym",
        "basement living area",
    ],
    "entrance": ["entrance guest room", "entrance bathroom"],
    "master": ["master bedroom", "master bathroom", "closet"],
    "mark": ["mark's playroom", "mark's room"],
    "alona": ["alona's office"],
    "guest": ["entrance guest room", "guest room", "guest bathroom"],
    "stair": ["stairs"],
    "laundry": ["laundry room", "laundry"],
    "kitchen": ["kitchen", "basement kitchen"],
    "living": ["basement living area", "living room", "cinema room"],
    "dining": ["sunroom", "dining room"],
    "gym": ["gym"],
    "cinema": ["cinema room", "living room"],
}


def get_access_token():
    """Return HA access token: use HA_TOKEN if set, else exchange REFRESH_TOKEN."""
    if HA_TOKEN:
        return HA_TOKEN
    data = f"grant_type=refresh_token&refresh_token={REFRESH_TOKEN}&client_id={CLIENT_ID}".encode()
    req = urllib.request.Request(
        f"{HA_URL}/auth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def looks_like_kasa_duplicate(name: str) -> bool:
    """True if name looks like ID, model, or non-human (skip for area/name updates)."""
    n = (name or "").strip()
    # Empty/missing name: do NOT treat as duplicate (might just be unset in registry)
    if not n:
        return False
    # Long hex/uuid style
    if re.match(r"^[a-fA-F0-9\-]{20,}$", n):
        return True
    # Common Kasa model patterns (KP115, HS220, KL430L, EP25, etc.)
    if re.match(r"^[KkHhEeLl][PpSsLlEe][0-9]{2,3}[a-zA-Z]?$", n):
        return True
    # Single long token that looks technical (no spaces, long)
    if " " not in n and len(n) > 18 and re.search(r"[0-9a-fA-F]{10,}", n):
        return True
    # Contains obvious model/ID substrings
    if re.search(r"\b(HS\d+|KP\d+|KL\d+|EP\d+)\b", n, re.I):
        return True
    return False


def normalize(s: str) -> str:
    return (s or "").lower().strip()


# Abbreviations and typos in entity_id parts -> proper word (for friendly names)
ABBREV_EXPAND = {
    "bsmnt": "Basement",
    "ent": "Entrance",
    "enterance": "Entrance",
    "upstaris": "Upstairs",
    "bedr": "Bedroom",
    "strs": "Stairs",
    "str": "Stairs",
    "led": "LED",
    "leds": "LEDs",
    "downstairs": "Downstairs",
    "upstairs": "Upstairs",
    "up": "Upstairs",
    "kitchen": "Kitchen",
    "laundry": "Laundry",
    "sunroom": "Sunroom",
    "dining": "Dining",
    "basement": "Basement",
    "entrance": "Entrance",
    "bedroom": "Bedroom",
    "stairs": "Stairs",
    "front": "Front",
    "back": "Back",
    "outside": "Outside",
    "hall": "Hall",
    "hallway": "Hallway",
    "ceiling": "Ceiling",
    "cabinet": "Cabinet",
    "under": "Under",
    "middle": "Middle",
    "towards": "Towards",
    "right": "Right",
    "left": "Left",
    "side": "Side",
    "mirror": "Mirror",
    "restart": "Restart",
    "motion": "Motion",
    "sensor": "Sensor",
    "cloud": "Cloud",
    "connection": "Connection",
    "signal": "Signal",
    "strength": "Strength",
    "not": "Not",
    "used": "Used",
}


def expand_entity_id_to_friendly(suffix: str) -> str:
    """Turn entity_id suffix into a proper friendly name: expand abbreviations, fix typos, Title Case."""
    if not suffix:
        return ""
    parts = suffix.split("_")
    expanded = []
    for p in parts:
        key = p.lower()
        if key in ABBREV_EXPAND:
            expanded.append(ABBREV_EXPAND[key])
        elif p.isdigit() or (len(p) <= 2 and p.upper() == p):
            expanded.append(p)
        else:
            expanded.append(p.capitalize() if p else p)
    result = " ".join(expanded)
    # Phrase-level fixes (possessive, brands)
    result = result.replace("Mark S ", "Mark's ")
    result = result.replace("Tp Link ", "TP-Link ")
    result = result.replace("Adguard ", "AdGuard ")
    result = result.replace("Roborock ", "Roborock ")
    return result


def match_area_for_device(
    device_name: str, entity_names: list, area_id_by_name: dict
) -> str | None:
    """Return area_id if we can match device/entity names to a known area."""
    combined = " ".join(
        [normalize(device_name or "")]
        + [normalize(n) for n in entity_names]
    )
    if not combined:
        return None
    candidates = []
    for area_name, area_id in area_id_by_name.items():
        an = normalize(area_name)
        # HA may use "Cinema/Living Room" - match full name or any part after /
        parts = [
            p.strip() for p in an.replace(" ", "/").split("/") if p.strip()
        ]
        if an in combined or an.replace(" ", "") in combined.replace(
            " ", ""
        ):
            candidates.append((area_name, area_id))
        elif any(p in combined for p in parts if len(p) >= 3):
            candidates.append((area_name, area_id))
    if not candidates:
        for area_name, area_id in area_id_by_name.items():
            an = normalize(area_name)
            words = an.replace("'", " ").replace("/", " ").split()
            for w in words:
                if len(w) >= 4 and w in combined:
                    candidates.append((area_name, area_id))
                    break
    if not candidates:
        return None
    for keyword, area_names in CONTEXT_KEYWORDS.items():
        if keyword in combined:
            for an, aid in candidates:
                if normalize(an) in [normalize(a) for a in area_names]:
                    return aid
    candidates.sort(key=lambda x: -len(x[0]))
    return candidates[0][1] if candidates else None


def suggest_entity_name(
    entity_id: str, current_name: str, force_all: bool = False
) -> str | None:
    """Suggest convention name: entity_id suffix with abbreviations expanded (e.g. bsmnt -> Basement)."""
    suffix = entity_id.split(".")[-1]
    derived = expand_entity_id_to_friendly(suffix)
    if not current_name or normalize(current_name) == normalize(derived):
        return derived
    if force_all:
        return derived
    # If current is already human-looking and good, don't override
    if (
        len(current_name) > 3
        and " " in current_name
        and not looks_like_kasa_duplicate(current_name)
    ):
        return None
    return derived


async def run(dry_run: bool, force_all: bool = False):
    if not websockets:
        print("Install websockets: pip install websockets")
        return
    print("Getting access token...")
    try:
        token = get_access_token()
    except Exception as e:
        print(f"Failed to get token: {e}")
        return
    print("Connecting to WebSocket...")
    msg_id = [0]

    def next_id():
        msg_id[0] += 1
        return msg_id[0]

    async with websockets.connect(WS_URL, close_timeout=5) as ws:
        auth_required = await ws.recv()
        if "auth_required" not in auth_required:
            print("Unexpected:", auth_required[:200])
            return
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth_ok = await ws.recv()
        if "auth_ok" not in auth_ok:
            print("Auth failed:", auth_ok[:300])
            return
        print("Authenticated.")

        async def send_recv(msg):
            await ws.send(json.dumps(msg))
            raw = await ws.recv()
            return json.loads(raw)

        # Fetch registries
        print("Fetching area registry...")
        r_areas = await send_recv(
            {"id": next_id(), "type": "config/area_registry/list"}
        )
        areas = r_areas.get("result", [])
        area_id_by_name = {
            a["name"]: a["area_id"] for a in areas if a.get("name")
        }
        print(
            f"  Found {len(areas)} areas: {list(area_id_by_name.keys())}"
        )

        print("Fetching device registry...")
        r_devices = await send_recv(
            {"id": next_id(), "type": "config/device_registry/list"}
        )
        devices = r_devices.get("result", [])
        print(f"  Found {len(devices)} devices")

        print("Fetching entity registry...")
        r_entities = await send_recv(
            {"id": next_id(), "type": "config/entity_registry/list"}
        )
        entities_raw = r_entities.get("result", [])
        # Build entity_id -> entry (with name, device_id, etc.)
        entities = {}
        for e in entities_raw:
            eid = e.get("entity_id")
            if eid:
                entities[eid] = e
        # Group entities by device_id
        entities_by_device = {}
        for _eid, e in entities.items():
            did = e.get("device_id")
            if did:
                entities_by_device.setdefault(did, []).append(e)

        print(f"  Found {len(entities)} entities")

        # Decide updates: skip Kasa duplicates, match areas, suggest names
        device_updates = []  # (device_id, area_id?, name_by_user?)
        entity_updates = []  # (entity_id, name?)
        kasa_skipped_devices = set()
        kasa_skipped_entities = set()

        for device in devices:
            device_id = device["id"]
            d_name = device.get("name_by_user") or device.get("name") or ""
            d_area = device.get("area_id")
            dev_entities = entities_by_device.get(device_id, [])
            entity_names = []
            for e in dev_entities:
                ename = (
                    e.get("name")
                    or e.get("original_name")
                    or e.get("entity_id", "").split(".")[-1]
                )
                entity_names.append(ename)
            # Check if device or any entity looks like Kasa duplicate
            if looks_like_kasa_duplicate(d_name):
                kasa_skipped_devices.add(device_id)
                continue
            if any(looks_like_kasa_duplicate(n) for n in entity_names):
                # Skip this device for area/name updates (treat as duplicate)
                kasa_skipped_devices.add(device_id)
                continue
            # Suggest area
            suggested_area = match_area_for_device(
                d_name, entity_names, area_id_by_name
            )
            if suggested_area and suggested_area != d_area:
                device_updates.append((device_id, suggested_area, None))
            elif not d_area and suggested_area:
                device_updates.append((device_id, suggested_area, None))
            # Optional: set device name_by_user if we have a better one
            better_device_name = None
            if dev_entities and not d_name:
                first_entity = dev_entities[0]
                ename = (
                    first_entity.get("name")
                    or first_entity.get("entity_id", "").split(".")[-1]
                )
                if not looks_like_kasa_duplicate(ename):
                    better_device_name = ename.replace("_", " ").title()
            if better_device_name and not device.get("name_by_user"):
                # Append to device_updates if we already have an entry, or add new
                found = next(
                    (u for u in device_updates if u[0] == device_id), None
                )
                if found:
                    device_updates = [
                        (
                            did,
                            aid,
                            better_device_name if did == device_id else nb,
                        )
                        for did, aid, nb in device_updates
                    ]
                else:
                    device_updates.append(
                        (
                            device_id,
                            d_area or suggested_area,
                            better_device_name,
                        )
                    )

        for entity_id, e in entities.items():
            if looks_like_kasa_duplicate(e.get("name") or ""):
                kasa_skipped_entities.add(entity_id)
                continue
            current_name = e.get("name") or e.get("original_name") or ""
            suggested = suggest_entity_name(
                entity_id, current_name, force_all=force_all
            )
            if suggested and suggested != current_name:
                entity_updates.append((entity_id, suggested))

        # Merge device_updates: one entry per device_id (merge area_id and name_by_user)
        seen_dev = {}
        for did, aid, nb in device_updates:
            if did not in seen_dev:
                seen_dev[did] = (aid, nb)
            else:
                prev_aid, prev_nb = seen_dev[did]
                seen_dev[did] = (aid or prev_aid, nb or prev_nb)
        device_updates = [
            (did, aid, nb) for did, (aid, nb) in seen_dev.items()
        ]

        # With force_all, also assign area to devices that have none (try matching from entity_id)
        if force_all and area_id_by_name:
            for device in devices:
                device_id = device["id"]
                if device_id in kasa_skipped_devices:
                    continue
                d_area = device.get("area_id")
                if d_area:
                    continue
                dev_entities = entities_by_device.get(device_id, [])
                entity_names = [
                    e.get("name")
                    or e.get("original_name")
                    or e.get("entity_id", "").split(".")[-1]
                    for e in dev_entities
                ]
                suggested_area = match_area_for_device(
                    device.get("name_by_user") or device.get("name") or "",
                    entity_names,
                    area_id_by_name,
                )
                if not suggested_area and dev_entities:
                    # Try matching from first entity_id only (e.g. light.mark_s_fan_lights -> mark)
                    first_id = dev_entities[0].get("entity_id", "")
                    suffix = first_id.split(".")[-1].lower()
                    for area_name, area_id in area_id_by_name.items():
                        an = normalize(area_name)
                        if an in suffix or any(
                            part in suffix
                            for part in an.replace("'", " ").split()
                            if len(part) >= 4
                        ):
                            suggested_area = area_id
                            break
                if suggested_area:
                    device_updates.append(
                        (device_id, suggested_area, None)
                    )
            seen_dev = {}
            for did, aid, nb in device_updates:
                if did not in seen_dev:
                    seen_dev[did] = (aid, nb)
                else:
                    prev_aid, prev_nb = seen_dev[did]
                    seen_dev[did] = (aid or prev_aid, nb or prev_nb)
            device_updates = [
                (did, aid, nb) for did, (aid, nb) in seen_dev.items()
            ]

        device_ids_being_updated = {d[0] for d in device_updates}
        no_area_after = [
            d["id"]
            for d in devices
            if not d.get("area_id")
            and d["id"] not in kasa_skipped_devices
            and d["id"] not in device_ids_being_updated
        ]
        if no_area_after:
            print(
                f"Devices still with no area (no match): {len(no_area_after)}"
            )

        print(
            f"\nKasa skipped: {len(kasa_skipped_devices)} devices, {len(kasa_skipped_entities)} entities"
        )
        print(f"Device updates (area/name): {len(device_updates)}")
        print(f"Entity name updates: {len(entity_updates)}")

        if dry_run:
            print("\n--- DRY RUN: no changes written ---")
            if device_updates:
                print("\nPlanned device updates (area_id / name_by_user):")
                for device_id, area_id, name_by_user in device_updates:
                    area_name = next(
                        (
                            n
                            for n, aid in area_id_by_name.items()
                            if aid == area_id
                        ),
                        area_id or "",
                    )
                    print(
                        f"  {device_id} -> area={area_name!r} ({area_id}), name_by_user={name_by_user!r}"
                    )
            if entity_updates:
                print("\nPlanned entity name updates:")
                for entity_id, name in entity_updates:
                    print(f"  {entity_id} -> {name!r}")
            print(
                "\nRun without --dry-run to apply. You will be asked to confirm."
            )
            return

        if device_updates or entity_updates:
            try:
                reply = (
                    input(
                        f"\nApply {len(device_updates)} device update(s) and {len(entity_updates)} entity name(s)? [y/N]: "
                    )
                    .strip()
                    .lower()
                )
            except EOFError:
                reply = "n"
            if reply not in ("y", "yes"):
                print("Aborted. No changes made.")
                return

        # Apply device updates
        for device_id, area_id, name_by_user in device_updates:
            msg = {
                "id": next_id(),
                "type": "config/device_registry/update",
                "device_id": device_id,
                "area_id": area_id,
            }
            if name_by_user:
                msg["name_by_user"] = name_by_user
            try:
                r = await send_recv(msg)
                if not r.get("success", True):
                    print(f"  Device update failed: {r}")
            except Exception as ex:
                print(f"  Device {device_id}: {ex}")

        # Apply entity updates
        for entity_id, name in entity_updates:
            try:
                r = await send_recv(
                    {
                        "id": next_id(),
                        "type": "config/entity_registry/update",
                        "entity_id": entity_id,
                        "name": name,
                    }
                )
                if not r.get("success", True):
                    print(f"  Entity update failed: {entity_id} {r}")
            except Exception as ex:
                print(f"  Entity {entity_id}: {ex}")

        print("\nDone.")
        print(
            f"Summary: {len(device_updates)} devices updated (area/name), {len(entity_updates)} entities renamed."
        )
        print(
            f"Skipped (Kasa duplicate/unnamed): {len(kasa_skipped_devices)} devices, {len(kasa_skipped_entities)} entities."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Assign HA devices to areas and set names (convention: Room + Fixture + Description)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be updated; do not write to Home Assistant.",
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Update every entity to convention name and try to assign area to every device.",
    )
    args = parser.parse_args()
    if not HA_TOKEN and not REFRESH_TOKEN:
        print(
            "Error: Set HA_TOKEN (long-lived) or REFRESH_TOKEN in your environment (e.g. from .cursor/rules/credentials.mdc, which is gitignored).",
            file=sys.stderr,
        )
        sys.exit(1)
    asyncio.run(run(dry_run=args.dry_run, force_all=args.force_all))
