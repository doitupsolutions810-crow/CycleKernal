# Descent CIII — evidence/identity concordance

**Status:** software-integrity finding with source integration and regression coverage added. This is not a new physical law. The committed repository suites, container builds, and hosted CI still require actual test-step execution.

## Finding

The simulation scheduler computed its fitness channels from the live civilization belief/resource mappings, then separately called the evidence builder without forwarding those mappings or its neural context. The evidence builder therefore populated the human-readable receipt with fallback values and false field-presence flags, even though the score and canonical identity state used actual values. Its `belief_source` / `resource_source` labels could say `provided` while `field_presence` claimed the mappings were absent.

The scheduler also put the computed `fusion_state_id` on the evidence record without attaching `fusion_state_witness`, even though the lineage tests and the evidence contract expect a historical witness from which the digest can be independently recomputed.

This exposes a distinct failure mode from hash tampering. The canonical witness can be correct while the adjacent narrative receipt is wrong, because the score, explanation, and witness were assembled through separate call paths.

## Integrated closure

A common `build_fusion_receipt` constructor now builds three linked outputs from one identical input context:

1. the evidence record, including the actual symbolic/neural context and presence metadata;
2. the canonical identity witness;
3. the `fusion_state_id` digest, with the exact witness attached to the evidence record.

Both `apply_fusion` and the simulation scheduler use this constructor. The helper is present in all three maintained fusion copies (backend, primary bridge, and master bridge). The scheduler forwards the actual belief/resources, core, base entropy, coupling, stress residual, mood labels, and provenance rather than falling back to the evidence builder's defaults.

Regression checks in `backend/test_cyclekernel_descent.py` and `backend/test_fitness_lineage.py` assert that recorded symbolic values and field presence match the live civilization, that neural context is retained, and that witness fields agree with evidence inputs. Existing lineage assertions recompute the fingerprint from `fusion_state_witness`.

## Mathematics

Let (z) be the exact context used for a fusion cycle. Let (E(z)) be its readable evidence projection and (W(z)) its canonical identity witness. The receipt contract is:

\[
E_{\text{inputs}}=\Pi(W),\qquad
\operatorname{SHA256}(\operatorname{canon}(W))=\text{fusion\_state\_id}.
\]

The critical condition is that (E) and (W) derive from the same (z), not from separate contexts (z_E) and (z_W). A self-consistent hash proves only that the stored witness matches the digest; it does not prove that nearby explanatory fields describe that witness. The common builder makes the input context shared by construction, while regression tests check representative projections.

CycleKernel's legacy score remains

\[
N=\sqrt{s n},
\]

and the existing mood/promotion thresholds remain unchanged.

## Great Scale mapping

This extends **System 25 — Typed Observation and Missingness** into **System 26 — Evidence/Identity Concordance**:

- **State:** actual scored inputs and effective neural context.
- **Evidence:** human-readable values, source labels, and field-presence metadata.
- **Witness:** canonical fingerprint material.
- **Integrity invariant:** evidence input projections agree with the witness, and the witness recomputes to the reported digest.

Great Scale's separate geometric relation remains unchanged:

\[
S(h)=h(1-h),\qquad
\Psi=\phi^{-2}+S(h)\geq\phi^{-2}.
\]

The risk-envelope result from Descent LVII is also unchanged. Its typed certificate must travel with the feasible moment set, support margin, extremal witness, method, and proof status—not as a bare scalar. The common idea across the two repositories is that the output value alone is insufficient; the conditions that produced it must remain observable and internally consistent.

## Scientific and security boundary

This is a data-integrity contract. It does not establish empirical calibration, a new physical law, or upstream publisher authenticity. A recomputable SHA-256 digest does not authenticate a relay; authenticated transport/workload identity and an operational missing-data policy remain necessary.

## Verification status

Source inspection confirms both the backend scheduler and all three fusion implementations call the common receipt constructor, and the new regression assertions are committed. A direct clone in the current execution environment failed because GitHub DNS resolution was unavailable. Recent GitHub Actions attempts have failed immediately with runner ID 0 and empty step lists; therefore the committed suite, Python compile checks, both Docker builds, and live relay smoke test are not reported as passed.


## Follow-on: policy-decision identity (Descent CIV)

Evidence/identity concordance must extend through policy consumption. The fusion-state ID describes the scored input but does not include whether the civilization was already promoted; hysteresis uses that prior state to select the active threshold. Descent CIV adds a separate `pd-` decision fingerprint and fixes the threshold metadata on a hold result. See [Descent CIV](DESCENT_CIV_PROMOTION_CONTEXT_CLOSURE.md).
