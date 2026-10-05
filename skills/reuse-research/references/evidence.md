# Evidence and adoption decisions

Saved captures are checked against their UTF-8 text SHA-256 before review/cache use. This detects inconsistent local records, not remote authenticity. An `inspected` capture must cite a GitHub blob URL, raw file URL, or contents API URL whose immutable commit ref matches its recorded 40-hex `revision`. Branch URLs and mismatched refs can retain weaker documented observations; they cannot pass the inspected pin check. Git blob object hashes do not establish a commit binding.

## Two independent dimensions

| State | Meaning |
| --- | --- |
| supported | Evidence supports the scoped requirement; limits recorded. |
| partial | Supports part of the requirement; identify the remainder. |
| contradicted | Observed evidence conflicts with the requirement. |
| unknown | Available evidence does not settle it. |

| Method | Meaning |
| --- | --- |
| documented | Primary documentation/API examples claim behavior. |
| inspected | Code, tests, manifests or history were read. Unrun tests show intended coverage, not a passing result. |
| tested | A named experiment executed at a stated revision/environment; record result and limited scope. |

A finding can have multiple methods. Model confidence, result rank and popularity are not verification methods. A failed request is unknown, not contradicted. Grounded identity does not establish fit/installability.

## Verify relative to intended use

For serious dependency/adaptation candidates, identify decisive gates: functionality, runtime/platform/version, integration/deployment, applicable license obligations, maintenance and operational constraints. Add security/governance checks proportional to task consequences. Existing user constraints determine eligibility; avoid unrelated enterprise requirements.

Inspect license material and relevant distribution/dependency context; license presence alone does not establish suitability. Preserve unresolved obligations as unknown. Decisive conflicts reject that role; decisive unknowns keep adoption provisional.

Read implementation/tests for critical behaviors, error handling, state boundaries, platform assumptions and fallbacks. Compare docs with extension points. Preserve useful code/tests even when adoption fails. Missing a searched test is a gap unless a sufficiently examined scope supports the bounded finding.

Assess releases, substantive changes, maintainer responses and dependency support. Recent commits may be automation; low activity may reflect stability. Issue counts and star ratios alone cannot establish responsiveness. Label dated signals accurately, avoiding a single health score.

Study references may remain useful despite age, archive state, language/framework differences or adoption incompatibility. Record transferable behavior/design, the handled cases, source/test evidence, assumptions, and the adaptation or reimplementation needed. Evaluate this against the subtask, independently of integration fit. Different implementation languages do not by themselves rule out adoption either: an SDK, protocol, CLI or worker boundary may make integration practical. Verify the actual interface and operating cost. Copying/adaptation still needs applicable eligibility checks and ownership-cost analysis; conceptual learning is a distinct role.

## Evidence record

Attach requirement ID, candidate role/version/revision, state, method, primary URL or inspected local path, observation date, evidence summary and limits. Prefer commit-pinned source/test links. Issue reports retain their affected version and resolution status, distinct from current behavior.

Record observed cases from code, tests or reports, along with uninvestigated behavior. A case inventory is not proof of exhaustive corner-case coverage.

## Integration and experiments

Compare glue code/configuration, runtime/deployment burden, adaptation changes, upgrades and ongoing ownership with building the gap. Use qualitative effort with reasons unless measured.

For a decisive unknown, specify input/condition, candidate revision/environment, expected behavior, observable acceptance criterion and the decision affected. Mark proposed, attempted, failed or passed. A successful example does not establish unrelated production readiness.
