# CycleKernel Master — Ghost Colony v4.0

Single coherent application merging evolutionary stages 1–9 into one deployable stack.

## Quick start

```bash
cd master
docker compose up --build
```

| Service | Port | Purpose |
|---------|------|--------|
| web | 8080 | Sentience HUD + control plane |
| orchestrator | 8100 | Pipeline API |
| cognitive-bridge | 8090 | Mood / trait engine |
| terminal-runtime | 8200 | Artifact execution sandbox |

## Core API

```http
POST /v1/run
{ "goal": "your objective", "auto_execute": true }
```

Full source lives under `master/` in this repository and in the project artifacts folder.
