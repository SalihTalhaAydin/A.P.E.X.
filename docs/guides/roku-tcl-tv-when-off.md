# Roku / TCL TV control when off

Roku TVs (including TCL with Roku) often enter a **low-power standby** when "off." In that state they can stop responding to network commands from Home Assistant. This document explains why and how to improve control.

## Why it happens

- In standby, the TV may drop network connectivity or stop answering HTTP/ECP requests.
- Wake-on-LAN is often unreliable on Roku TVs.
- Until the TV is woken, HA (and thus Apex Brain) has nothing to talk to.

## TV and Home Assistant setup

To maximize the chance that Apex can wake and control your TV:

1. **Static IP** – Assign a static IP for the Roku/TCL TV so HA always talks to the same host.
2. **Network access** – On the TV: Settings → System → Advanced → **Control by mobile apps** → **Network access** = On.
3. **Fast TV Start** – Settings → System → Power → **Fast TV Start**  
   - When enabled, the TV can keep network connectivity in standby so HA can wake it.  
   - If the TV still doesn’t wake reliably, try **disabling** Fast TV Start (firmware behavior varies).
4. **HA Roku integration** – Ensure the **Roku** integration is set up and the entity is a `media_player` (and optionally a `remote`) so `media_player.turn_on` is available.

## Using Apex to turn the TV on

Apex Brain can turn the TV on via `control_media` with action `turn_on`. Use:

- **"Turn on the living room TV"** → `control_media(entity_id, "turn_on")`
- **"Play something on the TV"** (TV off) → Turn on first with `control_media(entity_id, "turn_on")`, then play/volume as needed.
