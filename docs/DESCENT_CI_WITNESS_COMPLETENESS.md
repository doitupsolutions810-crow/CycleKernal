# Descent CI — Field-presence closure for full-state evidence

**Status:** source-provenance improvement with regression tests. This is a software integrity result, not a claim of physical validation or successful hosted CI.

## Finding

Descent C distinguished an absent mapping from an explicitly empty mapping. A deeper pass finds that the same information loss can occur one level down: a resource field omitted from a supplied mapping and a resource field explicitly present with its default value can have the same effective numeric value.

For example, when resources is present:
\[
\{\}\quad\text{and}\quad
\{\text{attention}:0,\text{compute}:0,\text{memory\_nodes}:0\}
\]
both yield effective resource values \((0,0,0)\). The symbolic score can be equal, and a witness that records only the effective values cannot distinguish omission from an explicit measurement of zero.

There is a second related case: the field belief.deception is validated but is not part of the current symbolic-score formula, which uses belief.truth and resource viability. Two otherwise identical inputs with different deception values therefore have the same score. If the state fingerprint is intended to witness the input state, not just the arithmetic inputs, that validated field should not silently disappear from evidence.

The correct distinction is between:
- **computation identity:** enough values to recompute the score;
- **input-state identity:** the relevant supplied values and which fields were present;
- **publisher authenticity:** evidence about who supplied the input.

These are different claims. One digest should not be treated as proving all three.

## Changes

The three fusion implementations now add a recognized-field presence map to the evidence and canonical state witness. It distinguishes:
- whether the belief mapping was supplied;
- whether belief.truth and belief.deception were present;
- whether the resources mapping was supplied;
- whether resources.attention, resources.compute, and resources.memory_nodes were present.

The effective numeric values remain recorded as before. The witness also retains the effective deception value even though the current fitness formula does not use it. This preserves validated input facts without quietly changing the score semantics.

The master bridge's evidence builder has been aligned with the primary bridge so the same evidence fields travel through both runtime variants. Tests now compare absent, empty, field-omitted, explicit-zero, and differing-deception cases, verify distinct state fingerprints where input states differ, and recompute the fingerprints from the emitted witness.

## Mathematics

Let \(z\) be the effective numeric vector, and let \(m\in\{0,1\}^k\) be the field-presence vector for the \(k\) recognized input keys. The scoring function remains:
\[
N=F(z).
\]
But the state identifier should represent:
\[
\operatorname{id}(z,m,\pi),
\]
where \(\pi\) is the mapping-level source label. In general,
\[
F(z_1)=F(z_2)\ \not\Rightarrow\
(z_1,m_1,\pi_1)=(z_2,m_2,\pi_2).
\]
Equal scores establish only equality of the scalar projection; they do not establish equality of evidence state.

For example, an omitted attention field and explicit attention \(=0\) can have the same effective value and score, while their presence bits differ. Similarly, changing the supplied deception value does not change the existing score formula, but it changes the preserved evidence state.

## Great Scale mapping — System 25: Typed Observation and Missingness

The full observation should travel as
\[
X=(s,n,N,\pi,\mu,W),
\]
where \(s,n\) are the symbolic and neural channels, \(N=\sqrt{sn}\) is the legacy projection, \(\pi\) is provenance, \(\mu\) is field-presence metadata, and \(W\) is the canonical witness.

This extends Great Scale's witness discipline: a risk certificate carries its feasible set, support margin, extremal witness, method, and proof status; a fusion record carries raw channel scores, effective values, mapping-level provenance, field-level presence, thresholds, and a canonical witness. The same mathematical principle is used in both domains: retain the information that the projection discards.

The Great Scale geometry remains unchanged:
\[
S(h)=h(1-h),\qquad \Psi=\phi^{-2}+S\geq\phi^{-2}.
\]
No claim is made that a score, witness, or digest is a physical observable or authorization credential.

## Limits

The presence map covers the recognized fields used by the current contract; it is not a byte-for-byte capture of every arbitrary unknown key in the incoming object. The state fingerprint proves consistency of the recorded witness and digest if recomputed, not authenticity of the upstream publisher. A trusted relay identity and protected transport remain separate requirements.

Also, preserving belief.deception is not the same as using it in fitness. The current fitness equation remains truth-based plus resource viability. If deception is intended to affect the score, that requires a separate, explicit mathematical and policy change with its own validation; this descent does not smuggle such a change in.

## Verification contract

The added tests assert:
1. absent, empty, and explicit-zero resources produce the expected effective values and presence bits;
2. states with equal fitness but different supplied fields receive different fingerprints;
3. supplied deception survives the witness even when the score remains unchanged;
4. the primary bridge, backend, and master bridge return consistent presence evidence;
5. every canonical witness recomputes to the reported SHA-256 fingerprint.

A mathematical/isolated harness is not a substitute for the committed tests. Recent hosted Actions jobs in both repositories failed before runner allocation with no executed steps and unavailable logs. Therefore the full CI/build/bridge-image status remains blocked and unverified.
