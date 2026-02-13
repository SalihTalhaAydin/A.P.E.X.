# What This Repo Can Change in Home Assistant & Kasa Troubleshooting

## What in this repo can change Home Assistant

Only **one script** in this repo writes to Home Assistant:

- **[scripts/ha_assign_devices.py](../scripts/ha_assign_devices.py)**  
  When run **without** `--dry-run` and after you confirm with `y`, it:
  - **Assigns devices to areas** (e.g. device moved from "Unassigned" to "Living Room").
  - **Renames entities** (friendly names) per the device naming convention. Many Kasa devices are **skipped** from renames (model-style names like "KP115", "HS220" are left alone).

It does **not** disconnect integrations, remove devices, or change entity IDs. If devices or entity names look different from what you expect, running this script (or an agent running it) could explain it.

**Other scripts:**

- **suggest_device_names.py** — Read-only: suggests names and can write to a local file; does not change HA.
- **Apex Brain add-on** — Talks only to HA's REST API (e.g. `light.turn_on`, entity states). It does not talk to Kasa/Govee devices directly and does not cause them to drop off Wi‑Fi.

**To avoid unintended changes:** Run `ha_assign_devices.py` with **`--dry-run`** to preview changes; only run without `--dry-run` when you intend to apply and have reviewed the printed list.

---

## Kasa (TP-Link) troubleshooting checklist

Use this when Kasa lights randomly show as **unavailable** in Home Assistant or seem to disconnect (e.g. "every second some light gets disconnected"), even with extenders and devices on Wi‑Fi.

### 1. Confirm this repo is not the cause

- This repo does **not** disconnect Kasa devices. The add-on only calls HA's API; the only script that changes HA only updates areas and friendly names.
- If devices were **moved** (different area) or **renamed**, that can be from `ha_assign_devices.py`. That does not cause "unavailable" or disconnects.

### 2. Check Kasa integration and entity state in HA

- **Settings → Devices & Services** — Find the Kasa (TP-Link Smart Home) integration. Note if it's "Local" or "Cloud."
- **Developer Tools → States** — Search for `light.` and your Kasa entities. Watch which ones flip to `unavailable` (same light vs different lights each time).
- **Settings → Devices & Services → Kasa → [device] → Entities** — See if any entities are disabled or frequently unavailable.

### 3. Run the light-state diagnostic script (optional)

From the repo root, with `HA_URL` and `HA_TOKEN` (or `REFRESH_TOKEN`) set in `.env` so your machine can reach Home Assistant:

```bash
python scripts/ha_kasa_diagnostic.py
```

This lists all `light.*` entities and their state (on / off / **unavailable**), and prints a count of unavailable lights. Use it to see which entities are flapping or stuck unavailable.

### 4. Check HA logs

- **Settings → System → Logs** — Filter/search for `kasa` or `tplink`. Look for errors, "unavailable," "timeout," "disconnect," or "connection" when lights drop. That indicates whether the cause is network timeouts, discovery, or integration errors.

### 5. Network / Wi‑Fi (outside HA)

- **Stable IPs:** In your router or DHCP server, set **DHCP reservations** for each Kasa device so their IPs don't change when they roam or renew.
- **2.4 GHz and extenders:** Kasa uses 2.4 GHz. With multiple APs/extenders, devices can roam and the integration can lose them briefly. If possible, keep Kasa devices on one AP/band (e.g. dedicated 2.4 GHz SSID or reduce roaming) to see if flapping decreases.
- **Firmware:** Update Kasa device firmware in the Kasa app; newer firmware can improve stability with some routers.

### 5. Example: what showed up in HA logs (browser diagnostic)

When we opened **Settings → System → Logs** in HA, the following were relevant to Kasa/TP-Link and lights:

- **TP-Link Smart Home (ERROR, 107 times):**  
  `Error fetching 192.168.68.102 data: Unable to communicate with the device update: Unable to connect to the device: 192.168.68.102:9999: [Errno 111] Connect call failed`  
  So one Kasa device at **192.168.68.102** is not reachable on port 9999 (HA cannot talk to it). Fix: ensure that device is on and on the same network; give it a DHCP reservation; check if it's the "Mirror Lights Entrance" plug or another device at that IP.

- **config_entries (ERROR):**  
  `Setup of config entry 'Kitchen Under Cabinet Lights ES20M' for tplink integration cancelled`  
  The Kitchen Under Cabinet Lights (ES20M) config entry was cancelled; you may need to re-add that device in the Kasa/TP-Link integration if you still use it.

- **helpers/target (WARNING, 23 times):**  
  `Referenced entities light.basement_side_ceiling_lights are missing or not currently available`  
  A helper or automation references `light.basement_side_ceiling_lights`; when that entity goes unavailable, this warning appears. Fix: improve Wi‑Fi/connectivity for that light or update the helper to handle unavailable.

- **Developer Tools → States** (with filter "light"):  
  One entity seen as **unavailable** in the list: **switch.tp_link_smart_plug_4464_mirror_lights_ent** (TP-Link Smart Plug 4464 Mirror Lights Entrance). That may be the same device as 192.168.68.102 or another plug that's currently unreachable.

So the "random disconnects" are at least partly one or more specific devices (e.g. 192.168.68.102, Mirror Lights Entrance plug) that HA repeatedly cannot reach. Giving those devices a **fixed IP (DHCP reservation)** and keeping them on a stable AP may reduce flapping.

### 6. Summary of likely causes

| What you see | Likely cause | Where to look |
|--------------|--------------|----------------|
| Devices "moved" (area/name) | `ha_assign_devices.py` or manual HA changes | HA Devices & Services → Area and entity Name |
| Kasa: randomly lights go unavailable | Wi‑Fi (2.4 GHz congestion, roaming, extenders), integration timeouts, or DHCP/IP changes | HA Logs (kasa/tplink), entity states; router DHCP reservations; 2.4 GHz layout |
| Integrations "disconnecting" | Network, integration (local vs cloud), or HA/integration updates | HA Logs, integration status, entity states |
