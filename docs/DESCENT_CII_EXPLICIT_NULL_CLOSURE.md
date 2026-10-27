# Descent CII — explicit-null closure

**Status:** source-level integration and regression contract. This is a data-semantics finding, not a new physical law. Hosted CI and container builds remain unverified until actual runner steps execute.

## Finding

Descent C and CI preserved the distinction between an absent mapping and a supplied empty mapping, plus the presence of recognized fields. One final ambiguity remained at the lower-level fusion boundary: reading optional objects with `metrics.get("belief")` or `metrics.get("resources")` maps both an omitted key and a present key whose value is `None` to the same Python value.

For a serialized input, these are different states:

\[
\operatorname{Omitted}(k)\ne\operatorname{Present}(k,\texttt{null}).
\]

The old projection was non-injective:

\[
\pi(\operatorname{Omitted}(k))
=\pi(\operatorname{Present}(k,\texttt{null}))
=\texttt{None}.
\]

The result could silently use the absent-input defaults for an explicitly malformed value. The relay parser already rejected explicit null because a supplied `belief` or `resources` field must be a JSON object; direct internal callers of `apply_fusion` could bypass that ingress parser.

## Integrated contract

All three maintained `ns_fusion.py` implementations now inspect key membership separately from the value:

- **Key omitted:** input is absent and the documented baseline remains in use.
- **Key supplied with a mapping:** validate it; an empty mapping is valid and remains explicit evidence.
- **Key supplied with `None` / JSON `null`, or another non-mapping:** fail closed with `ValueError`; do not silently reinterpret malformed input as absent.

This preserves compatibility for omitted inputs and valid mappings while closing the ambiguity at the computation boundary. The primary relay parser and master relay parser already reject null objects; a regression locks that behavior. New cross-copy tests assert the internal guard in backend, primary bridge, and master bridge.

## Mathematics and Great Scale mapping

This remains **System 25 — Typed Observation and Missingness**. Treat mapping-level input as a tagged domain rather than a truthy/falsy scalar:

\[
I_k\in\{
\operatorname{Absent},
\operatorname{Present}(D)
\},
\qquad D\text{ a mapping, possibly }\emptyset.
\]

A malformed present-null value is outside that domain and must be rejected, rather than coerced into `Absent`. The calculation still emits the legacy score

\[
N=\sqrt{s\,n},
\]

with no change to the scoring formula or decision thresholds. The evidence companion carries source labels, recognized-field presence, the canonical state witness, and the full fingerprint. Great Scale's independent geometry remains

\[
S(h)=h(1-h),\qquad \Psi=\phi^{-2}+S\geq\phi^{-2}.
\]

The connection is methodological: a non-injective scalar projection cannot recover input semantics, so the typed observation and witness must stay beside the score.

## Verification criteria

The branch adds regressions that (1) omitted keys still use documented defaults, (2) explicit null is rejected in all three fusion implementations, and (3) both relay parsers reject a supplied null object. The exact repository suite, compile step, Docker builds, and live relay smoke test still need executed hosted-runner evidence; static code inspection is not a substitute for those runs.

## Trust boundary

Rejecting explicit null improves input integrity but does not authenticate the publisher. A valid empty mapping can still be intentionally supplied, and a source label or SHA-256 witness proves neither upstream identity nor benevolent intent. Production still requires authenticated transport/workload identity and a policy for which fields are required.
