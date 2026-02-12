# HA Device Setup Checklist

Use this when adding new smart home devices to Home Assistant. Prefer **Wi‑Fi or Bluetooth** devices (no Zigbee dongle in use). After adding devices, assign areas and friendly names per the convention below.

## Naming and areas

- **Convention**: [Room] [Fixture/Level] [Description] — see [device-naming.md](device-naming.md).
- **Friendly name**: Title Case (e.g. "Bedroom Ceiling Left", "Alena Office Plug").
- **Area**: Assign every device to an area in **Settings → Areas** so room-based commands work.
- **Bulk apply (optional)**: From repo root, run `python scripts/ha_assign_devices.py --dry-run` to preview area/name updates, then run without `--dry-run` and confirm to apply. Requires `HA_URL` and `REFRESH_TOKEN` (or `HA_TOKEN`) in the environment.

---

## Device list (integrations and naming)

| Device | Integration / protocol | Naming example |
|--------|-------------------------|----------------|
| 2 Sengled bedroom lights | Sengled (Wi‑Fi models); add "Sengled" in HA | Bedroom Ceiling Left, Bedroom Ceiling Right (or Bedside/Desk) |
| IKEA closet LED light bars | IKEA Dirigera hub + IKEA Smart Home in HA (Wi‑Fi path) | Closet LED Bar, Closet Shelf Light |
| Hampton Bay smart plug (Alena's office) | Tuya or Smart Life (Wi‑Fi) | Alena Office Plug, Office Desk Plug |
| All Echo devices | Alexa Smart Home / Amazon Alexa | Living Room Echo, Bedroom Echo Dot |
| All temperature sensors | Wi‑Fi or Bluetooth (Tuya, BLE, etc.) | Living Room Temperature, Bedroom Temperature |
| Thermostat (Google Nest) | Google Nest (SDM API); see [nest-setup.md](nest-setup.md) for full steps | Hallway Thermostat, Living Room Thermostat |
| BroadLink RM4 Pro | Broadlink | Universal Remote RM4 Pro |

**RM4 Pro (IR/RF)**: Use for projector (IR), upstairs fan (IR/RF), curtains (IR/RF), laundry light remote (IR/RF). In HA: **Developer Tools → Services → `remote.learn_command`**; choose IR or RF, then press the button on the original remote. Create **scripts** or **buttons** for each learned command so Apex can call them via `script.turn_on` or `button.press`.

---

## Integrate (after devices are in HA)

| Item | Approach |
|------|----------|
| Fan control | Learn fan remote codes on RM4 Pro (RF or IR); create scripts/buttons. |
| Projector | Learn projector IR codes on RM4 Pro; create "Cinema – projector on" style scripts. |
| Curtains | Learn curtain remote (IR/RF) on RM4 Pro, or add curtain integration if Wi‑Fi/Zigbee motor. |
| Laundry room light remote | Learn remote on RM4 Pro, or use existing smart light entity if already in HA. |
| Basement smart lights | Add Wi‑Fi (or Bluetooth) lights; assign to Basement area and friendly names. |

---

## Zigbee (skip for now)

No Zigbee dongle in use. Use Wi‑Fi/Bluetooth device options above. If you add a Zigbee coordinator later (e.g. Sonoff Zigbee 3.0 USB Dongle, ConBee II, SkyConnect), add the **ZHA** integration in HA and pair Zigbee devices from this list as needed.
