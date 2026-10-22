# Great Scale → CycleKernal descent integration (draft)

## What is wired

- \`backend/descent_engine.py\` is a deterministic Python adapter of Great Scale \`public/scale.js\` \`DescentEngine\` at source revision \`a0fd4b10b964932f90abf7004bbe7e28687168d1\`.
- Each \`Universe.simulate_cycle()\` advances exactly one descent tick, independent of the number of civilizations in that universe.
- The current stress residual is normalized and fed into the neural entropy input. The normalization weight is 0.35; the configured residual domain is [0, 7].
- Every \`apply_fusion()\` result includes \`stress_residual\`, \`stress_residual_normalized\`, \`neural_entropy_used\`, and \`descent_schema\`.
- Cycle state and Prometheus metrics expose the latest descent coordinate and residual.
- \`GET /api/v1/scale/state\` returns the \`great-scale.descent/v0.4.2\` snapshot schema.

## Domain and seam contract

The JavaScript involution is modular, but the raw residual \`abs(x - involution(x))\` is not a continuous circular distance at the 0/9 seam. In particular, values very close to zero can have residuals greater than 7. The integrated scheduler starts at x=1 and contracts toward x*=4.5 with k=0.5, keeping its orbit in [1, 4.5], where residual/7 is a valid normalization. The adapter rejects residuals outside [0, 7] rather than silently clipping them.

For the configured orbit,
\`x_(t+1) = 4.5 + 0.5 (x_t - 4.5)\` and
\`r_(t+1) = r_t / 2\` after each tick, until floating-point precision dominates.

## API security boundary

The read-only endpoint fails closed unless \`SCALE_API_TOKEN\` is set. Requests must send \`Authorization: Bearer <token>\`. This is bearer-token protection only; it is **not** SPIFFE/SPIRE workload attestation. A SPIFFE-aware verifier and authorization policy must be integrated before describing this endpoint as SPIFFE-attested. Do not expose the endpoint publicly without a deployment-level trust boundary.

No unauthenticated \`/step\` endpoint is added: CycleKernal's simulation scheduler owns tick ordering, and externally triggered ticks need an idempotency and authorization contract first.

## Threshold semantics

\`CONE = φ⁻²\` is the lower bound for Great Scale's defined \`Ψ = CONE + S\` quantity. CycleKernal's promotion/demotion thresholds operate on a different fused-fitness score. Numerical equality does not establish semantic equivalence, so this change intentionally does not set \`DEMOTE_THRESHOLD = CONE\`. That policy change requires a defined mapping or a proof that both values inhabit the same normalized decision domain.

## Verification status

The unit and integration tests cover modular involution identity on 37 points, residual halving, convergence, bounded history, normalization scope, fusion receipt fields, one tick per universe cycle, endpoint authentication, and snapshot schema. The GitHub Actions run is the authoritative hosted execution record. Until it completes successfully, the code is a proposed branch integration, not a verified deployment.

This adapter is software integration evidence only; it is not evidence for a new physical law of quantum geometry.
