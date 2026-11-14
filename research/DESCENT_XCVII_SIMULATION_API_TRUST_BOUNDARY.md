# Descent XCVII — Simulation identity is caller-selected, not authenticated

## Repository-grounded finding

In \`backend/server.js\`, the Express app installs security headers, permissive CORS, JSON parsing, logging, and an IP rate limiter. The inspected API routes do not apply an authentication or authorization middleware:

- \`POST /api/chat/save\` accepts \`userId\` from the request body, persists the chat, and writes a Redis cache entry under \`chat:<userId>:latest\`.
- \`GET /api/chat/history/:userId\` uses the path's \`userId\` directly to query MongoDB and Redis.
- \`POST /api/simulation/snapshot\` accepts a caller-supplied \`universeId\` and persists the supplied snapshot.
- \`GET /api/simulation/snapshots/:universeId\` retrieves snapshots for a caller-supplied universe ID.

The inspected server code does not bind these identifiers to an authenticated principal or check ownership/tenant scope. Consequently, if this server is reachable by an untrusted caller without an enforcing upstream gateway, user and universe identifiers are not an authorization boundary. A caller may be able to read another user's history or inject records/snapshots under another identity. The exposure depends on deployment reachability and any upstream controls not present in the inspected file; this note does not assume those controls are absent elsewhere.

Permissive CORS is not itself authentication and does not prevent direct non-browser HTTP clients from calling the API.

## Why this is a trust-boundary defect

The system treats an identifier as if it were proof of authority:

\[
\text{caller supplies } u \;\not\Rightarrow\; \text{caller is authorized for } u.
\]

The required rule is:

\[
\operatorname{allow}(p,r,o)
\iff
\operatorname{authenticated}(p)
\land
\operatorname{authorized}(p,r,o),
\]

where \(p\) is a verified principal, \(r\) is the user/universe resource, and \(o\) is the operation. The resource identity must be derived from or checked against authenticated claims, not trusted from request JSON/path parameters alone.

## Great Scale mapping

| Great Scale / platform channel | Meaning | Required control |
|---|---|---|
| Scientific result, model, residuals | Validity of a claim | Do not treat a correct result as authorization |
| Principal identity | Who is making the request | Verify a trusted token/session or workload identity |
| User/universe identifier | Target resource | Bind resource scope to the authenticated principal |
| Capability scope | What the principal may do | Check action, audience, resource, expiry, and revocation |
| Snapshot/chat evidence | Persisted record | Record verified actor, tenant/resource, request digest, and timestamp |
| Receipt/audit trail | Accountability | Emit durable, tamper-evident evidence for accepted and denied operations |

This is the same invariant separation used by the Great Scale evidence envelope: scientific validity, identity, permission, and persistence are distinct gates. None substitutes for another.

## Recommended implementation

1. Add a centralized authentication middleware before all \`/api/*\` routes; fail closed when identity verification is unavailable.
2. Derive the effective \`userId\` from verified identity claims, or explicitly authorize a requested target ID against those claims.
3. Apply universe-level tenant/resource authorization to both snapshot reads and writes.
4. Validate request schemas and bound \`limit\` to a small positive maximum; avoid exposing raw internal exception messages to clients.
5. Add tests for missing/invalid credentials, cross-user history reads, spoofed \`userId\` writes, cross-universe snapshot access, and authorized same-tenant access.
6. If the service intentionally relies on a gateway, document and enforce that trust boundary (network isolation plus authenticated gateway-to-service identity); do not rely on CORS as a substitute.

## Verification status

This finding is based on source-level inspection of \`backend/server.js\`. No live exploit, production deployment, or end-to-end request was executed. Full CycleKernel tests/builds were not run as part of this note. The recommended tests should be added before treating the trust boundary as verified.
