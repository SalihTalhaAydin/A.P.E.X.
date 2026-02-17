# Broadlink e-Control → Home Assistant Import

Transfer IR/RF codes from the Broadlink app into Home Assistant so Apex can control them.

## Step 1: Export from e-Control (on your phone)

1. Open the **Broadlink e-Control** app
2. Menu (≡) → **Share** → **Share to other phones in WLAN**
3. This creates 3 files. Copy them to this folder:
   - **Android**: `/broadlink/newremote/SharedData/` (connect phone via USB, browse)
   - Or use the share/export if your app saves to Downloads

Files needed: `jsonSubIr`, `jsonButton`, `jsonIrCode`

## Step 2: Dump codes

```bash
cd scripts/broadlink_import
python get_broadlink_shared_data.py
```

Pick the accessory (Projector, Curtain, etc.) by ID. Output: `Projector.txt` (or similar).

For RF switches (TC2) that need code duplication:
```bash
python get_broadlink_shared_data.py 5 --repeat 2
```

## Step 3: Generate HA scripts

```bash
python generate_ha_scripts.py Projector.txt
```

Use `--remote` if your Broadlink remote has a different entity:

```bash
python generate_ha_scripts.py Projector.txt --remote remote.first_floor_remote
```

## Step 4: Add to Home Assistant

Copy the generated YAML into **Settings → Automations & Scenes → Scripts**, or append to `scripts.yaml` and restart HA.

Then Apex can run them: *"Turn on projector"*, *"Close curtains"*.
