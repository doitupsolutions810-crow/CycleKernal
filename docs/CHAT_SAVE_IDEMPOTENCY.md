# CycleKernel chat-save idempotency contract

## Why this exists

The former POST /api/chat/save route wrote a MongoDB document and then refreshed metrics and Redis. If either secondary step failed after the Mongo write committed, the endpoint returned HTTP 500. A caller retry could insert a duplicate chat because no stable operation identity was enforced.

The new handler separates the primary MongoDB write from ancillary metrics/cache updates and reconciles uncertain write acknowledgements using the same operation ID.

## Request contract

Every POST /api/chat/save request must supply a stable key in either:

- HTTP header: `Idempotency-Key: chat-save-<client-generated-unique-id>`
- JSON body: `operationId` (or legacy spelling `operation_id`)

If both are present they must be identical. A key must be a string of 1–128 ASCII letters, digits, dot, underscore, or hyphen. Clients must reuse the same key for retries of the same logical request and must not reuse it for different content.

Example:

```http
POST /api/chat/save
Content-Type: application/json
Idempotency-Key: chat-save-7c0e83c9-3e16-4c26-9a8f-cc0123456789

{
  "userId": "user-123",
  "civId": "U1",
  "message": "hello",
  "response": "world",
  "metadata": { "attention": 1 }
}
```

The example key is illustrative; clients should generate a new high-entropy UUID for each new logical save.

## Response behavior

- `201`: a new MongoDB chat row was created.
- `200`: the matching operation was already stored and its original row is returned.
- `400`: missing/invalid idempotency key, invalid request object, missing user ID, or mismatched header/body key.
- `409`: the same key was reused with a different canonical request digest.
- `503` with `status: indeterminate`: the primary write/lookup outcome cannot be confirmed. Retry only with the same key; never generate a fresh key to retry an uncertain save.

Once the Mongo row is confirmed, Redis and metrics refresh are ancillary. Their failures are returned under `ancillary.cache` or `ancillary.metrics` as `degraded`; they do not turn a confirmed primary write into a false 500/no-effect response.

## Storage and concurrency

A sparse unique index on `operationId` preserves older rows that predate this contract. The request digest is SHA-256 over canonical JSON of the chat payload, with object keys sorted recursively. A duplicate key returns the existing row if the digest matches; a digest mismatch is rejected with 409.

The index is ensured before the first write. Duplicate-key races and uncertain write acknowledgements are reconciled by looking up the same operation ID after the write call.

## Guarantee boundary

This provides idempotent persistence for the chat-save endpoint when callers reuse a stable key and MongoDB enforces the unique index. It does not make Redis, metrics, or MongoDB part of one distributed transaction. A 503 indeterminate response means the server could not establish the write outcome; reusing the same key is required to reconcile it.

The focused test suite uses an injected model adapter and failure injection. It does not replace a real MongoDB integration test, nor does it prove the live Redis deployment is available.
