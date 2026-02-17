#!/usr/bin/env python3
"""
Dump IR/RF codes from Broadlink e-Control "SharedData" export.

NO ROOT REQUIRED. Export from the e-Control app first:

  1. Open e-Control app
  2. Menu → Share → Share to other phones in WLAN
  3. Copy the 3 files (jsonSubIr, jsonButton, jsonIrCode) from your phone
     Android: /broadlink/newremote/SharedData/
     to this script's directory (scripts/broadlink_import/)

Usage:
  cd scripts/broadlink_import
  python get_broadlink_shared_data.py              # interactive: pick accessory
  python get_broadlink_shared_data.py 5             # pick accessory ID 5
  python get_broadlink_shared_data.py 5 --repeat 2  # duplicate RF code 2x (for TC2 etc)
"""

import json
import base64
import sys
import os
from typing import Union

# Script dir = where jsonSubIr, jsonButton, jsonIrCode must live
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_json(name: str) -> Union[dict, list]:
    path = os.path.join(SCRIPT_DIR, name)
    if not os.path.exists(path):
        print(f"Missing {name}. Put it in {SCRIPT_DIR}")
        print("  Get it from e-Control: Share → Share to other phones in WLAN")
        sys.exit(1)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def main() -> None:
    repeat = 1
    if "--repeat" in sys.argv:
        idx = sys.argv.index("--repeat")
        repeat = int(sys.argv[idx + 1])
        sys.argv = [a for i, a in enumerate(sys.argv) if i not in (idx, idx + 1)]

    accessory_id = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        accessory_id = int(sys.argv[1])

    json_sub = load_json("jsonSubIr")
    if not isinstance(json_sub, list):
        json_sub = [json_sub]

    print("Available accessories:")
    for item in json_sub:
        iid = item.get("id", item.get("subIRId", "?"))
        name = item.get("name", "?")
        print(f"  ID: {iid} | Name: {name}")

    if accessory_id is None:
        try:
            accessory_id = int(input("\nSelect accessory ID: "))
        except (ValueError, EOFError):
            sys.exit(1)

    selected = None
    for item in json_sub:
        if item.get("id", item.get("subIRId")) == accessory_id:
            selected = item
            break
    if not selected:
        print(f"Accessory ID {accessory_id} not found")
        sys.exit(1)

    accessory_name = selected.get("name", "unknown").replace("/", "-").replace(" ", "_")
    print(f"[+] Selected: {accessory_name}")

    json_btn = load_json("jsonButton")
    if not isinstance(json_btn, list):
        json_btn = [json_btn]

    button_ids = []
    button_names = []
    for b in json_btn:
        if b.get("subIRId") == accessory_id:
            button_ids.append(b["id"])
            button_names.append(b.get("name", "unknown"))

    json_code = load_json("jsonIrCode")
    if not isinstance(json_code, list):
        json_code = [json_code]

    out_path = os.path.join(SCRIPT_DIR, f"{accessory_name}.txt")
    results = []

    with open(out_path, "w", encoding="utf-8") as f:
        for code_entry in json_code:
            bid = code_entry.get("buttonId")
            if bid not in button_ids:
                continue
            j = button_ids.index(bid)
            btn_name = button_names[j]

            raw = code_entry.get("code", [])
            if isinstance(raw, str):
                raw = [ord(c) for c in raw]
            hex_str = "".join(f"{x & 0xff:02x}" for x in raw)
            hex_str = hex_str * repeat  # for TC2 RF switches that need duplication

            try:
                b64 = base64.b64encode(bytes.fromhex(hex_str)).decode()
            except Exception:
                b64 = "(invalid hex)"

            hex_preview = hex_str[:48] + "..." if len(hex_str) > 48 else hex_str
            line = f"Button: {btn_name} | Hex: {hex_preview} | Base64: {b64}\n"
            f.write(line)
            results.append({"name": btn_name, "hex": hex_str, "base64": b64})

        f.write("\n# HA format (use with remote.send_command):\n")
        for r in results:
            f.write(f"# {r['name']}: b64:{r['base64']}\n")

    print(f"[+] Dumped {len(results)} codes to {out_path}")
    print("\nNext: run generate_ha_scripts.py to create Home Assistant script YAML")


if __name__ == "__main__":
    main()
