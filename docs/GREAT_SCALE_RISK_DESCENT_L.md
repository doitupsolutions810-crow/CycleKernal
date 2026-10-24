# Great Scale — Risk Descent L: Moment Aliasing and Tail Risk

**Status:** additive research note; non-canonical; no runtime policy change.  
**Scope:** mathematical risk model and its safe relationship to the CycleKernal geometric descent adapter.

## Finding

The pair of summary statistics `(p, v) = (E[P], Var(P))` does not identify the exact expected logarithmic loss

\[
J(P) = E[-a\ln(1-P)], \qquad 0 \le P < 1, \quad a>0.
\]

The second-order Taylor estimate is

\[
J_2(p,v)=a\left[-\ln(1-p)+\frac{v}{2(1-p)^2}\right].
\]

This is an approximation, not a distribution-free upper bound. Two distributions can share the same mean and variance and still have different exact risk because the nonlinear loss depends on distribution shape and tail mass.

## Deterministic counterexample

For \(a=1\), each distribution below has \(E[P]=0.5\) and \(\operatorname{Var}(P)=0.04\). Each therefore receives the same Taylor estimate:

\[
J_2(0.5,0.04)=\ln 2+0.08\approx0.773147180560.
\]

| Distribution | Atoms (value, probability) | Third central moment | Exact expected loss | Exact − Taylor |
|---|---|---:|---:|---:|
| Symmetric | (0.3, 0.5), (0.7, 0.5) | 0 | 0.780323874132 | +0.007176693573 |
| Positive skew | (0.4, 0.8), (0.9, 0.2) | +0.012 | 0.869177517612 | +0.096030337052 |
| Negative skew | (0.1, 0.2), (0.6, 0.8) | −0.012 | 0.754104688631 | −0.019042491929 |

The exact expected losses span approximately **0.115072828981**, despite identical first two moments. The approximation both underestimates and overestimates across these examples. The third central moment helps diagnose asymmetry, but it does not uniquely determine the full distribution or guarantee an approximation-error bound.

## Boundary descent: a stronger failure mode

For \(f(P)=-\ln(1-P)\), the curvature is

\[
f''(p)=\frac{1}{(1-p)^2},
\]

which diverges as \(p\to1^-\). For a two-point distribution with fixed \(\mu=0.5\), \(v=0.04\), and upper atom \(x\), choose

\[
y=\mu-\frac{v}{x-\mu}, \qquad
q=\frac{v}{(x-\mu)^2+v}.
\]

Then \(E[P]=\mu\) and \(\operatorname{Var}(P)=v\) while \(x\to1^-\), \(q\to0.137931\ldots\). A non-vanishing probability mass approaches a singular-loss boundary, so \(E[f(P)]\to\infty\), although the moment-only Taylor estimate stays at about 0.773147. This proves that the estimate is not a safe worst-case risk bound without extra distributional assumptions.

## Great Scale map

```text
                  TAIL / BOUNDARY AXIS
                         x → 1⁻
                  f(x) = -ln(1-x) → ∞
                         q → 0.137931…
                              │
                              ▼
  MOMENT BASE ───── SAME PROJECTION ───── HIDDEN RISK
  E[P] = 0.5          Var(P) = 0.04        E[f(P)] differs
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
             CVaR / ES              Support margin
          observe worst tail       require P ≤ 1−ε
                                   loss ≤ −ln ε
```

| Great Scale layer | Mathematical object | Operational meaning |
|---|---|---|
| Base coordinates | \((p,v)=(0.5,0.04)\) | First two moments only |
| Hidden axis | Distribution shape and tail mass | Information lost by moment projection |
| Curvature marker | \(f''(p)=a/(1-p)^2\) | Sensitivity grows near the boundary |
| Anomaly | Same \((p,v)\), different \(J(P)\) | Moment-only state is not decision-sufficient |
| Risk controls | CVaR/expected shortfall; \(P\le1-\epsilon\) | Explicit tail monitoring and a valid support margin |
| Promotion gate | Declared family or proved error bound | Do not turn an approximation into a safety guarantee |

## Relationship to the current CycleKernal adapter

The open integration branch wires a *different* descent object: a deterministic modular involution/contraction with state \(x_t\), raw residual \(r_t=|x_t-I(x_t)|\), and bounded normalized residual on its configured orbit. That geometric residual is **not** a probability distribution \(P\), and its variance is not automatically the \(v\) in the risk model above.

Therefore:

1. Keep the geometric `DescentEngine` and the risk functional \(J(P)\) as separate typed concepts.
2. Do not substitute \((p,v)\) estimates for exact risk, or reinterpret `stress_residual` as a probability, without an explicit data contract.
3. Before a risk score can influence entropy, promotion, or a production decision, define what random variable \(P\) means, how its distribution is estimated, the support guarantee, and the loss coefficient \(a\).
4. Prefer exact expectation under a validated distribution family; otherwise report a conservative bound with declared assumptions. Add CVaR/expected-shortfall and a support-margin check where applicable.
5. Keep this result advisory until the existing objective-sign convention and operational meanings of \(p\), \(v\), and \(A_\star\) are resolved.

## Cross-layer control finding: descent must preserve prior state

The fusion wrapper originally computed the prior-state flag as `promoted and fused >= PROMOTE_THRESHOLD`. That condition made the state transition internally inconsistent: when a previously promoted colony's score fell below the promotion threshold, the wrapper erased its prior promoted state before calling the transition function. The demotion rule (`fused < DEMOTE_THRESHOLD`) could therefore be bypassed and the wrapper return `hold`.

The corrected branch passes the persisted state alone: `already_promoted=bool(colony.get("promoted", 0))`. The transition function then applies its own thresholds:

```text
prior state = promoted AND F < 0.28  -> demote
prior state = not promoted AND F >= 0.62 -> promote
otherwise -> hold
```

This is a control-theoretic lesson for the Great Scale map: **state and score are separate coordinates**. The score is the observation; prior promotion status is the state variable. Reconstructing state from the current score destroys hysteresis/transition semantics. Great Scale's stress residual can alter entropy and therefore fitness, so this bug is relevant even though the geometric residual is not the probabilistic risk variable (P) in the logarithmic-loss analysis.

Regression tests for promoted-low-score demotion, unpromoted-high-score promotion, and unpromoted-low-score hold are now committed on the feature branch. The hosted workflow still reports failure with zero executed steps; these tests are added but not yet verified by a successful repository run.

## Test and verification record

The upstream audit receipt reports `python descent50.py` **PASS 6/6**, earlier Descent XLV–XLIX checks passing their listed counts, and `python -m compileall -q .` passing in the audit package. Those are the receipt's reported results; this note does not claim to have rerun those scripts in the CycleKernal checkout.

The existing CycleKernal integration PR has a dedicated workflow for descent, fusion, and scheduler tests. Its latest observed hosted run failed with `startup_failure` and **zero job steps**, so it provides no pass/fail evidence about the test code itself. A retry was requested, but the workflow remained failed at startup. Do not infer successful integration from that run.

### Acceptance tests required before operational use

- Verify the three distributions have valid probabilities, support in \([0,1)\), mean 0.5, and variance 0.04.
- Verify the same Taylor estimate is produced for all three and exact expectations differ by the reported spread within a declared tolerance.
- Verify the upper-atom family preserves moments while exact expected loss grows as \(x\to1^-\).
- Verify invalid or missing support margins fail closed; do not silently clip unsupported inputs.
- Verify risk state is typed separately from the geometric residual and cannot change promotion decisions until policy approval.
- Run the full unit/integration workflow successfully on a functioning runner, then perform security review and staging validation before deployment.

**Scientific boundary:** this is a deterministic mathematical/software counterexample under the stated assumptions. It is not an empirical physical experiment, a new physical law, or evidence of consciousness.
