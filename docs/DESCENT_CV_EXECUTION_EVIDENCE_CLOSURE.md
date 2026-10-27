# Descent CV — execution-evidence closure

**Status:** CI diagnosis and verification contract. This is an operational finding, not a passing code/test claim.

## Finding

The recent Actions runs for CycleKernal's `Great Scale descent integration` and Great Scale's `Great Scale build and tests` fail before executing any steps. The job payloads report `runner_id = 0`, empty runner names, and `steps = []`. This is not evidence of a Python/Node assertion failure, compile error, or Docker build failure; none of those operations ran.

The adjacent `swarm-vm-runner` repository explains the likely infrastructure cause:

- Its README says hosted Ubuntu pools have failed with `runner_id 0` and recommends the labels `[self-hosted, linux, control12]`.
- Its `SUCCESS_CRITERIA.md` explicitly considers both a not-yet-registered self-hosted runner and hosted `runner_id: 0` jobs to be degraded states, not required system failures.
- Its compose environment defaults the runner to `control12-workspace`, with labels `self-hosted,linux,x64,control12,swarm`; registration is repository-scoped in `runner/entrypoint.sh`.

So the strongest supported conclusion is **execution capacity/configuration is blocking verification**. I cannot independently query the registered-runner inventory through the available GitHub connector; therefore this note does not claim that no runner exists, only that the observed runs were never assigned one.

## Why the workflow was not blindly switched to self-hosted

Both target repositories are public and their workflows use `pull_request` triggers. A self-hosted runner executes repository code on its host; the supplied runner service also mounts `/var/run/docker.sock`. Routing arbitrary public PR code to that runner before trust and isolation controls are configured can expose the host and Docker daemon.

Additionally, the example runner configuration defaults to `control12-workspace`, not these two target repositories. Simply replacing `ubuntu-latest` with `[self-hosted, linux, control12]` without provisioning an authorized runner for each repository would move the job from immediate failure to indefinite queueing, not create a test pass. The workflow target should only change after runner registration scope, trusted-event policy, and host isolation are confirmed.

## A typed verification record

A job conclusion by itself is not enough to identify whether code was tested. Use the record

\[
Q=(H,R,A,\mathcal{S},C),
\]

where (H) is the tested commit SHA, (R) is the workflow/run/attempt identity, (A) is runner assignment, (\mathcal{S}) is the set of executed step results, and (C) is the overall conclusion.

Classify it as:

- **Verified pass:** the expected source SHA ran on an assigned runner and every required test/build step completed successfully.
- **Code/build failure:** a runner was assigned and at least one actual test/build step failed.
- **Execution blocked:** no runner was assigned or no required step executed.

The current CycleKernal and Great Scale jobs belong to the third category. A separate Vercel build-rate-limit status on Great Scale is a deployment/build-service status, not evidence that the Python/Node CI steps ran.

## Safe route to an actual run

1. Provision a trusted ephemeral runner in the existing `swarm-vm-runner` environment for the specific target repository (or use a properly scoped trusted runner group); the current example defaults to `control12-workspace`.
2. Mint a short-lived registration token for that repository using the existing `scripts/mint-runner-token.sh`; keep the token and GitHub credential in ignored local environment/configuration, never in source control or logs.
3. Do not allow untrusted external `pull_request` jobs to execute on a Docker-socket-enabled runner. Use hosted CI for public PR validation where available, or run trusted branch/manual builds in an isolated runner with no sensitive credentials.
4. Once a runner is registered and permitted to accept the intended event, execute the Python suites, relay tests, byte-compilation, and both Docker builds. Preserve the exact SHA and step logs in the verification report.

## Great Scale mapping

This is **System 28 — Execution Evidence and Proof-of-Run**. It extends System 25 typed observation, System 26 evidence/identity concordance, and System 27 policy-context identity: a claimed result must identify not only what was computed and decided, but whether the verification procedure actually executed.

Great Scale's geometry remains unchanged:

\[
S(h)=h(1-h),\qquad
\Psi=\phi^{-2}+S(h)\geq\phi^{-2}.
\]

The Descent LVII risk certificate also remains separate from CI state: (U_*(\varepsilon)), its feasible moment set, support margin, extremal witness, method, and proof status describe the analytic bound. A source-level proof, isolated arithmetic harness, and a repository-run test/build are distinct evidence classes and must not be collapsed into one `verified` label.

## Current verification boundary

The latest source audit confirms the shared fusion receipt, state witness, and separate promotion-decision fingerprint are integrated on the open CycleKernal PR; the Great Scale note cross-links the result. Hosted Actions still has not executed the repository steps. The new application code and newly added regressions are therefore source-integrated but not yet full-suite/build verified.


## Follow-on: typed numerical admission (Descent CVI)

Execution evidence is only useful if malformed values cannot enter scoring through implicit coercion. Descent CVI closes the `bool`/string-to-number conversion path across nested symbolic fields and top-level fusion metrics and adds cross-copy regression assertions. Full repository execution remains pending an assigned runner. See [Descent CVI](DESCENT_CVI_TYPED_NUMERIC_ADMISSION.md).
