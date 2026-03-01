#!/usr/bin/env python3
"""
Generate Home Assistant script YAML from Broadlink dump output.

Reads the .txt file produced by get_broadlink_shared_data.py and outputs
ready-to-paste YAML for Settings → Automations & Scenes → Scripts.

Usage:
  cd scripts/broadlink_import
  python generate_ha_scripts.py Projector.txt
  python generate_ha_scripts.py Projector.txt --remote remote.first_floor_remote
"""

import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_dump_file(path: str):
    """Parse dump file: 'Button: X | Hex: ... | Base64: Y' or '# Name: b64:Y'."""
    results = []
    seen = set()  # avoid dupes
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            m = re.search(
                r"Button:\s*(.+?)\s*\|\s*.*\|\s*Base64:\s*(.+)", line
            )
            if m:
                name, b64 = m.group(1).strip(), m.group(2).strip()
                key = (name, b64)
                if key not in seen:
                    seen.add(key)
                    results.append({"name": name, "base64": b64})
            else:
                m2 = re.search(r"#\s*(.+?):\s*b64:(.+)", line)
                if m2:
                    name, b64 = m2.group(1).strip(), m2.group(2).strip()
                    key = (name, b64)
                    if key not in seen:
                        seen.add(key)
                        results.append({"name": name, "base64": b64})
    return results


def slug(name: str) -> str:
    """Turn 'Volume Up' into volume_up."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python generate_ha_scripts.py <dump_file.txt> [--remote remote.first_floor_remote]"
        )
        print("  Example: python generate_ha_scripts.py Projector.txt")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.isabs(path):
        path = os.path.join(SCRIPT_DIR, path)
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    remote = "remote.first_floor_remote"
    if "--remote" in sys.argv:
        idx = sys.argv.index("--remote")
        remote = sys.argv[idx + 1]

    results = parse_dump_file(path)
    if not results:
        # Fallback: try to get base64 from # comments
        with open(path) as f:
            for line in f:
                if "b64:" in line and line.strip().startswith("#"):
                    parts = line.split("b64:", 1)
                    if len(parts) == 2:
                        name = (
                            parts[0].replace("#", "").strip().rstrip(":")
                        )
                        b64 = parts[1].strip()
                        results.append({"name": name, "base64": b64})

    if not results:
        print(
            "No codes found in file. Ensure get_broadlink_shared_data.py ran successfully."
        )
        sys.exit(1)

    basename = os.path.splitext(os.path.basename(path))[0]
    prefix = slug(basename)

    print("# Copy this into HA: Settings → Automations & Scenes → Scripts")
    print("# Or add to scripts.yaml and restart HA")
    print()
    print("script:")
    for r in results:
        script_id = f"{prefix}_{slug(r['name'])}"
        safe_name = r["name"].replace('"', '\\"')
        print(f"  {script_id}:")
        print(f'    alias: "{basename} - {r["name"]}"')
        print("    sequence:")
        print("      - service: remote.send_command")
        print("        target:")
        print(f"          entity_id: {remote}")
        print("        data:")
        print(f"          command: b64:{r['base64']}")
        print()

    print(f"# Generated {len(results)} scripts. Add to HA and restart.")


if __name__ == "__main__":
    main()
