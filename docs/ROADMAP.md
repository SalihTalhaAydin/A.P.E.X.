# Apex Brain -- Product Roadmap

> **Single source of truth** for every idea, feature, and improvement captured from our audit.
> Nothing gets lost -- if it's not here, it's not planned. Organized by phase/sprint priority.

---

## Phase 0: Stabilize (Current Sprint)

Critical fixes and test coverage gaps that must be resolved before any new feature work.

- [ ] Fix failing test: `test_settings_defaults` model default mismatch (`config.py` defaults to `gpt-4o`, test expects `claude-sonnet-4`)
- [ ] Fix hardcoded phone notification target (`mobile_app_salih_iphone` in `notify.py`) -- should be configurable via settings or auto-discovered from HA
- [ ] Sync `config.yaml` default model with `config.py` default so add-on config and code agree on the out-of-the-box model
- [ ] Bump test coverage to 50%+ on critical paths (`conversation.py`, `context_builder.py`, `fact_extractor.py`)
- [ ] Vacuum tool: read entity names from HA dynamically; fix context/name confusion when vacuums are renamed or re-paired

---

## Phase 1: Generic Tools Redesign

The most important architectural change. Replace 40+ hardcoded tools with ~5 generic power tools that let the LLM call any HA service, query any state, and discover any entity -- without needing a bespoke tool per domain.

- [ ] Implement `do()` -- generic service caller with auto-verification (call any `domain.service`, then re-read state to confirm it worked)
- [ ] Implement `query()` -- unified state reader + template evaluator (replace per-domain get_* tools with one flexible reader)
- [ ] Implement `discover()` -- unified entity/service/area/device discovery (merge list_entities, list_devices, list_areas, list_services into one tool)
- [ ] Inject HA service schemas into system prompt for AI guidance (so the model knows valid services, fields, and enums without hardcoding)
- [ ] Keep old tools as deprecated aliases during migration (backward compat -- old tool names forward to new generic tools)
- [ ] Update all tests for new tool architecture
- [ ] End-to-end integration tests (call `do()` / `query()` / `discover()` against a live HA instance and verify results)

---

## Phase 2: Proactive Intelligence

Move from reactive (user asks, Apex answers) to proactive (Apex notices things and acts or alerts).

- [ ] Background scheduler for timed actions and reminders ("remind me at 7pm to take out the trash")
- [ ] Proactive morning/evening briefings (triggered by time + presence -- "Good morning, here's your day")
- [ ] Weather alert system (freeze/storm/heat warnings --> notify + suggest actions like "close the windows" or "turn on the heater")
- [ ] Sensor watch capabilities ("tell me when the garage opens" -- subscribe to state changes and notify on match)
- [ ] Pattern learning ("you always turn on office lights at 8am" --> suggest creating an automation)
- [ ] Anomaly detection (door open at 3am --> alert + camera snapshot if available)

---

## Phase 3: Voice Pipeline

Full local voice assistant: wake word --> STT --> Apex Brain --> TTS --> speaker. No cloud dependency for the voice path.

- [ ] Wyoming satellite integration (ESP32-S3 or dedicated hardware per room)
- [ ] Wake word detection (openWakeWord -- "Hey Apex" or custom wake word)
- [ ] STT integration (faster-whisper, running locally for privacy and speed)
- [ ] TTS integration (Piper, local, natural-sounding voice)
- [ ] Room-aware audio routing (speak through the correct room's speakers based on which satellite heard the wake word)
- [ ] Multi-room announcement support ("announce dinner is ready in all rooms")
- [ ] Conversation continuity across rooms (start a conversation in the kitchen, continue it in the living room)

---

## Phase 4: Multi-User & Personalization

Apex should know who it's talking to and tailor responses, routines, and knowledge per person.

- [ ] Per-person fact storage (tie learned knowledge to HA person entities -- "Salih likes the office at 72F")
- [ ] Voice identification (speaker recognition to route conversations to the correct user profile)
- [ ] User-specific routines and preferences (different wake-up routines, notification preferences, etc.)
- [ ] Guest mode (temporary access with restricted capabilities -- no security controls, limited device access)
- [ ] Family dashboard / shared vs. personal knowledge (some facts are household-wide, others are personal)

---

## Phase 5: Advanced Intelligence

Deeper contextual awareness, energy intelligence, and long-running conversation management.

- [ ] Activity mode detection (infer "movie night", "workout", "work from home", "sleep" from sensor data and adjust environment)
- [ ] Circadian lighting integration (automatic color temperature shifts by time of day -- cool in morning, warm in evening)
- [ ] Energy cost tracking and efficiency alerts ("your HVAC used 40% more energy this week -- here's why")
- [ ] Calendar-aware prep ("meeting in 1 hour -- based on traffic, you should leave in 20 minutes")
- [ ] Shopping list integration (HA `shopping_list` domain -- add/remove/read items via conversation)
- [ ] Inter-room communication ("tell the kids dinner is ready" --> TTS announcement in specific rooms)
- [ ] Conversation summarization for long context management (compress older turns to stay within token limits without losing key info)
- [ ] Fact aging and cleanup (TTL on learned facts, periodic re-analysis to prune stale or contradicted knowledge)

---

## Backlog (Unscheduled)

Good ideas that don't yet have a home in a specific phase. Pull from here into sprints as capacity allows.

### Notifications & UI
- [ ] Rich notifications (attach camera snapshots, include action buttons for quick responses)
- [ ] Scene creation from current state ("save the current lighting as a scene called Movie Night")
- [ ] Automation templates/wizards (guided automation creation for common patterns)

### Voice & Audio
- [ ] TTS voice customization (speed, pitch, emotional tone adjustments)
- [ ] Multi-room audio sync (AirPlay/Spotify Connect coordination)

### Environmental & Health
- [ ] Carbon footprint tracking (estimate CO2 impact of energy usage)
- [ ] Air quality / pollen monitoring (integrate with outdoor AQI sensors or APIs)
- [ ] Sleep quality tracking integration (pull data from sleep sensors or wearables)

### Location & Calendar
- [ ] Geofence-triggered presets (auto away/home mode based on phone location)
- [ ] Meeting prep assistant (combine weather + traffic + prep time into a single "time to leave" notification)
- [ ] Calendar event deletion (implement the existing stub in `calendar_tool.py`)

### Infrastructure & Ops
- [ ] Persistent action traces (survive add-on restart -- store in DB instead of memory)
- [ ] Model health check on startup (verify the configured LLM endpoint is reachable before accepting conversations)
- [ ] Database cleanup/archiving job (periodic task to archive old conversations and prune the SQLite DB)

---

## Completed (Archive)

Shipped milestones for historical reference.

- [x] **v0.1.0** -- Core conversation loop + memory (SQLite-backed conversation storage, fact extraction)
- [x] **v0.2.0** -- Smart home tools (lights, climate, media player control)
- [x] **v0.3.0** -- Vacuum, calendar, weather, presence tools
- [x] **v0.4.0** -- Automations, routines, energy monitoring, security, scripts
- [x] **v0.5.0** -- J.A.R.V.I.S. personality, confabulation detection, proactive hints

---

*Last updated: 2026-02-18*
