# Descent CVII — validation frontier and lossy normalization

**Status:** architecture invariant derived from a concrete relay-path defect; implementation and regression coverage are integrated. Repository CI/builds remain unverified because the Actions jobs still fail before executing steps.

## Finding

Descent CVI introduced strict numeric admission in the fusion layer. A path audit then found the bridge relay normalizer performed `float(raw)` first. That erased the original JSON type before the downstream guard ran, so a boolean `true` became `1.0`, and the string `"0.5"` became `0.5`. The later type gate could no longer tell those malformed raw values apart from valid JSON numbers. The same pattern affected the optional Great Scale `stress_residual`.

The primary and master bridge parsers now call the shared `_json_number` guard on each raw metric before converting it to a float; they also apply it to the optional residual. Regression tests exercise booleans, numeric strings, huge integers, and primary/master parser parity.

## The general invariant

Let (X) be raw inputs and (N:X\to Y) a normalization function. Here (N) includes conversion to floating point. If (N) is non-injective, there can be distinct inputs (x_1\ne x_2) with (N(x_1)=N(x_2)). Any validator (V) that sees only (N(x)) cannot recover the information erased by (N):

\[
x_1\ne x_2,\quad N(x_1)=N(x_2)
\quad\Longrightarrow\quad
V(N(x_1))=V(N(x_2)).
\]

For example,

\[
N(\texttt{true})=1.0=N(1),\qquad
N(\texttt{"0.5"})=0.5=N(0.5).
\]

Therefore the correct validation order is:

\[
\boxed{
\text{raw parse}
\to\text{type admission}
\to\text{domain validation}
\to\text{normalization}
\to\text{scoring}
\to\text{witness/fingerprint}
}
\]

Type admission after normalization is too late whenever the normalization collapses input distinctions.

## Cross-descent closure

This principle generalizes earlier work:

- **System 25 — typed observation/missingness:** distinguish absent, empty, and explicit-null values before defaults collapse them.
- **System 26 — evidence/identity concordance:** generate the receipt and canonical witness from the same scored context.
- **System 27 — policy-context identity:** hash the prior-state bit and active hysteresis threshold separately from the fusion state.
- **System 28 — execution proof:** distinguish a failed test from a job that never executed.
- **System 29 — typed numerical admission:** reject booleans, numeric strings, non-finite values, and values outside the schema.
- **System 30 — validation frontier:** perform schema and domain admission before any lossy transformation.

The shared theme is information preservation at boundaries. Once a distinction is erased, downstream hashes, scores, and reports cannot reliably reconstruct it.

## Great Scale mapping

The existing geometric relation remains unchanged:

\[
S(h)=h(1-h),\qquad
\Psi=\phi^{-2}+S(h)\ge\phi^{-2}.
\]

The Descent LVII risk-envelope asymptotic is unchanged too. Its proof object remains separate from the software input-validation contract.

System 30 does not claim a new physical law. It specifies a software correctness condition: **validate in the richest representation available, then normalize; never rely on a downstream layer to infer erased input semantics.** The score formula (N=\sqrt{s n}) and promotion/demotion thresholds remain unchanged.

## Test, verify, run, build

Source inspection confirms both bridge parsers use the shared strict-number helper before float normalization, all three fusion copies use the same helper, and regression tests cover invalid values plus primary/master parser parity. An independent numeric-admission harness passed for valid integers/floats, booleans, strings, nulls, non-finite values, range violations, and oversized integer overflow.

The committed repository suite, Python compilation, and Docker builds are **not** reported as passing: current GitHub Actions jobs return failure with no executed steps. The source integration and independent harness are evidence of narrower scope, not a substitute for the repository run.
