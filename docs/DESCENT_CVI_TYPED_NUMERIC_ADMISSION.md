# Descent CVI — typed numerical inputs and scoring admission

**Status:** validation hardening and regression coverage integrated. The legacy fitness equation and thresholds are unchanged. Full repository test/build execution remains blocked by runner assignment.

## Finding

The input validator previously coerced supplied values with `float(value)`. In Python, booleans are accepted by this conversion: `float(True) == 1.0` and `float(False) == 0.0`. Numeric strings such as `"0.5"` also convert. A JSON value with the wrong type could therefore pass a “finite numeric” check and influence scores rather than fail closed. Example: `{"belief": {"truth": true}}` could be scored as truth = 1.0.

The gap affected more than nested belief/resource values. The score path also converted `Core`, `L5`, `L2`, and `stress_residual` before preserving their original types, while `neural_score` accepted values that could be coerced implicitly.

## Integrated correction

All three maintained `ns_fusion.py` implementations now share the same contract:

- `_json_number(value, label)` accepts JSON numeric types (integer or floating-point) but rejects booleans and strings before coercion.
- Belief `truth`/`deception` and resource `attention`/`compute`/`memory_nodes` are type-checked before range checks.
- Direct neural-score inputs and top-level fusion metrics `Core`, `L5`, `L2`, and `stress_residual` are checked before they are converted or used.
- Existing finite/range constraints remain in place; valid numeric inputs keep the same score formula, mood weights, and promotion thresholds.

Regression coverage now checks booleans, numeric strings, and parity across backend, primary bridge, and master bridge implementations. The validation rejects a malformed type instead of turning it into a score-bearing zero or one.

## Mathematics and Great Scale mapping

This is **System 29 — Typed Numerical Admission**, extending System 25 (missingness), System 26 (evidence/identity concordance), System 27 (policy context), and System 28 (execution proof).

Let (x) be a raw JSON field and (T) the schema's numeric type admission function:

\[
T(x)=
\begin{cases}
x,&x\in\mathbb{R}\text{ encoded as a JSON number and finite},\\
\text{reject},&x\text{ is a boolean, string, null, or non-finite}.
\end{cases}
\]

Then the domain constraint is applied after type admission; for belief values, (0\le T(x)\le1), while resource counts require (T(x)\ge0). Type admission must precede arithmetic so a boolean cannot silently acquire the meaning of a numeric confidence or resource amount.

The downstream equations remain:

\[
N=\sqrt{s n},\qquad m=0.65N+0.35M,
\]

with existing promotion threshold (0.62) and demotion threshold (0.28). No policy recalibration is inferred from the validation change.

Great Scale's geometric relation remains unchanged:

\[
S(h)=h(1-h),\qquad\Psi=\phi^{-2}+S(h)\ge\phi^{-2}.
\]

The LVII analytic envelope remains a separate proof object. Type-valid input data, a mathematically correct envelope, and a repository test run are separate evidence layers; each needs its own witness.

## Verification boundary

Source inspection confirms the helper and checks exist in all three fusion copies and that the tests cover invalid numeric types. Hosted Actions remains unable to allocate a runner (the returned jobs have empty step lists). These changes are source-integrated, but the full CycleKernal suite, compile step, and Docker builds are not reported as passed until actual execution evidence is available.


## Relay-ingress closure

The first strict-type guard still had a normalization bypass: `normalize_relay_metrics()` converted `Core`, `U2`, `L2`, `L5`, and the optional `stress_residual` to floats before fusion received them. A boolean or numeric string could therefore lose its original type at the bridge boundary. Both primary and master relay parsers now call the shared `_json_number` guard on the raw field before conversion and distinguish an omitted required metric from an explicitly supplied null. Regressions cover both parser copies, booleans, numeric strings, and oversized integers.


## Follow-on: validation frontier (Descent CVII)

The original numeric type guard also had to be placed before relay normalization; otherwise `true` and `"0.5"` had already become floats when fusion saw them. Both bridge parsers now validate raw values using the shared helper. Descent CVII formalizes the non-injective-normalization invariant and maps it to Great Scale System 30. See [Descent CVII](DESCENT_CVII_VALIDATION_FRONTIER.md).
