# CognitiveBridge

LoopMem metrics arrive on a WebSocket relay. `subscribe_to_relay` connects to `WS_RELAY_URL` (fallback `RELAY_URL`, default `ws://ws-relay:8081/ws/out`) and maps each frame through `sync_state`. Dropped connections retry with exponential backoff.

The old fixed sample heartbeat runs only when `CK_SYNTHETIC=1`. `GET /health` reports `mode` as `relay` or `synthetic`.

## Environment

| Name | Default | Purpose |
| --- | --- | --- |
| `WS_RELAY_URL` | `RELAY_URL`, else `ws://ws-relay:8081/ws/out` | Relay socket |
| `CK_SYNTHETIC` | off | Emit the fixed LoopMem sample instead of connecting |
| `CK_SYNTHETIC_INTERVAL` | `5` | Seconds between synthetic samples |
| `CK_RELAY_BACKOFF_INITIAL` | `1` | First reconnect delay, seconds |
| `CK_RELAY_BACKOFF_FACTOR` | `2` | Backoff multiplier |
| `CK_RELAY_BACKOFF_MAX` | `30` | Backoff cap, seconds |
| `CK_RELAY_OPEN_TIMEOUT` | `5` | Handshake timeout, seconds |
| `CK_RELAY_MAX_FRAME_BYTES` | `65536` | Largest accepted relay frame. Exactly this size is accepted; one byte over closes the socket |
| `CK_HUD_SEND_TIMEOUT` | `0.5` | Seconds before a slow HUD client is dropped |
| `CK_EVENTS_TOKEN` | unset | Bearer token for `/events`. Unset rejects every post. Copy `.env.example` |
| `CK_EVENTS_TOKEN_PREVIOUS` | unset | Still accepted while `CK_EVENTS_TOKEN` is rotated |
| `CK_EVENTS_MAX_BYTES` | `65536` | Maximum `POST /events` body |
| `CK_EVENTS_MAX_RECENT` | `100` | In-memory ring size. Older events are dropped |

## HTTP

- `GET /health` — liveness plus mode, relay counters, and event counts
- `GET /v1/current_mood` — latest cognitive state
- `POST /events` — Fusion Bridge intake. `Authorization: Bearer <CK_EVENTS_TOKEN>` or `X-Events-Token`. The previous token is accepted until it is cleared
- `GET /events` — same credentials, returns the ring buffer
- `POST /v1/feedback` — orchestrator closed loop. Not the events intake
- `WS /ws/hud` — pushes the cognitive state to HUD clients. A client that does not read within `CK_HUD_SEND_TIMEOUT` is disconnected

The compose files start `ws-relay` and point `WS_RELAY_URL` at `ws://ws-relay:8081/ws/out`. Publish a frame with `POST /publish` on the relay, or push text frames to `/ws/in`. Subscribers that fall behind drop the oldest frame (`CK_RELAY_QUEUE_MAX`). Copy `.env.example` to `.env` (and `master/.env.example` to `master/.env`) before relying on a real events token. The master stack builds this directory, not `master/src/bridge`.

`/health` stays up when the relay is down so the process can keep retrying. Relay liveness is `relay.connected`, not the HTTP status.
