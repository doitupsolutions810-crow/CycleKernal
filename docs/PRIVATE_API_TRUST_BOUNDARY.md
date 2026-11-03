# CycleKernal private API trust boundary (draft)

## Problem, pinned source

On `main` at `cbbcce9b6c3864e8710a5607033e351364dab605`, `backend/server.js` exposes:
- POST `/api/chat/save` with a caller-supplied `userId`
- GET `/api/chat/history/:userId`
- POST `/api/simulation/snapshot` with a caller-supplied `universeId`
- GET `/api/simulation/snapshots/:universeId`
- GET `/api/users/active` and GET `/api/analytics/dashboard`

The inspected server has no application-level authentication/authorization middleware for these routes. Permissive CORS and an IP rate limiter are not authorization. Actual exposure depends on deployment networking and any upstream gateway controls.

## Proposed protection

This branch adds a **single administrative service credential** gate for all `/api/*` routes, before handler execution:

- `CK_API_ADMIN_TOKEN` must be supplied by the deployment's secret store; absent/empty means HTTP 503 and no private API handler runs.
- Accepted presentation: `X-Admin-Token` **or** `Authorization: Bearer <token>`, never both.
- Exact token comparison uses SHA-256 digests and `crypto.timingSafeEqual`. Malformed/duplicated credentials are HTTP 401. No token is written into logs or source.
- `/health` and `/metrics` remain outside this middleware; review their separate exposure if made publicly accessible.
- No bypass for loopback/CORS settings.

### Identity and permissions limitation

**This is an admin-only API gate, not end-user authentication.** A holder of this shared operator token can still choose any `userId` or `universeId`. Never pass this administrative secret to public browser JavaScript or a mobile client. Only trusted backends should call the protected API; for public multi-user access, add a separate authenticated principal/tenant binding and scope checks for every read and write.

Changing this middleware may break the existing frontend if it sends unauthenticated API requests. Coordinate caller changes before merging.

## Verification

```bash
cd backend
npm run test:auth
```

The new module and tests require only Node built-ins. An isolated Node 22.16.0 run passed 8/8 focused cases covering disabled configuration, missing/wrong tokens, both accepted header forms, ambiguous/duplicate headers, whitespace invalid value types, and registration of the gate before every private route. The module parsed under `node --check`.

**Unverified:** full Express+MongoDB+Redis integration; actual gateway/proxy behavior; real trusted-caller migration; cross-tenant isolation; production configuration and hosted CI. No deployment or main-branch mutation is part of this draft.

## Cross-repository integration ledger

| Source | Revision/PR | Boundary |
|---|---|---|
| CycleKernal | main `cbbcce9b6c3864e8710a5607033e351364dab605` | unauthenticated private APIs; this branch adds operator gate |
| CycleKernal | PR #13 `https://github.com/doitupsolutions810-crow/CycleKernal/pull/13` | chat-save idempotency, separate concern; reconcile overlapping server.js |
| CycleKernal | PR #14 `https://github.com/doitupsolutions810-crow/CycleKernal/pull/14` | authenticated Fusion event intake, separate service routes |
| AVRONE | PR #19 `https://github.com/doitupsolutions810-crow/Avrone/pull/19` | durable signed Swarm enqueue; queue != completion |
| Capability Authority | PR #17 `https://github.com/doitupsolutions810-crow/capability-authority/pull/17` | signed capabilities, operation replay and scope |
| Capability Plane | PR #2 `https://github.com/doitupsolutions810-crow/capability-plane/pull/2` | durable event outbox and broker ACK boundary |

## Promotion gate

1. Review which CycleKernal routes should remain operator-only versus tenant-scoped.
2. Adapt all legitimate callers so no admin token is embedded in public client code.
3. Verify lost/wrong token, raw duplicate headers, cross-user/cross-universe access and resource scope with a real HTTP server.
4. Rebase/reconcile PR #13 without losing its atomic chat-save behavior.
5. Require exact-head CI and live isolated-stack tests before promoting or deploying.
