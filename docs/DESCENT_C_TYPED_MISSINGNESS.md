# Descent C — Typed missingness and source-preserving fusion

**Status:** integration finding and regression contract. This is not a new physical law and not a claim of successful hosted CI.

## Finding

A missing object and an explicitly supplied empty object are not the same observation.

The fusion interface accepts optional symbolic inputs belief and resources. Before this descent, the implementation used Python truthiness:

- belief_provided = bool(belief)
- resources_provided = bool(resources)
- belief = belief or defaults
- resources = resources or defaults

Consequently, absent inputs (None) and explicit empty objects ({}) collapsed into the same fallback path. The evidence then described the result as default, erasing the fact that a payload had in fact supplied an empty mapping. In the score path, the empty resource mapping was replaced by the baseline resource mapping instead of contributing its own zero values.

This is an instance of a non-injective observation map. Let the input be a tagged value
\[
I\in\{\operatorname{Absent},\operatorname{Present}(D)\},
\]
where \(D\) is a mapping that may validly be empty. A truthiness projection
\[
T(\operatorname{Absent})=T(\operatorname{Present}(\{\}))=\text{fallback}
\]
cannot recover whether input was absent or present-but-empty.

That loss matters because the default resource vector is \((50,20,1)\), while an explicit empty resource mapping uses the per-field resource defaults \((0,0,0)\). With truth \(0.5\), the symbolic score changes:
\[
s_{\rm absent}
=0.55(0.5)+0.45\left[
0.45\frac{50}{150}
+0.35\frac{20}{40}
+0.20\frac18\right]
=0.4325,
\]
while
\[
s_{\rm empty}=0.55(0.5)+0.45(0)=0.275.
\]

Treating the two states as identical therefore makes both the reported score and provenance misleading.

## Changes integrated on the GS–LVI branch

- In all three maintained fusion implementations (backend/ns_fusion.py, src/bridge/ns_fusion.py, and master/src/bridge/ns_fusion.py), only None triggers the whole-object baseline fallback. An explicit empty mapping remains explicit input.
- Source labels use an explicit non-None check, not mapping truthiness.
- The evidence builder and canonical identity-state builder apply the same absent-vs-present rule, so recorded inputs, score components, and fusion_state_witness agree.
- The master bridge evidence builder has been aligned to the primary bridge's fields for symbolic and neural inputs, thresholds, Great Scale residual, source labels, and signed margins.
- Regression tests cover the numerical score difference, distinct source labels, distinct state fingerprints, witness recomputation, relay parsing, and the behavior of all three maintained fusion copies.

For the valid absent-input case, the existing backward-compatible baseline stays in place. The behavior changes only when a caller explicitly sends an empty object; that object no longer silently masquerades as missing data.

## Great Scale mapping

This is **System 25 — Typed Observation and Missingness**.

The state should be thought of as a tuple:
\[
X=(s,n,N,\pi,\mu,W),
\]
where \(s,n\) are the symbolic and neural channels, \(N=\sqrt{sn}\) is the compatibility projection, \(\pi\) is source provenance, \(\mu\) is input presence/completeness metadata, and \(W\) is the canonical witness.

The projection \(N\) remains unchanged. The additional metadata preserves facts that \(N\) alone cannot identify. The presence channel distinguishes at least:
- default: no mapping supplied, baseline used;
- provided: a mapping was supplied, including an empty mapping;
- field-level defaults: individual values not present within an explicitly supplied mapping use the documented per-field behavior.

The Great Scale heat/cone state also remains unchanged:
\[
S(h)=h(1-h),\qquad \Psi=\phi^{-2}+S\geq\phi^{-2}.
\]
The typed observation channel is additional instrumentation, not a redefinition of the geometry.

## Scientific and security boundary

Input-presence metadata does not prove truth or authenticity. A relay can intentionally send {}; the system can accurately record that an empty mapping arrived, but this does not authenticate the relay or explain why the fields were omitted. Production trust still requires an authenticated transport/workload identity, explicit schemas, and operational policy for missing required fields.

A source label is evidence about which code path handled input; it is not cryptographic proof of the upstream publisher.

## Verify

The branch regression suites now assert that:
1. absent and empty inputs yield different provenance and score values;
2. state fingerprints are different for those different input states;
3. the canonical witness recomputes to the reported fingerprint;
4. the same contract holds in the backend and both bridge copies;
5. relay normalization preserves an explicitly empty object.

The focused arithmetic is directly checkable from the formula above. The exact committed repository tests, Python compile step, and Docker builds still require a real GitHub Actions runner. Recent Actions attempts have failed before any runner was assigned, with no job steps executed; that status is blocked/unverified, not a passing build and not evidence of a test assertion failure.
