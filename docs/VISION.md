# Apex Brain -- Product Vision

## The Vision

Apex is J.A.R.V.I.S. for the smart home.

Not a chatbot. Not a voice remote control. Not another "hey assistant, turn off the lights" interface bolted onto a dashboard. Apex Brain is a genuine intelligent home companion -- an AI that **knows** you, **anticipates** your needs, and **acts** autonomously on your behalf.

The goal is 100% AI capability over the home. No artificial restrictions. No hardcoded limits. Full autonomy. If Home Assistant can do it, Apex can do it -- and it should figure out *when* to do it without being asked.

---

## Core Principles

### 1. Proactive, Not Reactive

Jarvis speaks first when it matters. A truly intelligent assistant does not wait to be summoned for every interaction. It notices the temperature dropping, the calendar conflict, the door left unlocked at midnight -- and it acts. The shift from "command and response" to "awareness and initiative" is what separates an assistant from a companion.

### 2. Infinite Capability

No hardcoded tool list should define the boundaries of what Apex can do. The AI must be able to call **any** Home Assistant service dynamically -- lights, locks, climate, media, cameras, custom integrations, third-party services. If a new device appears on the network tomorrow, Apex should be able to control it tomorrow. The architecture must treat capability as unbounded.

### 3. Persistent Memory

Apex remembers. Not just within a conversation, but across days, weeks, and months. It knows your preferred wake-up temperature, that you hate overhead lights in the evening, that Thursday is trash night, and that your partner prefers the thermostat two degrees warmer. Memory is what transforms a stateless tool into something that feels like it genuinely knows you.

### 4. Natural Interaction

Voice-first, conversational, personality-driven. Apex should feel like talking to someone, not issuing commands to a machine. It has a consistent persona. It uses natural language. It can handle ambiguity, follow-up questions, and context shifts the way a human would. The interaction model is dialogue, not syntax.

### 5. Privacy-First

All core processing can run locally. Speech-to-text, text-to-speech, wake word detection, and inference can all be handled on-premises. Cloud services are optional enhancements, never requirements. Your home intelligence should not depend on someone else's servers, and your conversations should not leave your network unless you choose otherwise.

---

## The Jarvis Standard

This scorecard defines what "Jarvis-level" means in concrete, measurable terms. Each category is rated on a 10-point scale. The gap between current state and target is the roadmap.

| Category | Current | Target | Gap |
|---|---|---|---|
| Personality and Persona | 9.5 / 10 | 10 / 10 | Minor polish -- tone consistency across edge cases |
| Persistent Memory | 9.5 / 10 | 10 / 10 | Fact aging, confidence decay, per-user memory isolation |
| Smart Home Control | 9 / 10 | 10 / 10 | Migrate to fully generic service-call tools, remove hardcoded tool wrappers |
| Context Awareness | 9 / 10 | 10 / 10 | Activity mode detection, room occupancy awareness, time-of-day behavioral shifts |
| Proactive Behavior | 5 / 10 | 9 / 10 | Event-driven scheduler, anomaly alerts, morning/evening briefings, unsolicited suggestions |
| Voice Pipeline | 3 / 10 | 9 / 10 | Full Wyoming protocol integration, local STT/TTS, wake word, speaker zones |
| Scheduled Actions | 2 / 10 | 9 / 10 | Natural-language reminders, timed actions, recurring tasks, countdown timers |
| Multi-User Support | 3 / 10 | 8 / 10 | Per-person fact stores, voice identification, personalized responses and preferences |
| Test Coverage | 34% | 80% | Integration tests, HA API mocking, end-to-end conversation tests |
| **Overall Jarvis Score** | **7.5 / 10** | **9.5 / 10** | |

The overall score is not an average. It is a holistic assessment of how close the system feels to a real Jarvis experience. A perfect 10 in memory means nothing if the assistant never speaks unless spoken to. The categories are interdependent -- proactive behavior requires context awareness, which requires memory, which requires multi-user support to be truly personal.

---

## Current State (v0.5.0)

Apex Brain today is a working, deployed system with real capability:

- **Home Assistant integration**: 347 entities, 64 service domains, 263 services under active management
- **Tool surface**: 26+ tools exposing 40+ functions covering lights, climate, locks, media, vacuums, calendars, notifications, scripts, automations, and more
- **Test suite**: 112 tests (111 passing, 1 failing), 34% code coverage
- **Persistent memory**: Semantic vector search over stored facts, preferences, and conversation history
- **Dynamic system prompt**: Rebuilt every turn with current entity states, user facts, time context, and conversation history
- **Anti-confabulation detection**: Validates claims against actual HA state to prevent hallucinated device status
- **OpenAI-compatible API**: Drop-in replacement endpoint enabling native integration with Home Assistant voice pipelines

The foundation is solid. The architecture is right. What remains is filling the gaps identified in the Jarvis Standard -- primarily proactive behavior, voice pipeline, scheduled actions, and multi-user support.

---

## What Success Looks Like

These are not hypothetical features. These are the concrete scenarios that define "done."

**Morning awareness.** You walk into the kitchen at 6:45am. Without being prompted, Apex speaks through the kitchen speaker: "Good morning, sir. It is 28 degrees outside and clear. Your 9 o'clock meeting with the engineering team is still on. I have started the coffee maker and set the kitchen lights to your morning preference."

**Natural reminders.** "Remind me to take out the trash at 7pm." No configuration screen. No app. Just a sentence. At 7pm, Apex announces through the nearest speaker: "Sir, it is 7 o'clock. You asked me to remind you about the trash."

**Anomaly detection.** At 3:12am, the front door motion sensor triggers. Apex evaluates context: no one is scheduled to be awake, no alarms are set for early morning. It announces quietly through the bedroom speaker: "Sir, I have detected motion at the front door. The camera shows no recognized person. Would you like me to activate the exterior lights and send an alert?"

**Learned preferences.** Apex knows that you prefer 72 degrees in the living room during the day but 68 at night. It knows your partner prefers 70 during the day. When both of you are home, it compromises to 71. None of this was explicitly programmed -- it was learned from corrections and feedback over weeks.

**Multi-room presence.** "Play my dinner playlist" works because Apex knows which room you are in, which speakers are in that room, and what your dinner playlist is. No room name required. No service name required. Context handles it.

**Family recognition.** Your partner says "turn the lights to my reading mode." Apex recognizes a different voice, retrieves that person's preferences, and sets the lights accordingly -- different from what it would do for you.

---

## Non-Goals

These items are explicitly out of scope for the current roadmap. They may be revisited in the future, but they are not part of the Jarvis Standard being pursued now.

- **Mobile application.** The Home Assistant Companion app already provides mobile access. Building a separate app would duplicate effort without advancing the core vision.
- **Custom hardware.** Apex runs on commodity hardware -- any machine that can run Home Assistant. Designing or manufacturing dedicated hardware is not part of this project.
- **Cloud dependency.** Apex must function fully on a local network with no internet connection. Cloud-based LLMs, cloud TTS, and cloud STT may be used as optional enhancements for quality, but the system must degrade gracefully to local alternatives, never fail entirely.

---

## Closing

The distance between a smart home and an intelligent home is not more devices or more automations. It is an AI layer that understands intent, remembers context, and takes initiative. That is what Apex Brain is building.

The foundation exists. The architecture is sound. The path from 7.5 to 9.5 is clear. What remains is execution.
