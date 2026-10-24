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
