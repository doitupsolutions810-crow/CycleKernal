# Descent CVIII — alias concordance and duplicate-key closure

**Finding:** strict type admission after JSON decoding does not fully preserve the submitted observation. Two normalization rules can erase contradictory raw evidence before scoring:

1. JSON object decoders commonly accept repeated identical keys and keep only the last value.
2. Relay aliases are equivalent spellings of one metric (L5 / l5 / entropy, for example). A first-match selector can silently ignore a second spelling carrying a different value—or an invalid type.

For a canonical metric m, let A_m be its supported spellings and let P_m be the spellings present in the raw object. Ingress now requires P_m to be nonempty, validates every present spelling as a finite JSON number in the metric's domain, and requires all admitted values to agree. Equal aliases remain accepted for compatibility; conflicting or invalid aliases fail closed. String JSON is decoded with a duplicate-key hook that rejects repeated keys recursively before constructing ordinary dictionaries.

## Mathematical statement

A first-match normalizer selecting the first present alias is non-injective over multi-spelling payloads: different payloads can normalize to the same selected value while carrying contradictory unused values. Duplicate-key last-wins parsing has the same defect: it discards an earlier value before application validation can inspect it.

The corrected admission condition is:

Admit_m(x) iff P_m is nonempty AND every present x_a is finite and in-domain AND the set of admitted numeric values has cardinality one.

This is an application-level consistency rule, not cryptographic authentication and not proof that the upstream relay is truthful.

## Integration

- Updated src/bridge/main.py and master/src/bridge/main.py identically.
- Rejected repeated JSON object keys before the decoder can collapse them.
- Validated every present alias, rejecting wrong types, out-of-range values, and disagreement.
- Kept matching canonical/legacy aliases compatible.
- Added primary-parser and primary/master parity regressions for top-level and nested duplicate keys, conflicting aliases, invalid secondary aliases, and matching aliases.

## Verification boundary

These are source changes plus committed regression tests. The CycleKernal Actions workflow has repeatedly failed with no assigned runner / no executed steps, so do not claim that the committed repository suite, compile checks, or Docker image builds passed until logs show those steps executing. Local semantic probes can verify the admission rule but are not a substitute for the repository test suite or live relay smoke test.

## Great Scale mapping — System 31: alias concordance

| Great Scale layer | Meaning here | Mathematics / engineering |
|---|---|---|
| Raw observation | All supplied keys and values | Preserve multiplicity until validation |
| Boundary / seam | JSON decoding and alias selection | Reject repeated keys and contradictory aliases before normalization |
| Invariant | One semantic metric has one admitted value | All present aliases must be finite, in-domain, and equal |
| Witness | Canonical normalized metrics plus rejection result | Reproducible validation outcome; not publisher authentication |
| Risk / limitation | Unauthenticated relay can still lie consistently | Transport identity and network policy remain separate controls |

The existing Great Scale heat/cone relation is unchanged:

S(h) = h(1-h), and Ψ = φ⁻² + S(h) ≥ φ⁻².

This descent applies the same projection discipline to telemetry admission; it does not assert a new physical law.
