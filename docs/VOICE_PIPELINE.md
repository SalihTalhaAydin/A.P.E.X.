# Apex Brain Voice Pipeline

> **Status:** Research / Planning
> **Last updated:** 2026-02-18

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Home Assistant Voice Pipeline](#3-home-assistant-voice-pipeline)
4. [Hardware Options](#4-hardware-options)
5. [Software Components](#5-software-components)
6. [Implementation Plan](#6-implementation-plan)
7. [Audio Routing Strategy](#7-audio-routing-strategy)
8. [Latency Considerations](#8-latency-considerations)
9. [Cost Estimates](#9-cost-estimates)

---

## 1. Overview

**Goal:** Walk into any room in the house, say **"Hey Apex"**, and have a natural, real-time conversation with the AI assistant. The response plays through the room's speakers. A full Jarvis-style experience -- always listening, always ready, room-aware, and hands-free.

Key requirements:

- **Whole-home coverage** -- microphones and speakers in every occupied room.
- **Custom wake word** -- "Hey Apex" triggers the assistant, not a generic keyword.
- **Local-first processing** -- wake word detection and as much of the pipeline as possible runs locally for speed and privacy.
- **Natural conversation** -- low latency, natural-sounding TTS voice, context-aware responses.
- **Room awareness** -- the system knows which room the request came from and routes the response back to the correct speakers.
- **Extensible** -- supports future features like voice identification, multi-room continuity, and ambient awareness.

---

## 2. Architecture

The voice pipeline is a linear chain of five components. Audio enters at the microphone and exits at the speaker, with processing at each stage.

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Microphone  │    │  Wake Word   │    │     STT      │    │  Apex Brain  │    │     TTS      │
│ (always on)  │───►│  Detection   │───►│  (Whisper)   │───►│  (Claude /   │───►│  (Piper)     │───► Speaker
│              │    │(openWakeWord)│    │              │    │   GPT-4o)    │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                         Wyoming Protocol                        /v1/chat/completions
```

**Data flow:**

1. **Microphone** -- always listening for audio input (satellite device in each room).
2. **Wake Word Detection** -- runs locally on the satellite or on the HA host. Listens for "Hey Apex". Only when detected does audio stream forward.
3. **Speech-to-Text (STT)** -- converts the spoken command into text. Can run locally (faster-whisper) or in the cloud (OpenAI Whisper API).
4. **Apex Brain** -- the LLM-powered conversation agent. Receives text, reasons over it, calls Home Assistant tools if needed, and generates a text response. Exposed via the OpenAI-compatible `/v1/chat/completions` endpoint.
5. **Text-to-Speech (TTS)** -- converts the text response into audio. Played back through the room's speaker(s).

The **Wyoming protocol** is the glue between components. It is an open, lightweight protocol designed specifically for voice assistants, and Home Assistant uses it natively.

---

## 3. Home Assistant Voice Pipeline

Home Assistant has a built-in voice pipeline system that orchestrates the entire flow from wake word to spoken response. This is the integration point for Apex Brain.

### Wyoming Protocol

Wyoming is an open protocol for voice assistant components. Each component (wake word engine, STT engine, TTS engine) runs as an independent service that speaks the Wyoming protocol. Home Assistant discovers and connects to these services automatically.

Key properties:
- Each component is a standalone process or container.
- Communication happens over TCP sockets with a simple event-based protocol.
- Components can run on the same machine as HA, on a separate server, or on satellite devices.

### Voice Pipeline

The HA Voice Pipeline is the orchestrator. It chains together:

1. **Wake word detection** -- listens for the trigger phrase.
2. **STT** -- transcribes the audio that follows the wake word.
3. **Conversation agent** -- processes the transcribed text and generates a response.
4. **TTS** -- synthesizes the response text into audio.

You can configure multiple pipelines (e.g., one per language, one for testing). Each pipeline selects which wake word engine, STT engine, conversation agent, and TTS engine to use.

### Conversation Agent Integration

This is where Apex Brain plugs in:

- Apex Brain already exposes a `/v1/chat/completions` endpoint (OpenAI-compatible API).
- The **Extended OpenAI Conversation** custom component (already configured in v0.5.0) registers Apex Brain as a conversation agent within Home Assistant.
- When the voice pipeline receives transcribed text, it forwards it to the configured conversation agent (Apex Brain), receives the text response, and passes it to TTS.

**This means no additional server-side work is needed for basic voice integration.** The pipeline already terminates at Apex Brain. The remaining work is hardware deployment, pipeline configuration, and optimization.

---

## 4. Hardware Options

### Satellite Devices (Microphone + Speaker in Each Room)

A "satellite" is a small device placed in a room that provides the microphone input and (optionally) speaker output for that room.

| Device | Mic | Speaker | Wake Word | Price | Notes |
|--------|-----|---------|-----------|-------|-------|
| **M5Stack ATOM Echo** | Yes (built-in) | Yes (tiny, low quality) | Via HA (streamed) | ~$13 | Cheapest entry point. Audio quality is mediocre but functional for testing. Flashed with ESPHome firmware. |
| **ESP32-S3-BOX-3** | Yes (dual mic array) | Yes (1W) | Local (on-device) | ~$45 | Best ESP32 option. Has a small screen for visual feedback. Dual mics improve pickup. Local wake word via ESP-SR. |
| **Raspberry Pi + USB mic + speaker** | External USB/I2S mic | External speaker/amp | Local (on-device) | ~$50+ | Most flexible. Best audio quality if paired with good hardware. Runs full Wyoming satellite software. |
| **Home Assistant Voice Preview Edition (Voice PE)** | Yes (dual mic array) | Yes (built-in) | Local (on-device) | ~$59 | Official HA hardware. Purpose-built for this use case. Best out-of-box experience. Dedicated wake word processor. |
| **Dedicated mic array + existing speakers** | Mic array only | Use TV/Sonos/etc. | Local | Varies | Best audio quality. Pair a ReSpeaker or similar mic array with existing room speakers. |

**Recommendation:**

- **For testing:** Start with 1-2 M5Stack ATOM Echo devices. They are cheap, easy to flash, and good enough to validate the full pipeline end-to-end.
- **For production:** Upgrade to **Home Assistant Voice Preview Edition** or **Raspberry Pi-based satellites** with quality USB microphones. The Voice PE is the most turnkey option. RPi satellites offer the most flexibility and best audio if you choose good mic/speaker hardware.

### Reusing Existing Speakers

Not every room needs a dedicated speaker on the satellite device. If a room already has speakers (TV, smart speaker, soundbar), TTS audio can be routed there instead.

- **TV speakers (Roku/TCL):** HA exposes these as `media_player` entities. TTS audio can be sent via the `tts.speak` or `media_player.play_media` service.
- **Amazon Echo / Alexa devices:** Can receive TTS output via the `notify.alexa_media` service (requires Alexa Media Player custom component).
- **Sonos speakers:** Native HA integration. Excellent TTS targets via `media_player.play_media`.
- **Google Home / Nest speakers:** Can receive TTS via the Google Home integration or Cast integration.
- **Any `media_player` entity:** If HA can see it as a media player, it can receive TTS audio.

**Trade-off:** Using existing room speakers gives better audio quality but adds complexity to audio routing and may introduce additional latency. Satellite-native speakers are simpler (audio stays on the device) but typically lower quality.

---

## 5. Software Components

### Wake Word Detection

The wake word engine runs continuously, listening for the trigger phrase. It must be fast, low-resource, and accurate to avoid false positives (triggering on random speech) and false negatives (missing the wake word).

| Option | Local/Cloud | Accuracy | Custom Wake Words | Resource Usage | Notes |
|--------|-------------|----------|-------------------|---------------|-------|
| **openWakeWord** | Local | Good | Yes (requires training) | Low | Default for HA. Runs on Pi-class hardware. Community-trained models available. Training a custom "Hey Apex" model requires collecting audio samples and running the training pipeline. |
| **Porcupine (Picovoice)** | Local | Excellent | Yes (easy web console) | Very Low | Free tier available. Best accuracy in testing. Custom wake words can be created via the Picovoice Console without collecting training data. |
| **snowboy** | Local | Good | Limited selection | Low | Older project, less actively maintained. Was popular before openWakeWord. |
| **microWakeWord** | Local (on-device) | Good | Limited | Minimal | Designed for ESP32 devices. Runs directly on the satellite hardware. Limited to pre-trained models. |

**Recommendation:** Start with **openWakeWord** since it is the HA default and has the best integration. Train a custom "Hey Apex" model. If accuracy is insufficient (too many false positives or missed detections), switch to **Porcupine** which offers easier custom wake word creation and generally better accuracy at the cost of a proprietary dependency.

### Speech-to-Text (STT)

The STT engine transcribes spoken audio into text. This is the most compute-intensive step if run locally.

| Option | Local/Cloud | Speed | Accuracy | Resource Usage | Notes |
|--------|-------------|-------|----------|---------------|-------|
| **faster-whisper** | Local | Fast | Excellent | Moderate-High | CTranslate2-based Whisper implementation. Significantly faster than original Whisper. Runs on CPU (slower) or GPU (fast). The recommended local option. |
| **Whisper (OpenAI API)** | Cloud | Fast | Excellent | None (cloud) | Best accuracy. Requires OpenAI API key. ~$0.006/minute of audio. Good fallback when local resources are limited. |
| **whisper.cpp** | Local | Fast | Excellent | Moderate | C/C++ port of Whisper. Lower memory usage than Python-based options. Good for resource-constrained hosts. |
| **Google Cloud STT** | Cloud | Fast | Excellent | None (cloud) | Free tier: 60 minutes/month. Excellent accuracy. Good alternative cloud option. |
| **Vosk** | Local | Fast | Good | Low | Lightweight, fully offline. Lower accuracy than Whisper-based options but very fast and resource-efficient. |
| **Home Assistant Cloud STT** | Cloud | Fast | Good | None (cloud) | Included with Nabu Casa subscription ($6.50/month). Simple setup. |

**Recommendation:** **faster-whisper** running locally on the HA host (or a dedicated NUC/Pi if the HA host is resource-constrained). Use the `base` or `small` model for a good speed/accuracy balance. The `medium` model is more accurate but slower. Fall back to the **OpenAI Whisper API** for maximum accuracy or if local compute is insufficient.

### Text-to-Speech (TTS)

The TTS engine converts the text response into spoken audio. Voice quality here is critical for the "Jarvis experience" -- a robotic or unnatural voice breaks immersion.

| Option | Local/Cloud | Quality | Speed | Cost | Notes |
|--------|-------------|---------|-------|------|-------|
| **Piper** | Local | Very Good | Fast | Free | Default for HA. Many voice models available. Quality has improved significantly. Best local option. Runs on Pi-class hardware. |
| **Google Cloud TTS** | Cloud | Excellent | Fast | ~$4/1M chars (WaveNet) | WaveNet and Neural2 voices are very natural. Good balance of quality and cost. |
| **Amazon Polly** | Cloud | Excellent | Fast | ~$4/1M chars (Neural) | Neural voices are comparable to Google. Well-integrated with AWS ecosystem. |
| **ElevenLabs** | Cloud | Exceptional | Medium | ~$5-22/month (usage tiers) | Most natural-sounding voices available. Voice cloning capability. Higher latency than other cloud options. Premium pricing. |
| **Coqui TTS** | Local | Good | Medium | Free | Open source. XTTS v2 model is good quality but more resource-intensive than Piper. |
| **Home Assistant Cloud TTS** | Cloud | Good | Fast | Included w/ Nabu Casa | Simple setup. Decent quality. Included in $6.50/month subscription. |

**Recommendation:** **Piper** for the primary local-first setup. It is fast, free, private, and quality is good enough for daily use. For a premium experience or special occasions, **ElevenLabs** provides the most natural voice. **Google Cloud TTS** (WaveNet/Neural2) is a good middle ground -- excellent quality at reasonable cost.

---

## 6. Implementation Plan

### Step 1: Server-Side (Apex Brain)

**Already complete:**
- `/v1/chat/completions` endpoint is live and OpenAI-compatible.
- Extended OpenAI Conversation integration connects HA to Apex Brain as a conversation agent.
- Tool calling (lights, climate, scripts, etc.) works through the existing tool framework.

**TODO -- Optimize for voice:**

| Task | Priority | Description |
|------|----------|-------------|
| Streaming response support | High | Enable streaming in `/v1/chat/completions` so TTS can begin synthesizing before the full response is generated. This is the single biggest latency win. |
| Room-aware context | High | Pass the originating room/area as context to the LLM. When a satellite in the bedroom triggers, Apex should know the user is in the bedroom and tailor responses accordingly (e.g., "turning off the bedroom lights" vs. "which room?"). |
| Shorter response style for voice | Medium | Voice responses should be concise. A system prompt modifier for voice-originated requests: prefer short, spoken-language answers over verbose text answers. |
| Conversation continuity | Medium | Maintain conversation context across multiple voice interactions in the same session (e.g., "turn on the lights" followed by "make them dimmer" should understand "them" refers to the lights just turned on). |
| Error handling for voice | Low | Graceful spoken error messages instead of technical error text (e.g., "Sorry, I could not reach that device" instead of a stack trace). |

### Step 2: HA Voice Pipeline Configuration

This is the core integration work. All components are configured within Home Assistant.

1. **Install the Wyoming integration** in HA (Settings > Integrations > Add Integration > Wyoming).

2. **Install and configure the STT add-on:**
   - Install the "Whisper" add-on from the HA Add-on Store (this runs faster-whisper).
   - Select the model size (`base` or `small` for speed, `medium` for accuracy).
   - The add-on exposes a Wyoming STT service automatically.

3. **Install and configure the TTS add-on:**
   - Install the "Piper" add-on from the HA Add-on Store.
   - Select a voice model (e.g., `en_US-amy-medium` or `en_US-lessac-high` for higher quality).
   - The add-on exposes a Wyoming TTS service automatically.

4. **Install and configure the wake word add-on:**
   - Install the "openWakeWord" add-on from the HA Add-on Store.
   - Configure with the default wake words initially (e.g., "ok nabu").
   - Train or obtain a custom "Hey Apex" model (see Wake Word Training section below).
   - The add-on exposes a Wyoming wake word service automatically.

5. **Create the voice pipeline:**
   - Go to Settings > Voice Assistants.
   - Create a new pipeline named "Apex Voice".
   - Set the conversation agent to **Apex Brain** (via Extended OpenAI Conversation).
   - Set STT to the Whisper add-on.
   - Set TTS to the Piper add-on.
   - Set wake word to the openWakeWord add-on.
   - Set the language to English (or as needed).

6. **Test the pipeline:**
   - Use the HA Voice Pipeline debug tool (Settings > Voice Assistants > pipeline > "Run" button).
   - Speak a command through the browser microphone and verify the full chain works.

### Step 3: Satellite Deployment

Once the pipeline is validated via the HA web interface, deploy physical satellites into rooms.

**For M5Stack ATOM Echo (ESPHome-based):**
1. Flash the ATOM Echo with the ESPHome voice assistant firmware.
   - Use the ESPHome dashboard or `esphome run` CLI.
   - The firmware config specifies the HA instance and pipeline to use.
2. Power on the device and adopt it in the ESPHome dashboard.
3. Assign the device to a room/area in HA.

**For Raspberry Pi (Wyoming satellite):**
1. Install the Wyoming Satellite software on the Pi.
   - `pip install wyoming-satellite` or use the Docker image.
2. Connect a USB microphone and speaker/DAC.
3. Configure the satellite to point at the HA instance.
4. The satellite appears in HA as a new Wyoming device.
5. Assign it to a room/area.

**For Home Assistant Voice PE:**
1. Power on the device and connect to Wi-Fi.
2. HA auto-discovers it via the Wyoming integration.
3. Assign it to a room/area.

**For all satellites:**
- Verify wake word detection triggers correctly in each room.
- Test voice commands and confirm TTS response plays back through the correct device.
- Adjust microphone sensitivity and wake word threshold as needed to avoid false positives/negatives.

### Step 4: Advanced Features (Future)

These are enhancements to pursue after the basic pipeline is stable.

| Feature | Description | Complexity |
|---------|-------------|------------|
| **Multi-room conversation continuity** | If a user starts a conversation in the kitchen and walks to the living room, the context follows them. Requires presence detection + conversation session management. | High |
| **Interrupt handling** | If the user speaks while TTS is playing, stop playback and listen to the new command. Requires barge-in support on the satellite. | Medium |
| **Ambient sound awareness** | If music is playing in a room, increase mic sensitivity or route TTS at a higher volume. Integrate with media_player state. | Medium |
| **Voice identification** | Identify who is speaking and personalize responses (e.g., different users get different calendar events). Requires speaker diarization or voiceprint matching. | High |
| **Proactive announcements** | Apex initiates speech (e.g., "Reminder: your meeting starts in 10 minutes") without a wake word trigger. Route to the room where the user is currently detected. | Medium |
| **Multi-language support** | Support wake words, STT, and TTS in multiple languages. Requires per-language pipeline configuration. | Medium |
| **Whisper mode** | Detect when the user is whispering and respond at a lower volume. Useful for nighttime commands. | Low-Medium |

---

## 7. Audio Routing Strategy

How TTS responses reach the correct speakers depends on the setup. Three strategies, from simplest to most sophisticated:

### Option A: Satellite Speaker (Simplest)

The TTS audio plays through the speaker built into (or directly connected to) the satellite device that detected the wake word.

- **Pros:** Zero configuration. Audio stays on the device. Lowest latency.
- **Cons:** Satellite speakers are typically small and low quality. Not great for music or long responses.
- **Best for:** Quick commands, confirmations ("OK, lights turned on"), rooms without other speakers.

### Option B: Room Speakers (Recommended)

The TTS audio is routed to `media_player` entities in the same HA area as the satellite. For example, if the satellite is in the "Living Room" area and there is a Sonos speaker also in "Living Room", the TTS plays through the Sonos.

- **Pros:** Much better audio quality. Uses speakers already in the room.
- **Cons:** Requires area assignment for both satellites and speakers. Slight additional latency for network audio routing. May interrupt currently playing media.
- **Best for:** Rooms with existing smart speakers, TVs, or sound systems.

**Implementation:** Use an automation or script that triggers on `assist_satellite` events, looks up the area, finds `media_player` entities in that area, and sends TTS audio to them. Alternatively, configure this in the voice pipeline settings if supported.

### Option C: Whole-Home Broadcast

TTS audio plays through all speakers simultaneously. Useful for important announcements (security alerts, timers, reminders).

- **Pros:** Guaranteed to be heard regardless of which room the user is in.
- **Cons:** Disruptive. Not appropriate for normal conversations.
- **Best for:** Alerts, alarms, broadcast announcements.

**Implementation:** Use the `tts.speak` service targeting a speaker group or call `media_player.play_media` on all `media_player` entities.

### Hybrid Approach (Recommended for Production)

Combine all three strategies:

- **Default:** Option B (room speakers) for normal interactions.
- **Fallback:** Option A (satellite speaker) if no room speakers are available.
- **Override:** Option C (whole-home) for alerts, alarms, and user-requested broadcasts.

The routing logic can live in an HA automation or be built into Apex Brain as a tool that selects the appropriate output based on the request type and room context.

---

## 8. Latency Considerations

**Target:** Less than 2 seconds from the end of the user's speech to the start of the spoken response. This is the threshold for a conversation to feel "natural" rather than sluggish.

### Component Latency Breakdown

| Component | Typical Latency | Notes |
|-----------|----------------|-------|
| Wake word detection | ~100ms | Runs locally on the satellite or HA host. Very fast. |
| Audio streaming to HA | ~50-200ms | Depends on network. Wi-Fi latency is the main variable. |
| STT (faster-whisper, local) | 200-500ms | Depends on model size and host hardware. GPU accelerates significantly. |
| STT (OpenAI Whisper API, cloud) | 500-1000ms | Network round-trip + processing. |
| Apex Brain (LLM processing) | 500-2000ms | Depends on model (Claude Sonnet is faster than Opus), prompt length, and whether tool calls are needed. Simple responses are fast; multi-tool-call responses are slower. |
| TTS (Piper, local) | 100-300ms | Very fast. Depends on voice model complexity. |
| TTS (Cloud, e.g., ElevenLabs) | 300-800ms | Network round-trip + synthesis. |
| Audio playback initiation | ~50-100ms | Time for the speaker to begin playing. |

### Estimated Total Latency

| Configuration | Estimated Total | Assessment |
|---------------|----------------|------------|
| **All local** (faster-whisper + local LLM + Piper) | ~1-2.5 seconds | Best case. Meets target for simple requests. |
| **Hybrid** (faster-whisper local + cloud LLM + Piper local) | ~1-3 seconds | Typical setup. Meets target for most requests. |
| **All cloud** (cloud STT + cloud LLM + cloud TTS) | ~1.5-4 seconds | Acceptable but noticeable. May feel slow for rapid back-and-forth. |

### Latency Optimization Strategies

1. **Streaming TTS:** Start TTS synthesis and audio playback as soon as the first sentence of the LLM response is available, rather than waiting for the complete response. This is the single biggest win -- it can cut perceived latency by 50% or more for longer responses.

2. **Smaller STT models:** Use `base` or `small` faster-whisper models for voice (they are fast enough for short commands) and reserve `medium`/`large` for scenarios requiring maximum accuracy.

3. **Faster LLM for voice:** Use a faster model (e.g., Claude Sonnet or GPT-4o-mini) for voice interactions where latency matters more than deep reasoning. Reserve Opus/GPT-4o for complex tasks initiated via text.

4. **Prewarming:** Keep the STT and TTS models loaded in memory at all times (the HA add-ons do this by default). Cold starts add seconds of latency.

5. **Local network optimization:** Ensure satellites are on a reliable Wi-Fi network (5GHz preferred). Wired Ethernet for the HA host and any dedicated STT/TTS servers.

6. **Edge wake word processing:** Run wake word detection on the satellite device itself (ESP32-S3-BOX-3 and Voice PE support this). This avoids streaming audio to HA until the wake word is confirmed, reducing unnecessary network traffic and processing.

---

## 9. Cost Estimates

### Hardware Costs (One-Time)

| Component | Cost | Quantity | Total | Notes |
|-----------|------|----------|-------|-------|
| M5Stack ATOM Echo | $13 | 2 (testing) | $26 | For initial pipeline validation |
| HA Voice Preview Edition | $59 | 3-5 (production) | $177-295 | One per main room |
| Raspberry Pi 4/5 (STT/TTS server) | $50-75 | 0-1 | $0-75 | Only if HA host can't handle STT/TTS load |
| USB microphone (for RPi satellites) | $15-30 | 0-2 | $0-60 | Only if using RPi-based satellites |
| Speakers (for RPi satellites) | $10-30 | 0-2 | $0-60 | Only if using RPi-based satellites and no existing speakers |

**Total hardware estimate:** $200-500 for a 3-5 room deployment.

### Monthly Recurring Costs

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| Cloud STT (OpenAI Whisper API) | ~$5-10 | Only if using cloud STT. Based on ~30-60 min of audio/day. |
| Cloud TTS (Google Cloud / ElevenLabs) | ~$5-20 | Only if using cloud TTS. Piper is free. |
| LLM API (Claude / GPT-4o) | ~$10-30 | Already a cost for Apex Brain regardless of voice. |
| Nabu Casa subscription (optional) | $6.50 | Includes cloud STT + TTS. Simplest cloud option. |

### Cost Scenarios

| Scenario | One-Time | Monthly | Description |
|----------|----------|---------|-------------|
| **Budget local** | ~$130 | ~$10-30 (LLM only) | 2x ATOM Echo + all local processing. LLM API is the only recurring cost. |
| **Recommended hybrid** | ~$300-400 | ~$15-40 | Voice PE satellites + local STT/TTS + cloud LLM. |
| **Premium cloud** | ~$300-400 | ~$30-70 | Voice PE satellites + cloud STT + ElevenLabs TTS + cloud LLM. Best quality, highest cost. |

---

## Appendix A: Wake Word Training (openWakeWord)

To create a custom "Hey Apex" wake word model for openWakeWord:

1. **Collect positive samples:** Record 50+ examples of different people saying "Hey Apex" in different conditions (quiet room, background noise, different distances).
2. **Collect negative samples:** Record ambient household audio (TV, music, conversation) that should NOT trigger the wake word.
3. **Use the openWakeWord training notebook:** The project provides a Google Colab notebook for training custom models.
4. **Export the model:** Output is a `.tflite` file that can be loaded into the openWakeWord HA add-on.
5. **Test and tune:** Adjust the detection threshold to balance false positive rate vs. missed detections.

Alternatively, the **Picovoice Console** (for Porcupine) allows creating custom wake words by simply typing the phrase -- no audio samples needed. This is significantly easier but ties you to the Porcupine ecosystem.

## Appendix B: Wyoming Satellite Setup (Raspberry Pi)

Minimal setup for a Raspberry Pi-based Wyoming satellite:

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv

# Create virtual environment
python3 -m venv wyoming-env
source wyoming-env/bin/activate

# Install wyoming-satellite
pip install wyoming-satellite

# Run the satellite (example with USB mic and 3.5mm speaker)
wyoming-satellite \
  --name "Living Room Satellite" \
  --uri tcp://0.0.0.0:10700 \
  --mic-command "arecord -r 16000 -c 1 -f S16_LE -t raw" \
  --snd-command "aplay -r 22050 -c 1 -f S16_LE -t raw" \
  --wake-uri tcp://HA_HOST:10400 \
  --wake-word-name "hey_apex"
```

The satellite will appear in Home Assistant as a Wyoming device. Assign it to an area and it will be part of the voice pipeline.

## Appendix C: ESPHome ATOM Echo Configuration

Minimal ESPHome YAML for the M5Stack ATOM Echo voice satellite:

```yaml
esphome:
  name: atom-echo-living-room
  friendly_name: "Living Room Voice Satellite"

esp32:
  board: m5stack-atom

# ... (standard ESPHome Wi-Fi, API, OTA config)

i2s_audio:
  - id: i2s_audio_bus
    i2s_lrclk_pin: GPIO33
    i2s_bclk_pin: GPIO19

microphone:
  - platform: i2s_audio
    id: atom_mic
    adc_type: external
    i2s_din_pin: GPIO23
    pdm: true

speaker:
  - platform: i2s_audio
    id: atom_speaker
    dac_type: external
    i2s_dout_pin: GPIO22
    mode: mono

voice_assistant:
  microphone: atom_mic
  speaker: atom_speaker
  use_wake_word: true
  on_wake_word_detected:
    - light.turn_on:
        id: led
        effect: "Listening"
  on_tts_end:
    - light.turn_off: led
```

## Appendix D: Relevant Links

- [Home Assistant Voice Documentation](https://www.home-assistant.io/voice_control/)
- [Wyoming Protocol Specification](https://github.com/rhasspy/wyoming)
- [openWakeWord GitHub](https://github.com/dscripka/openWakeWord)
- [Piper TTS GitHub](https://github.com/rhasspy/piper)
- [faster-whisper GitHub](https://github.com/SYSTRAN/faster-whisper)
- [ESPHome Voice Assistant](https://esphome.io/components/voice_assistant.html)
- [Wyoming Satellite GitHub](https://github.com/rhasspy/wyoming-satellite)
- [Picovoice Porcupine](https://picovoice.ai/platform/porcupine/)
- [Extended OpenAI Conversation](https://github.com/jekalmin/extended_openai_conversation)
- [M5Stack ATOM Echo](https://shop.m5stack.com/products/atom-echo-smart-speaker-dev-kit)
- [Home Assistant Voice Preview Edition](https://www.home-assistant.io/voice-pe/)
