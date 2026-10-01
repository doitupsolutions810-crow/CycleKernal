# Production LLM wiring — ChatBot reasoner

The colony reasoner is `master/src/chat/reasoner.py`. It speaks the OpenAI chat-completions contract and falls back to `local_reason` when the endpoint is unset or errors.

## Environment

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `LLM_BASE_URL` | no | empty | Origin only. Do not append `/v1`. Example: `http://llm.internal:8000` |
| `LLM_API_KEY` | no | empty | Sent as `Authorization: Bearer …` when set |
| `LLM_MODEL` | no | `gpt-4o-mini` | `model` field on the completions payload |

Resolved request:

```
POST ${LLM_BASE_URL}/v1/chat/completions
```

Mood from the cognitive bridge is appended to the system prompt as `Current cognitive mood: <mood>` when the caller passes `mood`. NS fitness does not replace that string. It biases the mood label before the reasoner sees it (`mood_dot = 0.65 * ns_fitness + 0.35 * mood_score`).

## Fallback

- Empty `LLM_BASE_URL`: `call_llm` returns `""` and `reason()` sets `source=local_reasoner`.
- HTTP error, timeout (60s), or non-JSON body: same fallback. The pipeline still answers.
- A configured endpoint that returns tool JSON sets `source=custom_llm`.

## Prove it without a model

```
python3 master/src/chat/test_reasoner_llm.py
```

That test stubs `httpx` and asserts the exact completions URL, bearer header, mood injection, and local fallback.

## Compose

`make up` is `docker compose up -d --build` from the repo root (`docker-compose.yml`: simulation, monitoring, mongodb, redis, prometheus, grafana, frontend).

`make health` probes:

- simulation `GET :5000/health`
- monitoring `GET :3000/health`
- prometheus `GET :9090/-/ready`
- grafana `GET :3001/api/health`
- frontend `GET :8080/`
- redis `PING`, mongodb TCP `27017`

The ChatBot reasoner is not a compose service in this file. It lives on the master stack (`master/docker-compose.yml`, chat service). Point that service at the same `LLM_BASE_URL`. This sandbox has no Docker daemon, so `make up` / `make health` cannot be executed here. Run both on a host with Docker and keep any failing service name from `make health`.
