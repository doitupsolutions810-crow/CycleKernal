# Descent CX — strict JSON numeric-token admission

**Finding:** metric-domain validation does not guarantee the whole inbound document is valid JSON. Python's default JSON decoder accepts the non-standard tokens `NaN`, `Infinity`, and `-Infinity` as floating-point values. Known metric fields are normally rejected downstream as non-finite, but these values can otherwise survive in unused or nested metadata that the normalizer does not consume.

## Corrected boundary

The bridge parser now supplies a `parse_constant` hook to reject these tokens at decode time, recursively and independent of which field contains them. Duplicate-key rejection remains enabled. The rule applies to JSON text; already-materialized Python mappings cannot reveal original lexical tokens, so their values continue to be checked by field-specific admission.

## Formal statement

Let (D) be the JSON-text decoder and (V) the metric validator. The old composition was effectively (V(D(x))), where (D) extended JSON with non-standard constants. If a token occurred in metadata outside (V)'s inspected fields, it could survive. The corrected decoder (D_s) rejects those tokens before any envelope selection:

[
D_s(x) 	ext{ is defined only if every JSON numeric token uses standard JSON syntax.}
]

This is parser strictness, not source authentication or a claim about physical reality.

## Integration

- Added `_reject_json_constant` to both maintained bridge parsers.
- Configured `json.loads` with both duplicate-key and non-standard-constant rejection hooks.
- Added tests for all three tokens at metric, metadata, and nested-metadata locations and parity checks across parser copies.
- No score equation, Great Scale invariant, or legacy alias policy changes.

## Verification boundary

Regression tests are committed but the hosted Actions runs have failed before exposing executed steps. Until a runner executes the repository suite, compile checks, and build jobs, those remain unverified. An isolated semantic probe is not equivalent to the checked-in test suite.

## Great Scale mapping — System 33: strict token boundary

| Layer | Meaning | Invariant |
|---|---|---|
| Raw text | Relay JSON bytes/text | Preserve syntax until decoding |
| Parser boundary | JSON decoder | Reject duplicate keys and non-standard numeric constants |
| Semantic admission | Envelope and metric validation | Only validated values reach scoring |
| Evidence | Accepted normalized vector or explicit rejection | A reproducible outcome, not publisher identity |
| Limitation | Correct syntax can still carry false data | Authenticate the source separately |

The existing geometry remains unchanged: (S(h)=h(1-h)), (Psi=phi^{-2}+S(h)gephi^{-2}). This is a software parsing invariant, not a new physical law.
