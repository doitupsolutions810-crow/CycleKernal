# Great Scale–CycleKernel LVI: lossless fitness evidence

**Status:** software-integration proposal; not a claim of physical validation or a production run.

## Finding

CycleKernel's legacy fusion scalar is

[
g(s,n)=sqrt{s,n},
]

where (s) is the symbolic/resource score and (n) is the neural/LoopMem score. This is a many-to-one projection. For example,

[
g(0.9,0.4)=0.6=g(0.6,0.6),
]

but the channel ratio and signed imbalance differ:

[
eta=s-n:quad 0.5	ext{ versus }0,qquad
ho=s/n:quad 2.25	ext{ versus }1.
]

The downstream mood fusion (m=0.65g+0.35M) sees the same (g) and mood (M), so it cannot distinguish those two underlying states. The decision scalar is therefore not a lossless account of why a promotion was made.

## Companion evidence contract

The compatibility scalar `ns_fitness` and `mood_dot` remain unchanged. Each fusion additionally emits `cyclekernel.fusion-evidence/v1` with:

- `symbolic_score`, `neural_score`, `signed_eta = symbolic - neural`, and `absolute_channel_gap`;
- `symbolic_neural_ratio` plus `ratio_defined` (the ratio is `null` if the neural channel is zero or the ratio is not finite);
- origin of symbolic inputs and Great Scale residual;
- absolute distance and signed margin to promote (0.62), demote (0.28), convergent-label (0.70), and survival-label (0.30) thresholds;
- the existing Great Scale schema and normalized residual/entropy used by the fusion calculation.

A threshold margin is (m-	heta); a threshold distance is (|m-	heta|). Distances tell how close the state is to a boundary; signed margins tell which side it occupies. Neither replaces the current promotion policy.

## Integration

- The scheduler still performs one Great Scale descent tick per universe simulation cycle; its configured residual normalization remains restricted to the documented orbit.
- Every simulation fusion appends a bounded lineage event (maximum 500; snapshots expose the last 100), and promote/demote events carry the same companion evidence.
- Both CognitiveBridge runtime variants expose `metric_source` and the companion channel.
- If `RELAY_URL` is configured, metrics come from the WebSocket relay. Connection or schema failures do not silently substitute synthetic values; health becomes degraded/stale. Synthetic stream mode is explicitly labelled and used only when no relay URL is configured and `ALLOW_SYNTHETIC_RELAY` is enabled.
- A relayed Great Scale residual must declare `descent_schema = great-scale.descent/v0.4.2` and satisfy the ([0,7]) normalization domain. The bridge does not invent a residual from ordinary LoopMem mood values.
- Both bridge Dockerfiles include the fusion and descent modules, keeping the shipped image aligned with the source tree.

## Great Scale map

| Layer | State / invariant | Evidence emitted |
|---|---|---|
| Geometry | (x_{t+1}=4.5+0.5(x_t-4.5)) | source revision, residual and normalization |
| Symbolic | (sin[0,1]) | value and input-source metadata |
| Neural | (nin[0,1]) | value, entropy actually used, source metadata |
| Projection | (g=sqrt{sn}) | retained for compatibility |
| Companion | (eta=s-n, ho=s/n) where defined | identifiability diagnostics |
| Decision | (m=0.65g+0.35M) | margins and distances to all four thresholds |
| Lineage | ordered fusion / promotion event | cycle, civilization, genome ID, same evidence object |

This is a typed observation record, not an authorization credential, calibrated probability, or new physical law. In particular, the Great Scale cone floor ( Psigephi^{-2}) is not equated with CycleKernel's separate promotion threshold.

## Verification plan

The PR workflow runs:
1. the existing descent-engine, fusion, and scheduler integration tests;
2. tests for the non-injective scalar example and all threshold diagnostics;
3. relay JSON/schema/range validation and explicit live-versus-synthetic provenance tests;
4. Python byte-compilation and Docker builds for both bridge variants.

CI success and a live relay run are separate questions. Until the hosted workflow executes its steps and a configured relay is exercised, those outcomes must not be reported as verified.
