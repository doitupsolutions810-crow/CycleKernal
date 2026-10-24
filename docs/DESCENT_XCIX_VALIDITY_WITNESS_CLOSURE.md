# Descent XCIX — Validity and witness closure

**Status:** software integrity and input-domain hardening. This is not a new physical law or empirical claim.

## Finding

A scalar summary does not identify the full state that produced it. CycleKernel's legacy projection is
\[
g(s,n)=\sqrt{sn}.
\]
For example,
\[
g(0.9,0.4)=0.6=g(0.6,0.6),
\]
although the source-channel imbalance \(s-n\) is \(0.5\) for the first pair and \(0\) for the second. Retaining the full channel values fixes that particular identifiability loss.

A second requirement follows: a state fingerprint should be independently reproducible from the exact payload that it names. A digest without the corresponding canonical witness is difficult to verify later if the live state has already advanced.

A third requirement is input validity. JSON-shape validation alone is insufficient: a payload may be an object and still contain an impossible domain value. Before this descent, the bridge accepted belief and resources as mappings, while symbolic_score clipped out-of-range truth and aggregate resource values into plausible scores. That hid bad inputs rather than rejecting them.

## Changes

### 1. Canonical fingerprint witness

Every fitness_evidence record now includes fusion_state_witness, the exact canonical identity-state mapping used to calculate fusion_state_id:
\[
\operatorname{id}(W)=\texttt{fs-}\,\operatorname{SHA256}(\operatorname{canonicalJSON}(W)).
\]
A consumer can independently recompute the fingerprint from the recorded witness. The witness is separate from the rounded display fields in the evidence summary and preserves source labels and effective inputs used in the calculation.

This proves internal payload/digest consistency if the verifier recomputes it. **It does not prove that the metric source is authentic.** A self-reported source label and a valid hash do not establish who supplied the original data.

### 2. Strict symbolic input domains

The three maintained fusion implementations now validate inputs before computing a score:

- belief.truth and belief.deception, when supplied, must be numeric, finite, and in \([0,1]\);
- resources.attention, resources.compute, and resources.memory_nodes, when supplied, must be numeric, finite, and nonnegative;
- malformed mappings and out-of-domain values are rejected rather than silently clipped.

The same validation is applied at both relay-ingress parsers and in symbolic_score, protecting callers that bypass the bridge. Resource values are not capped at 8 because simulation memory-node counts may legitimately grow beyond that value; only finite, nonnegative values are enforced.

The legacy formulas, score weights, Great Scale descent behavior, and promotion/demotion thresholds are not changed for valid inputs.

## Great Scale mapping

Use the extended typed state
\[
X=(G,s,n,g,\pi,W),
\]
where \(G\) is Great Scale geometry, \(s,n\) are symbolic and neural channels, \(g=\sqrt{sn}\) is their legacy projection, \(\pi\) records source metadata, and \(W\) is the canonical witness. The state fingerprint binds the witness to a digest; it does not turn the score or the digest into an authorization credential.

This is the validity side of **System 24 — Provenance-Conditioned Projection**:
- the scalar is a useful projection, not the whole state;
- the witness preserves the state needed to audit that projection;
- domain checks preserve the conditions required for the calculation to be meaningful;
- transport identity and trusted-source verification remain a separate security layer.

For the quantum-geometric Great Scale bridge, the existing relationship remains
\[
S_Q=\frac14\frac{\det Q}{\det g}=\frac{R}{4},\qquad
\Psi_Q=\phi^{-2}+S_Q\geq\phi^{-2}.
\]
These equations do not imply an empirical physical law, and neither \(\Psi_Q\) nor the fusion score establishes permission to execute.

## Regression verification

New tests check that:

1. an evidence witness recomputes to its fusion_state_id;
2. lineage events carry a witness matching the current state ID;
3. out-of-range or non-finite belief/resource values fail closed in the fusion layer;
4. the relay parsers reject those same values before publishing them to the state mapper.

Run the existing Great Scale/CycleKernel workflow on the PR branch to test fusion, lineage, relay normalization, Python compilation, and the two bridge images. Hosted runs were previously observed to fail before any runner step was assigned, so a failed job with zero steps is not evidence of a test assertion failure. A passing local or hosted run must be recorded separately from the source-level and mathematical checks in this note.

## Limits

A valid domain and a reproducible digest are necessary, not sufficient, to trust a remote observation. Production must still authenticate the relay through a protected transport and authenticated workload identity or mutual TLS, enforce access policy, and verify provenance. A checksum proves sameness of bytes, not truth of the claim.
