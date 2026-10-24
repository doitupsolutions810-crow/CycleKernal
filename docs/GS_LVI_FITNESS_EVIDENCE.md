# Great Scale–CycleKernel LVI: lossless fitness evidence

**Status:** software-integration proposal; not a claim of physical validation or a full production run.

## Finding

CycleKernel's legacy fusion scalar is

\[
g(s,n)=\sqrt{s\,n},
\]

where \(s\) is the symbolic/resource score and \(n\) is the neural/LoopMem score. This is a many-to-one projection. For example,

\[
g(0.9,0.4)=0.6=g(0.6,0.6),
\]

but the channel ratio and signed imbalance differ:

\[
\eta=s-n:\quad 0.5\text{ versus }0,\qquad
\rho=s/n:\quad 2.25\text{ versus }1.
\]

The downstream mood fusion \(m=0.65g+0.35M\) sees the same \(g\) and mood \(M\), so it cannot distinguish those two underlying states. The scalar is therefore not a lossless account of why a promotion was made.

## Companion evidence contract

The compatibility scalar ns_fitness and mood_dot remain unchanged. Each fusion additionally emits the cyclekernel.fusion-evidence/v1 schema with:

- symbolic_score, neural_score, signed_eta = symbolic - neural, and absolute_channel_gap;
- symbolic_neural_ratio plus ratio_defined (the ratio is null if the neural channel is zero or the ratio is not finite);
- origin of belief/resource inputs, metric-source provenance, and Great Scale residual source;
- absolute distance and signed margin to promote (0.62), demote (0.28), convergent-label (0.70), and survival-label (0.30) thresholds;
- the Great Scale schema and normalized residual/entropy used by the fusion calculation;
- input/output mood, whether the categorical label was projected, and which label threshold triggered it.

A threshold margin is \(m-\theta\); a threshold distance is \(|m-\theta|\). Distances say how close a score is to a boundary; signed margins say which side it occupies. Neither replaces the current promotion policy.

## State fingerprint and threshold projections

The content identity is distinct from a civilization's stable entity ID:

- fusion_state_id is fs- plus a full SHA-256 digest of canonical JSON containing both channels, their ratio/imbalance, effective inputs, source labels, stress, schema, and input/output mood.
- genome_id retains the familiar short gn- identifier for a derived state when no persistent colony identity is supplied; an explicitly supplied persistent colony ID remains the entity identity.
- mood_label_projected records when the fused value changes a categorical mood and identifies the threshold responsible. Numeric thresholds and decision policy are unchanged.

This exposes two separate information losses: the geometric-mean projection \((s,n)\mapsto\sqrt{sn}\), and the categorical projection from mood_dot to a mood label. Identical scalar values can have different fusion_state_id fingerprints. Neither a score nor a categorical label should be used to reconstruct the full state.

## Integration and trust boundary

- The scheduler still performs one Great Scale descent tick per universe simulation cycle; residual normalization is restricted to the configured orbit.
- Each simulation fusion appends a bounded lineage event (maximum 500; snapshots expose the last 100); promotion and demotion events carry the same companion evidence and state fingerprint.
- Both CognitiveBridge runtime variants expose metric_source, fusion_state_id, and the companion channel.
- If RELAY_URL is configured, metrics come from the WebSocket relay. Connection/schema failures do not silently substitute synthetic values; health becomes stale/degraded. Synthetic mode is explicitly labelled and only used when no relay URL is configured and ALLOW_SYNTHETIC_RELAY permits it.
- A relayed Great Scale residual must declare descent_schema = great-scale.descent/v0.4.2 and satisfy the configured \([0,7]\) domain. The bridge does not invent a residual from ordinary LoopMem mood values.
- Both bridge Dockerfiles include the fusion and descent modules.

**Important limitation:** metric_source is an operational provenance label, not cryptographic proof that a relay is trusted. The reviewed bridge validates the configured WebSocket URL's payload shape/range; the declared schema can be spoofed by an untrusted publisher. Production still needs a protected relay endpoint, TLS/authenticated workload identity or mTLS, secret handling, and network policy. The current ws:// compose example is suitable only for a protected network.

## Great Scale mapping

| Layer | State / invariant | Evidence emitted |
|---|---|---|
| Geometry | \(x_{t+1}=4.5+0.5(x_t-4.5)\) | source revision, residual and normalization |
| Symbolic | \(s\in[0,1]\) | value and input-source metadata |
| Neural | \(n\in[0,1]\) | value, entropy actually used, source metadata |
| Projection | \(g=\sqrt{sn}\) | retained for compatibility |
| Companion | \(\eta=s-n,\ \rho=s/n\) when defined | identifiability diagnostics |
| Decision | \(m=0.65g+0.35M\) | margins/distances to four thresholds |
| Lineage | ordered fusion/promotion event | cycle, civilization, stable genome ID, state fingerprint and matching evidence |

This is a typed observation and lineage record, not an authorization credential, calibrated probability, or new physical law. Great Scale's cone floor \(\Psi\ge\phi^{-2}\) is not equated with CycleKernel's separate promotion threshold.

## Test, verify, run, build

The branch workflow is configured to run:

1. descent, fusion, scheduler, and lineage tests;
2. non-injective scalar and full-fingerprint regressions;
3. relay JSON/schema/range and provenance tests;
4. Python byte-compilation;
5. Docker builds for both CognitiveBridge variants.

Focused local tests run on isolated copies of the descent and fusion modules passed **21/21** in the analysis environment. That is not a full CycleKernel integration run. The latest hosted Actions jobs still report failure with no runner assigned and empty step lists, so hosted CI and the Docker builds remain unverified. A live relay smoke test is also still required before operational promotion.


## Descent XCIX — validity and independently checkable witness

The companion evidence now carries the canonical state witness used to produce `fusion_state_id`. Consumers can recompute the SHA-256 fingerprint from the witness, while recognizing that digest consistency is not source authentication. Belief truth/deception must be finite and in [0,1], and resource counts finite and nonnegative; invalid values fail closed both at relay ingress and in the score function. See [Descent XCIX](DESCENT_XCIX_VALIDITY_WITNESS_CLOSURE.md).


## Descent C — typed missingness

The fusion contract now distinguishes an absent symbolic mapping (None, which uses the documented baseline) from an explicitly supplied empty object ({}, which is preserved as provided input). This prevents false source labels and keeps the recorded inputs consistent with the computed score and canonical witness across the backend and both bridge copies. See [Descent C — Typed missingness](DESCENT_C_TYPED_MISSINGNESS.md).


## Descent CI — field-presence closure

The canonical witness now includes mapping-level presence plus recognized-field presence, and preserves the validated belief.deception value even though the current score does not use it. This distinguishes equal-score inputs with different supplied data. See [Descent CI](DESCENT_CI_WITNESS_COMPLETENESS.md). This enriches the evidence record only; the fitness formula and promotion thresholds are unchanged.


## Descent CII — explicit-null closure

The core fusion entry point now distinguishes an omitted mapping key from a present key whose value is `None`/JSON `null`. Omitted keys keep the baseline; supplied mappings are validated and preserved; explicit null/non-mapping values are rejected rather than silently treated as absent. This closes the last non-injective fallback identified after Descent C and CI. See [Descent CII](DESCENT_CII_EXPLICIT_NULL_CLOSURE.md). Scoring and promotion thresholds are unchanged.


## Descent CIII — evidence/identity concordance

A common `build_fusion_receipt` constructor now creates the evidence projection and canonical witness together. It is used by both bridge/backend fusion and the simulation scheduler; the scheduler passes the same live belief/resources and neural context it scored, and the returned evidence includes the exact witness used to compute its digest. This addresses a source-level mismatch in which scheduler evidence could display defaults and false field-presence flags despite a fingerprint built from live inputs. See [Descent CIII](DESCENT_CIII_EVIDENCE_IDENTITY_CONCORDANCE.md). Scoring and policy thresholds remain unchanged; full hosted tests/builds are still pending actual runner execution.


## Descent CIV — promotion-context closure

Promotion is stateful hysteresis: the upper threshold `0.62` applies to an unpromoted civilization, whereas the lower threshold `0.28` governs demotion of an already-promoted one. A held, already-promoted state now reports `0.28` as its active threshold. The canonical decision witness and type-distinct `pd-` digest are stored separately from the `fs-` fusion-state fingerprint and included in simulation lineage and bridge responses. This preserves the legacy fitness score and policy actions while making the decision context auditable. See [Descent CIV](DESCENT_CIV_PROMOTION_CONTEXT_CLOSURE.md).


## Descent CVI — typed numerical admission

Nested symbolic inputs and top-level `Core`/`L5`/`L2`/`stress_residual` now reject booleans and numeric strings before numeric conversion. Python's `float(True)` evaluates to `1.0`, so coercion alone does not establish that a value has the expected schema type. The shared `_json_number` helper is mirrored in the backend and both bridge copies and is covered by cross-copy regressions. The legacy score formula and thresholds are unchanged. See [Descent CVI](DESCENT_CVI_TYPED_NUMERIC_ADMISSION.md).


The relay parser is part of the same typed-input boundary: both `src/bridge/main.py` and `master/src/bridge/main.py` now validate raw JSON metric types with the shared `_json_number` helper before normalization. This closes the path where a boolean/string was converted to a float before fusion's strict guard. See [Descent CVI](DESCENT_CVI_TYPED_NUMERIC_ADMISSION.md).
