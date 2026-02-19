# Apex Brain

**J.A.R.V.I.S. for your smart home.**

Apex Brain is a personal AI assistant that runs as a Home Assistant add-on. It has persistent memory, semantic knowledge, and full unrestricted control over every device and service in your home.

---

## Documentation

!!! tip "New here?"
    Start with [VISION](VISION.md) for the big picture, then [WORKFLOW](WORKFLOW.md) for how we develop.

| | |
|---|---|
| [Vision](VISION.md) | What we're building and why. The Jarvis Standard scorecard. |
| [Architecture](ARCHITECTURE.md) | How the system works, data flows, and the Generic Tools redesign. |
| [Roadmap](ROADMAP.md) | Everything planned — Phase 0 through Phase 5. The single source of truth. |
| [Voice Pipeline](VOICE_PIPELINE.md) | Hardware options, STT/TTS, latency targets, and setup guide. |
| [Workflow](WORKFLOW.md) | How every AI session should operate: Evaluate → Implement → Validate. |

---

## Current State

**Version:** 0.5.2 — Deployed on Home Assistant OS, Crystal Lake IL

| Metric | Value |
|--------|-------|
| HA entities under management | 347 |
| Service domains | 64 |
| Registered tools | 60+ |
| Test suite | 117 tests passing |
| Test coverage | 34% |
| Jarvis score | 7.5 / 10 → target 9.5 / 10 |

---

## Quick Start

!!! note "Local development"
    ```bash
    cd apex_brain
    pip install -r requirements.txt
    cp ../.env.example .env
    python -m brain.server
    ```

!!! note "View these docs locally"
    Run `./scripts/serve-docs.sh` or:

    ```bash
    pip install -r requirements-docs.txt   # Zensical — Material team's MkDocs successor
    zensical serve
    # Open http://127.0.0.1:8000
    ```

---

## Next Up

The active sprint is **Phase 0: Stabilize**. See [Roadmap](ROADMAP.md) for details.

1. Fix hardcoded `mobile_app_salih_iphone` in `notify.py`
2. Sync `config.yaml` default model with `config.py`
3. Bump test coverage to 50%+ on critical paths
4. Vacuum tool: read entity names from HA dynamically (fix name/context confusion)
