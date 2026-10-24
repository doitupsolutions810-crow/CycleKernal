# Descent XCVIII — The deployment exposes both data planes and observability planes

## Repository-grounded finding

A second pass beyond the route-level identity review found additional independent exposure surfaces in the repository's deployment configuration and monitoring API.

### 1. Monitoring API returns cross-user data

In \`backend/server.js\`, the \`GET /api/analytics/dashboard\` handler calls \`ChatHistory.find()\`, returns the ten most recent chat records, and returns the most recent simulation snapshot. The inspected route has no local authentication or authorization check. The \`GET /api/users/active\` handler also reports active-user counts. These are broader than a single \`userId\` path issue: the dashboard query has no per-user filter at all.

If the API is reachable by untrusted callers without an enforcing gateway, the dashboard can disclose recent chat messages/responses and snapshot data across users. This is a source-level exposure finding, not a claim that a deployed instance was reached.

### 2. Compose publishes stateful and observability services

The root \`docker-compose.yml\` publishes these container ports to host ports without an explicit host-interface binding:

- Monitoring API: \`3000:3000\`
- MongoDB: \`27017:27017\`
- Redis: \`6379:6379\`
- Prometheus: \`9090:9090\`
- Grafana: \`3001:3000\`
- Simulation API: \`5000:5000\`
- Frontend: \`8080:80\`

In Docker Compose, a port mapping without a host IP normally publishes on all host interfaces. Actual reachability still depends on host firewall, cloud security groups, and network topology; none were inspected. Publishing MongoDB and Redis directly is unnecessary for inter-container communication because services on the Compose network can address each other by service name. Prefer not to publish those ports in production, or bind them to loopback when host-local debugging is required.

### 3. Grafana admin credential is hard-coded

The Compose environment sets \`GF_SECURITY_ADMIN_PASSWORD=admin\`. If the Grafana port is reachable and the credential remains unchanged, the default admin username plus this password presents an administrative takeover risk for the Grafana instance and its dashboards/data sources. The repo configuration does not demonstrate that this is an actually deployed or externally reachable instance.

### 4. Prometheus and metrics are not access-controlled in the inspected configuration

The Compose file publishes Prometheus on \`9090:9090\`, and \`backend/server.js\` serves \`/metrics\` without authentication. The Prometheus configuration also scrapes service metrics on the internal Compose network. Metrics and dashboards can reveal service topology, request rates, active-user counts, and operational behavior. Treat observability as a protected data plane, not automatically public because it is "only monitoring."

## Formal trust model

Let \(p\) be a verified principal, \(r\) a resource, and \(o\) an operation. The acceptance predicate must include both authentication and resource/action authorization:

\[
\operatorname{allow}(p,r,o)
=
\operatorname{authenticated}(p)
\land
\operatorname{authorized}(p,r,o).
\]

For a dashboard response containing a set \(D\) of records, authorization must hold for every disclosed record:

\[
\operatorname{disclose}(p,D)
\Rightarrow
\forall d\in D,\ \operatorname{canRead}(p,d).
\]

Filtering by a caller-provided ID is not sufficient unless that ID is bound to the authenticated principal. An unfiltered \`find()\` over multi-user records is a particularly direct violation of the second invariant if the endpoint is externally accessible.

## Great Scale mapping

| Great Scale channel | System analogue | Verification question |
|---|---|---|
| \(\mathcal A_Q=P+N\) | Total set of stored state | What data exists and where is it reachable? |
| \(C=P-N\) | Signed/qualified scientific result | Does correctness hold independently of access rights? |
| \(E_Q=\mathcal A_Q-|C|\) | Residual/unaccounted state | Are all exposed endpoints, ports, and records accounted for? |
| Domain-validity gate | Request/resource validation | Is input valid and bounded? |
| Identity gate | Authenticated principal | Who is actually calling? |
| Capability gate | Resource/action scope | May this principal perform this operation on this resource? |
| Evidence/receipt gate | Auditable access decision | Can accepted and denied reads/writes be traced? |
| Observability plane | Metrics, logs, dashboards | Is operational metadata protected at the same trust level as the system? |

The analogy is architectural, not a claim that these security properties are quantum observables. Great Scale is useful here as a discipline of keeping independent channels separate: mathematical validity does not imply identity, authorization, confidentiality, or safe deployment.

## Remediation order

1. Remove MongoDB and Redis host-port publication in production; use Compose networking only. If host-local debugging is needed, bind explicitly to \`127.0.0.1\`.
2. Replace the hard-coded Grafana admin password with a required secret and fail startup if it is missing; rotate any credential that may have been used in a real deployment.
3. Put authentication and authorization in front of all API routes, including analytics, active-user, snapshots, chat history, health/metrics where appropriate.
4. Remove cross-user record payloads from general dashboards. Return aggregates by default; expose individual records only to explicitly authorized principals.
5. Restrict Prometheus/Grafana to a private management network or authenticated reverse proxy; do not assume a metrics endpoint is harmless.
6. Add automated checks that fail if database/cache ports are published in production compose, default credentials appear, or sensitive routes lack an auth/authorization guard.
7. Test denied and permitted access with two distinct principals and seeded records; test the deployment network from an untrusted segment.

## Verification boundary

This is source/configuration analysis of the repository files \`backend/server.js\`, \`docker-compose.yml\`, and \`prometheus/prometheus.yml\`. No live host, cloud firewall, running container, Grafana instance, or deployed API was accessed. The note identifies dangerous defaults and conditional exposure; it does not claim a production compromise or prove that the host is reachable from the public internet.
