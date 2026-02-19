# Broadlink: The Easy Way

**Goal:** Control projector, curtains, fan via Apex. Skip the complicated stuff.

---

## Option A: Pre-made codes (no learning)

If your device is common, someone may have already learned the codes. **No button pressing. No export. No app.**

### 1. Install SmartIR

**Option 1a – HACS (recommended):**

1. **HACS** → Integrations → ⋮ menu → **Custom repositories** → Add `https://github.com/smartHomeHub/SmartIR` → Category: Integration
2. **HACS** → Integrations → search **SmartIR** → Download
3. Restart HA

**Option 1b – One command (HA Terminal add-on or SSH):**

1. Open **Terminal** add-on (or SSH into HA)
2. Paste and run:

```sh
cd /config && mkdir -p custom_components && cd /tmp && curl -sSL https://github.com/smartHomeHub/SmartIR/archive/refs/tags/1.17.12.tar.gz -o s.tar.gz && tar xzf s.tar.gz && rm -rf /config/custom_components/smartir && mv SmartIR-1.17.12/custom_components/smartir /config/custom_components/ && rm -rf SmartIR-1.17.12 s.tar.gz && echo "Done! Add smartir: to configuration.yaml and restart HA"
```

3. Add `smartir:` to `configuration.yaml` (Settings → System → Configuration → Edit Configuration YAML)
4. Restart HA

### 2. Check if your device is supported

Browse: [SmartIR Device Codes](https://github.com/smartHomeHub/SmartIR/tree/master/codes)

- **Climate** (AC): [climate/](https://github.com/smartHomeHub/SmartIR/tree/master/codes/climate)
- **Fan**: [fan/](https://github.com/smartHomeHub/SmartIR/tree/master/codes/fan)
- **Media** (TV, projector): [media_player/](https://github.com/smartHomeHub/SmartIR/tree/master/codes/media_player)
- **Light**: [light/](https://github.com/smartHomeHub/SmartIR/tree/master/codes/light)

Search by brand (Epson, BenQ, Optoma for projectors; Somfy, etc. for curtains).

If you find your model: follow SmartIR docs for that platform. You paste a device code, point SmartIR at your Broadlink, done.

### 3. Curtains / projectors not in the database?

SmartIR covers many devices. Curtains and odd projectors are often RF/IR and may not be in the database. Then use Option B.

---

## Option B: Learn in HA (2 minutes per button)

No app. No export. Just HA and your physical remote.

1. **Developer Tools** → **Services**
2. Service: **`remote.learn_command`**
3. Fill in:
   - `entity_id`: `remote.first_floor_remote`
   - `device`: `projector` (or `curtain`, `fan`)
   - `command`: `power` (or `open`, `close`, etc.)
4. **Call service**
5. When the Broadlink blinks, **press the button** on your physical remote
6. Done. Repeat for each button.

Create a script in HA that calls `remote.send_command` with that device/command. Apex can then trigger it.

---

## Summary

| Path | Effort | When to use |
|------|--------|-------------|
| **SmartIR + database** | ~5 min | Device is in the codes repo |
| **HA learn_command** | ~2 min per button | Device not in database, or curtains/RF |

Skip the e-Control app. Skip export scripts. Use SmartIR first; if not supported, learn in HA.
