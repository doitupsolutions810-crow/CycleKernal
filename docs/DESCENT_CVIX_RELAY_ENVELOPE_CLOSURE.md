# Descent CVIX — relay envelope closure

**Finding:** duplicate-key and alias checks still do not establish that one payload has only one authoritative observation map. The bridge accepts both a direct metric object and a wrapped form containing a metrics object. Previously, when the wrapper key existed, the parser selected payload.metrics and ignored recognized metric fields that also appeared at the outer level.

For example, the outer Core value could contradict metrics.Core while the inner value silently won. The normalization function was again non-injective: different raw envelopes collapsed to the same normalized vector.

## Admission invariant

There are two supported envelope forms:
- Direct form: recognized metric fields are in the root object.
- Wrapped form: recognized metric fields are inside the metrics object; unrelated envelope metadata such as source or timestamp may remain outside.

A wrapped envelope must not also contain recognized metric input fields at its outer level. This includes Core/U2/L2/L5 aliases, symbolic belief/resources, stress_residual, and descent_schema. The parser now rejects such shadow fields rather than silently discarding them. This rule complements CVIII: duplicate JSON keys are rejected, aliases inside the selected object must agree, and the envelope must identify one metric map.

## Formalization

Let E be an input envelope and let M(E) select its observation map. If M(E) chooses E.metrics whenever the key is present, then the following distinct envelopes can map to the same result:

M({metrics: m}) = m = M({metrics: m, Core: c_shadow}).

The corrected precondition is:
Admit(E) iff either (a) no metrics wrapper exists and the root is the observation map, or (b) a metrics wrapper exists, is an object, and no recognized metric input key exists at the outer level.

This is an input-shape invariant, not a trust or authentication guarantee.

## Integration

- Updated both maintained bridge parsers with the same envelope check.
- Added tests for outer Core, coupling, Great Scale residual/schema, and symbolic-field shadows.
- Confirmed that non-metric envelope metadata remains supported.
- Added cross-copy parity coverage.

## Verification boundary

The isolated CVIII semantic harness passed 11/11 checks. The CVIX cases are now committed as regression tests, but no local repository environment is available to execute the complete checked-in suite. GitHub Actions still reports runner_id=0, no runner name, and empty step arrays; consequently Python unit tests, compile checks, Docker builds, npm builds, and live WebSocket smoke tests are not reported as passed.

## Great Scale mapping — System 32: envelope closure

| Layer | Meaning | Invariant |
|---|---|---|
| Observation boundary | Choose direct or wrapped payload form | Exactly one authoritative metric map |
| Consistency | Keep recognized input fields in the selected map | No outer shadow fields when metrics wrapper is present |
| Witness | Normalize only after envelope and alias checks | A digest can describe normalized state but cannot authenticate its publisher |
| Operational limit | A consistent relay message may still be false | Use protected transport/workload identity and network policy |

Great Scale geometry is unchanged: S(h)=h(1-h) and Ψ=φ⁻²+S(h)≥φ⁻². This is a software input-integrity result, not a new physical law.
