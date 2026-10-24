# Descent XCVIII — Channel observability for neuro-symbolic fusion

**Status:** algebraic result plus software diagnostics. This is not a new physical law or an empirical claim.

## Repository finding

CycleKernal's `ns_fitness` projects symbolic and neural scores into a geometric mean; `fuse_mood` then combines that scalar with mood, and the promote/demote controller acts on the resulting `mood_dot`. The previous result did not expose the component scores alongside that scalar. Also, `apply_fusion` passed `already_promoted` only when the fused value was already at the promote threshold, which prevented its demotion logic from receiving the true promoted state. The same `ns_fusion.py` source is mirrored at `backend/ns_fusion.py`, `src/bridge/ns_fusion.py`, and `master/src/bridge/ns_fusion.py`; this change keeps all copies identical.

## Mathematics

Let the raw channel scores be (s,nin[0,1]), and let the geometric-mean projection be

[
sigma_{NS}=sqrt{sn}.
]

Many ordered pairs have the same projection because the level sets satisfy (sn=sigma_{NS}^2). The scalar alone does not identify the pair.

Retain the signed companion channel

[
delta_{NS}=s-n.
]

Then

[
(s+n)^2=(s-n)^2+4sn=delta_{NS}^2+4sigma_{NS}^2
]

and, since (s,nge0),

[
s=rac{sqrt{delta_{NS}^2+4sigma_{NS}^2}+delta_{NS}}{2},
quad
n=rac{sqrt{delta_{NS}^2+4sigma_{NS}^2}-delta_{NS}}{2}.
]

**Finding:** the scalar plus signed channel difference is sufficient to reconstruct the ordered pair. Exposing the named raw channels makes the semantics explicit; the signed delta enables auditing and the absolute gap (Delta=|s-n|) summarizes imbalance.

Example: ((s,n)=(0.9,0.4)) and ((0.6,0.6)) both have (sigma_{NS}=0.6), while their channel gaps are (0.5) and (0). A scalar-only gate treats equal projections as identical even when the underlying evidence differs.

The companion diagnostics include four signed margins:

[
m_{s,p}=s-	heta_p,quad m_{s,d}=s-	heta_d,quad
m_{n,p}=n-	heta_p,quad m_{n,d}=n-	heta_d
]

with existing thresholds (	heta_p=0.62) and (	heta_d=0.28). These are visibility diagnostics; they do not silently redefine the existing policy, which still acts on (mood_dot).

A promotion-collision audit finds pairs of promotion events whose rounded fused scores agree within tolerance while either raw channel differs by more than 0.30. This flags rank-collisions for review; it does not automatically block a promotion without calibration against operational outcomes.

## Mapping to Great Scale

The Great Scale state and laws remain unchanged:

[
S(h)=h(1-h),qquad Psi=phi^{-2}+S,qquad Psigephi^{-2}approx0.381966.
]

The structural mapping is:

| CycleKernal | Great Scale interpretation |
|---|---|
| Ordered pair ((s,n)) | Rich state before projection |
| (sigma_{NS}=sqrt{sn}) | Scalar shadow; non-injective projection |
| (delta_{NS}=s-n) | Signed contrast channel that restores pair identifiability |
| (Delta=|s-n|) | Explicit channel-gap diagnostic; analogous in role, not identical, to a Great Scale residual |
| Four channel-to-threshold margins | Distance-to-boundary observables |
| `mood_dot` | Downstream scalar used by the existing action policy |

For a display-only Great Scale-compatible encoding of agreement, define (D=Delta),

[
S_{mathrm{agree}}=operatorname{heat}!left(rac{1+D}{2}ight)
=rac{1-D^2}{4},qquad
Psi_{mathrm{agree}}=phi^{-2}+S_{mathrm{agree}}.
]

This is a derived visualization of agreement reserve, not a physical observable or an authorization condition. Use the raw gap (Delta), signed delta, thresholds, and event lineage for decisions and audits; never treat (Psi_{mathrm{agree}}) as permission to act. The QGT scalar in Great Scale remains distinct from these cognitive channels.

## Implementation and verification

- Emit both component scores, signed and absolute channel differences, and four threshold margins.
- Attach the evidence to every active civilization's per-cycle fusion record and to promotion/demotion events.
- Detect promotion collisions with equal fused output and (>0.30) divergence on either channel.
- Fix `apply_fusion` to pass the actual promoted state to the decision function.
- Pass optional nested `belief` and `resources` from the metrics input into symbolic scoring; legacy calls without them keep their default behavior.
- Keep the mirrored fusion modules byte-identical.
- Use `make test-ns` and `make build-ns`; the CI workflow runs both.

The live WebSocket relay/LoopMem stream remains unverified by repository unit tests. This patch verifies the local fusion logic and the emitted evidence structure; it does not claim the production metrics stream has been certified.
