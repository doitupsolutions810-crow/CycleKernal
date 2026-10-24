# Descent CIV — promotion-context closure for hysteresis

**Status:** policy-metadata correction and regression coverage added. The legacy fitness formula and promotion/demotion actions are unchanged; exact repository CI and Docker builds still require actual runner execution.

## Finding

CycleKernel uses a hysteresis policy: an unpromoted civilization becomes promoted at the upper threshold, while an already-promoted civilization is demoted only after falling below the lower threshold. Let (m) be the fused score, (a_t\in\{0,1\}) denote whether the civilization was promoted before the decision, and (	heta_p=0.62), (	heta_d=0.28).

\[
a_{t+1}=\begin{cases}
0,&a_t=1\land m<\theta_d,\\
1,&a_t=0\land m\geq\theta_p,\\
a_t,&\text{otherwise}.
\end{cases}
\]

The prior-state bit is therefore part of the decision context. Before this descent, a `hold` result always reported `PROMOTE_THRESHOLD` (0.62), even when (a_t=1) and the actual active boundary was the demotion threshold 0.28. That metadata could describe the wrong rule for a correct `hold` action.

A second observability gap followed: `fusion_state_id` fingerprints the scored state, not the policy context. Two equal fusion states with different prior promotion state can legitimately require different active thresholds; one identifier should not be presented as the identity of both computations and decisions.

## Integrated closure

- `promote_decision` now reports the demotion threshold for a held, already-promoted civilization and the promotion threshold for a held, unpromoted civilization. Actual decision conditions and thresholds are unchanged.
- The common `build_fusion_receipt` constructor adds a canonical decision witness containing the policy schema, fusion-state ID, raw fused value, prior promotion state, action, and active threshold.
- A type-distinct `promotion_decision_id` uses the `pd-` prefix and a full SHA-256 digest of canonical JSON. The existing `fusion_state_id` retains its `fs-` prefix and continues to identify the fusion computation.
- Both identities and the decision witness travel in fitness evidence. The simulation records the decision ID on civilization state, fusion events, promotion/demotion lineage, and colony snapshots. Both bridge responses expose the decision ID at top level.
- Regression tests assert the two identities remain distinct, the same fusion inputs may have one fusion ID but different decision IDs, each decision witness recomputes to its digest, and the active hysteresis threshold is correctly recorded across the backend and both bridges.

## Mathematics and Great Scale mapping

This extends System 25's typed-observation rule and Descent CIII's evidence/identity concordance into **System 27 — Policy Context and Hysteresis**.

For the active decision boundary,

\[
\theta_{\text{active}}(a_t)=
\begin{cases}
\theta_d,&a_t=1,\\
\theta_p,&a_t=0.
\end{cases}
\]

Let (F=\texttt{fusion\_state\_id}) identify the scored state. The decision witness is the canonical record

\[
D=(F,m,a_t,\text{action},\theta_{\text{active}},\text{schema}),
\]

and its identifier is

\[
\texttt{promotion\_decision\_id}
=\texttt{pd-}\operatorname{SHA256}(\operatorname{canon}(D)).
\]

Thus (F) can remain equal while the decision identity differs because (a_t) or its active threshold differs. This is intentional separation of computation identity from policy-decision identity, not score drift.

The Great Scale geometry remains unchanged:

\[
S(h)=h(1-h),\qquad
\Psi=\phi^{-2}+S(h)\geq\phi^{-2}.
\]

The risk-envelope certificate from Descent LVII is unchanged as well. Its bound, feasible moment set, support margin, extremal witness, method, and proof status remain a separate typed channel.

## Verification and trust boundary

The new tests cover both thresholds, identical fusion inputs with distinct policy contexts, digest recomputation, cross-copy parity, scheduler lineage, and bridge exposure. Source inspection confirms the common receipt constructor is used by `apply_fusion` and the scheduler.

Hosted Actions attempts continue to fail before runner assignment, with empty step lists; a clone attempt from this execution environment also failed at GitHub DNS resolution. Therefore this source integration is not reported as an executed repository test or successful build. The decision digest proves consistency with its stored decision witness, not publisher authenticity or authorization.
