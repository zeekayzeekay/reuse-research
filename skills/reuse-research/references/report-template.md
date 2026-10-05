# Durable research report

Use this structure; omit empty optional detail. Keep every important subtask and decisive unknown visible. Replace example identifiers with task-specific ones. This is a decision record, not a research transcript.

```markdown
# Reuse research: <feature>

Observed: <date/time/timezone>
Status: <complete within scope | budget-limited | access-limited>
Budget: <target; measured elapsed; observed tokens or unavailable>
Supersedes/reuses: <prior findings, or none>

## Brief
Task/context:
Stack/runtime/deployment:
Hard constraints:
Assumptions and consequential unknowns:

| Requirement | Required behavior | Importance/constraint |
| --- | --- | --- |
| R1 | ... | ... |

## Coverage and candidates
Stages: <retrieved / queued / reviewed / source-inspected / runtime-tested / recommended>
Requirement gaps: <no lead / unreviewed / partial / unsuitable / unknown / evidence-backed, with limits>
Evidence-card/source-capture record: <location or equivalent host-tool records>
| Subtask | Requirements | Candidate/version/revision | Role | Coverage/gaps |
| --- | --- | --- | --- | --- |
| S1 | R1 | ... | dependency/adaptation/study | ... |

## Evidence
| Requirement/gate | Candidate | State | Method | Source | Finding and limits |
| --- | --- | --- | --- | --- | --- |
| R1 | ... | supported/partial/contradicted/unknown | documented/inspected/tested | pinned link | ... |

Functional fit:
Adoption/maintenance assessment and observation date:
Study value, transferable ideas/cases and source evidence (including cross-stack references):
Assumptions and reimplementation/validation needed for those ideas:
Integration/ownership effort:

## Decisions
Whole-solution comparison: retain the protected shortlist before choosing the architecture. For each, state documented coverage/reuse role, primary source, assessment or named deferral, remaining implementation/ownership cost and next check. Compare the strongest whole bases with composing specialist components; documentation remains a relevance hypothesis until decisive behavior/eligibility checks pass.

| Subtask | Decision | Disposition | Why / remaining gap / next check |
| --- | --- | --- | --- |
| S1 | USE/ADAPT/CONTRIBUTE/FORK/STUDY/BUILD/DEFER | recommended/provisional | ... |

Rejected strong alternatives:
Queued/high-priority leads not inspected: <canonical identity, capability/role hypothesis, deferral reason and explicit unknowns, including leads outside the queue>
Selection accountability: <strict audit result/artifact and unresolved gaps>
Whole-purpose alternative: <primary documentation card and relevance reason, or explicit deferral>
Decisive experiments: <condition, expected result, decision affected, proposed/executed status>

## Revised implementation plan
Chosen components/interfaces:
References to study and lessons/tests to carry forward:
Remaining implementation:
Deferred decisions/prerequisites:

## Search boundary
Purpose/capability queries, integration-focused queries, sources/revisions reached:
Unavailable/failed checks and their effect:
Uninvestigated requirements/candidates:
Refresh conditions:
```

Supported findings do not imply tested integration when the method is documented/inspected. The handoff names decisions, critical uncertainty and report location. Already-authorized implementation proceeds on the reconciled plan.
