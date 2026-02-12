# Device Naming Convention

Apex expects smart home device names to follow a consistent pattern so it can understand "the kitchen floor lamp" or "living room ceiling" reliably. Apply this convention in Home Assistant so voice and chat commands map correctly.

## Pattern: Room + Fixture/Level + Description

| Part | Meaning | Examples |
|------|--------|----------|
| **Room** | Area/room name | Living Room, Kitchen, Bedroom, Office |
| **Fixture / Level** | Where or what kind of fixture | Ceiling, Floor, Desk, Wall, Bedside |
| **Description** | What it is / does | Lamp, Switch, Blinds, Fan, Thermostat |

## Friendly name (display name in HA)

Use **Title Case**, same order: Room, then Fixture/Level, then Description.

Examples:

- Living Room Ceiling Lamp  
- Kitchen Floor Lamp Switch  
- Bedroom Ceiling  
- Office Desk Lamp  
- Living Room Blinds  
- Garage Door  

## Entity ID (when you can set it)

Use **snake_case**, same order: `room_fixture_description`.

Examples:

- `light.living_room_ceiling_main`  
- `switch.kitchen_floor_lamp`  
- `cover.living_room_blinds`  
- `fan.bedroom_ceiling`  
- `climate.living_room_thermostat`  

Many entity IDs are set by integrations and cannot be changed. When that happens, at least set the **friendly name** and assign the device to an **area**.

## How to apply in Home Assistant

1. **Set the friendly name**  
   Go to **Settings → Devices & Services → [your device] → Entities**. Open an entity and set **Name** to the convention (e.g. "Living Room Ceiling Lamp"). This is what Apex sees when listing or confirming state.

2. **Assign the device to an area**  
   In **Settings → Areas**, create or edit areas (Living Room, Kitchen, etc.). For each device, assign it to the correct area. This keeps "room" consistent and helps with "turn off all kitchen lights" style commands.

3. **Entity ID**  
   For helpers or entities you create, use the snake_case pattern when naming the entity ID. For integration-created entities, leave the entity ID as is and rely on friendly name + area.

## Summary

- **Friendly name**: "Living Room Ceiling Lamp" (Title Case).  
- **Entity ID** (when editable): `living_room_ceiling_lamp` (snake_case).  
- **Area**: Always assign each device to an area so "room" is clear.

After updating names and areas in HA, Apex will use the same convention in prompts and tool examples, so voice and chat will align with your device list.

## Applying updates with the script (optional)

From the repo root you can use the helper script to assign devices to areas and set entity/device names in bulk:

1. **Preview (no changes)**  
   Run with `--dry-run` to see exactly which devices would get an area and which entities would be renamed. Nothing is written to Home Assistant. Put `HA_URL`, `HA_TOKEN` or `REFRESH_TOKEN` in `.env` at repo root (see `.env.example`); the script loads `.env` automatically.
   ```bash
   python scripts/ha_assign_devices.py --dry-run
   ```

2. **Apply**  
   Run without `--dry-run`. The script will show the same summary and ask for confirmation (`Apply ... ? [y/N]`) before making any changes. Only after you answer `y` will it call the Home Assistant WebSocket API to update the device registry (areas) and entity registry (names).

Requires: `pip install websockets`, and `HA_URL` + `REFRESH_TOKEN` (or `HA_TOKEN`) in `.env` (see `.env.example`). The script uses your existing area names to match devices to areas; entity names are suggested from the entity ID (snake_case → Title Case) per the convention above.
