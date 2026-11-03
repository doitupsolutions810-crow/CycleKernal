# Readable HTTP refusal — November 3, 2026

An actual AVRONE / CognitiveBridge / WS Relay network run exposed a TCP reset when an early 413 response forced `Connection: close` while the client was still sending. Remove the forced close and let the ASGI HTTP server drain unread frames. The 4096-byte admission limit and authentication order remain enforced.

This patch is based on the immutable PR #14 source `f3a763fe230b6de3450c235c165773c5ea9550bb`; its draft PR targets that proposal's branch. It adds a real uvicorn/TCP regression with repeated declared and chunked oversized bodies and subsequent health requests. The existing contract assertion now checks that the response does not force a close.

All 47 tests under `tests/` pass in 3.50 seconds. Python 3.12 deprecation warnings remain in dependencies and the existing trait clock. The AVRONE and recovered Fusion relay combination completed 50 cycles and 21 assertions, including both service restarts, durable deduplication and software-check evidence delivery. The input metrics are explicit test data; no live model or physical telemetry is certified.

Run `python -m pytest -q tests`. The cross-repository runner lives in Fusion Bridge PR #2, `scripts/verify-live-peers.py`. AVRONE's corresponding transport repair is `0b2515516b3689ddfc6787ba9ac76e00c22735c9`.
