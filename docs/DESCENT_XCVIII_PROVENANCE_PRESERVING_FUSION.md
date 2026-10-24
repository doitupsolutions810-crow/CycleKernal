# Descent XCVIII — Provenance-preserving neuro-symbolic fusion

**Status:** code-level engineering finding with regression tests. This is not a physical law.

## Finding

CycleKernel computes neuro-symbolic fitness as a geometric mean,
[
N = \sqrt{s n},
]
where (s) is the symbolic score and (n) is the neural score, then computes
[
M=\operatorname{clip}(0.65N+0.35m)
]
for mood score (m). Colony promotion depends on (M\geq0.62), while an already-promoted colony is demoted when (M<0.28). Mood relabels use (M<0.30) and (M\geq0.70).

The map ((s,n)\mapsto\sqrt{sn}) is non-injective: ((0.5,0.5)), ((0.25,1)), and ((1,0.25)) all produce (N=0.5). When (m=0.5), all yield (M=0.5). The scalar preserves a product-like summary, not the source contribution or which side is weak.

## Repository-specific defect discovered

In the bridge path, `apply_fusion()` called `ns_fitness(core=..., entropy=..., coupling=...)` without passing the available `belief` and `resources` mappings. As a result, it silently used default symbolic inputs:
[
s=0.55(0.5)+0.45\left(0.45\frac{50}{150}+0.35\frac{20}{40}+0.20\frac18\right)=0.4325.
]
That symbolic value was invariant across bridge heartbeats unless explicit symbolic inputs were wired through. The default value is still supported for backward compatibility, but the new channel labels it `default-fallback`; nested `metrics.belief` and `metrics.resources`, when present, are now passed through and recorded.

A second drift was found in `master/src/bridge/ns_fusion.py`: its `apply_fusion()` invoked `ns_fusion()`, which is not defined in that module. The change corrects the call and adds a test that loads every maintained copy to prevent regression.

Both reviewed bridge main modules generate synthetic heartbeats rather than consuming a real external WebSocket relay. Their test stream is now explicitly tagged `telemetry_source: synthetic`. This change does not claim the real relay has been integrated or certified; measuring synthetic-versus-live distributional differences is a separate next stage.

## Companion-channel contract

Every bridge fusion result now includes `companion_channel` with schema `cyclekernel.ns-fusion-companion/v1`:

- unrounded `symbolic_score` and `neural_score`;
- `ns_fitness`, mapped `mood_score`, and unrounded `mood_dot`;
- `symbolic_source`: `provided`, `partial-default`, or `default-fallback`;
- `telemetry_source`: explicit source, `synthetic`, or `unspecified`;
- the symbolic and neural inputs used to compute the result;
- thresholds and four signed distances: promote (M-0.62), demote (M-0.28), survival label (M-0.30), convergent label (M-0.70).

Distances are in normalized score units. Positive means above that threshold; negative means below. The existing rounded summary fields and the thresholds themselves are unchanged. Raw diagnostics are additional, not a replacement for the score.

The Flask simulation path records this channel per civilization using its actual belief/resources. The two bridge `CognitiveState` outputs surface it to HTTP/WebSocket consumers. Duplicated fusion implementations remain for compatibility, and the regression suite checks that each copy emits the same contract.

## Mapping to Great Scale

Great Scale's QGT bridge uses
[
S_Q=\frac14\frac{\det Q}{\det g}=\frac{R}{4},
\qquad \Psi_Q=\phi^{-2}+S_Q.
]
That is a useful scalar projection, but it intentionally discards curvature sign and absolute scale. Neuro-symbolic fusion has the same mathematical shape of problem: the scalar (N=\sqrt{sn}) does not identify the pair ((s,n)).

The corresponding Great Scale extension is to preserve the full evidence tuple alongside its projection:
[
X_{NS}=(s,n,N,m,M,\Delta_{0.62},\Delta_{0.28},
\Delta_{0.30},\Delta_{0.70},\pi),
]
where (pi) is input provenance. It does not redefine (S_Q), the original phase state, or the Great Scale cone. It makes explicit what the compressed value cannot tell us.

**Proposed Great Scale layer: System 24 — Provenance-Conditioned Projection.** A projected score is an observation; its companion channel states input attribution, decision margins, and provenance. High score is not the same as high evidence quality.

## Verification

Run the NS fusion unit tests:
```bash
make test-ns
```

Syntax-check the Python modules:
```bash
python -m compileall -q src/bridge backend master/src/bridge
```

Tests cover component attribution, default-fallback visibility, the four threshold margins, scalar non-identifiability, and parity across all three maintained fusion copies. The new GitHub Actions workflow runs the same suite on pull requests and pushes to `main`.

The current execution environment could not clone GitHub (DNS/network resolution failed), so I do not claim a local run of the repository's test files. The branch's Actions result is the source of truth for a full execution; a job with no assigned runner and no executed steps is not a passing test.
