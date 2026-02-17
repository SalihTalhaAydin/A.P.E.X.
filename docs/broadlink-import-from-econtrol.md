# Import Broadlink Codes from e-Control to Home Assistant

You’ve learned IR/RF codes in the Broadlink e-Control app. This guide transfers them into Home Assistant so Apex can control projector, curtains, fan, etc., without re-learning each button.

> **Prefer the easier path:** See [broadlink-easy-setup.md](broadlink-easy-setup.md) — SmartIR (pre-made codes) or HA learn (no app).

## Overview

| Step | Where | What |
|------|-------|------|
| 1 | e-Control app (phone) | Share → Share to other phones in WLAN |
| 2 | Your computer | Copy 3 JSON files to `scripts/broadlink_import/` |
| 3 | Terminal | Run `get_broadlink_shared_data.py` → pick accessory |
| 4 | Terminal | Run `generate_ha_scripts.py` → get YAML |
| 5 | Home Assistant | Paste YAML into Scripts, restart |

## Step 1: Export from e-Control

1. Open **Broadlink e-Control** on your phone.
2. Go to menu (≡) → **Share** → **Share to other phones in WLAN**.
3. Confirm the share; this creates the export files.

## Step 2: Copy the 3 files

You need:
- `jsonSubIr`
- `jsonButton`  
- `jsonIrCode`

**Android:** Connect the phone via USB and browse to:
```
/broadlink/newremote/SharedData/
```
(or `/sdcard/broadlink/newremote/SharedData/`)

Copy the 3 files into:
```
A.P.E.X./scripts/broadlink_import/
```

**iPhone:** Use iBackup Viewer or a similar tool to export the e-Control app data. See the [original project](https://github.com/NightRang3r/Broadlink-e-control-db-dump) for iOS instructions.

## Step 3: Dump codes for your accessory

```bash
cd scripts/broadlink_import
python get_broadlink_shared_data.py
```

The script lists your remotes (Projector, Curtain, TV, etc.). Enter the ID of the one to export, e.g. `5`.

Output: `Projector.txt` (or `Curtain.txt`, etc.) with IR/RF codes.

**RF switches (TC2):** Some need the same code sent multiple times:
```bash
python get_broadlink_shared_data.py 5 --repeat 2
```

## Step 4: Generate Home Assistant script YAML

```bash
python generate_ha_scripts.py Projector.txt
```

Use your Broadlink remote entity (from HA Developer Tools → States):
```bash
python generate_ha_scripts.py Projector.txt --remote remote.first_floor_remote
```

The script prints YAML you can copy.

## Step 5: Add scripts to Home Assistant

1. Go to **Settings → Automations & Scenes → Scripts**.
2. Click **+ Add script** (or use **⋮ → Edit in YAML** if you use `scripts.yaml`).
3. Paste the generated YAML.
4. Restart Home Assistant.

## After setup

Apex can turn scripts on via voice or chat: *"Turn on projector"*, *"Close the curtains"*, *"Run cinema mode"*.

Use `list_entities(domain="script")` in Apex to see available scripts.
