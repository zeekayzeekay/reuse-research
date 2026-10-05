# Shared clock and compact handoff

Use `scripts/reuse_run.py` to record total elapsed time and assemble a source-backed report. Python 3.11+ standard library only. It does not run candidate code or install a background timer.

Start before framing, with the task's agreed total budget and reporting reserve:

```text
python <skill>/scripts/reuse_run.py start --task "Feature brief" --seconds 600 --reserve 90 --out <run>/clock.json
python <skill>/scripts/reuse_run.py status --run <run>/clock.json --acquisition
```

`start` refuses to overwrite an existing attempt. Use a separate clock for an authorized continuation, preserving its predecessor. `status --acquisition` exits nonzero at the acquisition cutoff; plain `status` allows reporting until the final deadline. After completion, acquisition stays closed.

Pass `--run <run>/clock.json` to `reuse_search.py search`; every participating search call clamps its allowance to the same remaining acquisition time. Before direct host web/source calls, checkpoint the clock and honor the result. Direct host tools and agent reasoning are outside the executable's enforcement; neither shared clocks nor API timeouts can terminate a host turn automatically.

Keep semantic screening bounded. Record concrete reasons for queued/high-priority leads and inspected alternatives, while retaining the complete ledger and a grouped remaining-pool deferral. The report includes a bounded list of unbriefed front-page leads; these are retrieval hints, not fit endorsements. This avoids writing hundreds of shallow disposition rows.

Protected `whole_shortlist` leads from [enrichment-cli.md](enrichment-cli.md) stay visible in checkpoints and receive a comparison table in the handoff. Their candidate records require `next_check` as well as an assessment/deferral reason; source text and identity must survive focused discovery and reranking. This retention does not require inspecting every alternative or establish adoption readiness.

Retain `component_leads` dispositions in selection records as described in [enrichment-cli.md](enrichment-cli.md). Snapshot and handoff show their exact source cues; a handoff with an unaccounted critical upstream cue stays unfinished. Resolve or explicitly defer the bounded leads within the same acquisition/report budget.

Save an initial recovery artifact immediately after discovery, then refresh it as cards become available:

```text
python <skill>/scripts/reuse_run.py snapshot --ledger <run>/final-ledger.json --briefs <run>/briefs.json --review <run>/final-review.json --run <run>/clock.json --out <run>/progress.md
```

Only ledger and out are required. A snapshot validates available cards, keeps every unbriefed front-page identity visible, and labels every requirement DEFER/provisional. It is explicitly unfinished: there is no semantic recommendation or strict selection reconciliation. It does not stop the run or reopen acquisition. Keep `progress.md` separate from the final report. If the total deadline arrives without a reconciled handoff, return the checkpoint with the unfinished status. Saving after the deadline returns exit 3 while preserving the artifact.

Write `decisions.json` with one row per requirement:

```json
{"decisions":[{"requirement":"R1","decision":"DEFER","status":"provisional","reason":"Deployment access remains unknown","next_check":"Run a representative input in the target environment"}]}
```

Allowed decisions are USE, ADAPT, CONTRIBUTE, FORK, STUDY, BUILD and DEFER. Status is provisional or recommended; the host must judge the evidence and decisive gates. The assembler validates structure and provenance, not the truth of that judgment.

Supply host-authored `context.json` (or the same object as `decisions.context`) so the final report retains task meaning and the revised plan. Each ledger requirement needs a `description`. State unknown stack/constraints explicitly when unavailable. Every requirement needs a plan action, including deferred experiments; evidence IDs must refer to actual cards. For example:

```json
{"goal":"Recover profile history across coding agents","stack":"Unknown; compare cross-stack study value","constraints":"Preserve provenance; integration remains untested","implementation_plan":[{"requirement":"R1","action":"Study the observed merge behavior, then validate an adapter against conflict fixtures","evidence_ids":["E1"]}]}
```

```text
python <skill>/scripts/reuse_run.py handoff --ledger <run>/final-ledger.json --briefs <run>/briefs.json --screened <run>/semantic-queue.json --review <run>/final-review.json --records <run>/selection-records.json --decisions <run>/decisions.json --context <run>/context.json --cases <run>/case-inventory.json --run <run>/clock.json --out <run>/report.md --audit-out <run>/selection-audit.json
```

Cases and clock are optional. Existing review/card and case checks run first. The report retains requirement descriptions, task context, the reconciled plan, card IDs/roles/source dates, case applicability and evidence links, selection reasons and boundaries. It displays the complete bounded front-page set, with fit unknown. Exit 0 means accounting and required report content passed and any supplied clock was within budget; exit 1 preserves an explicitly unfinished report and audit gaps; exit 2 means invalid inputs or failed persistence; exit 3 preserves the report but records a timing failure. `audit.accounted` measures selection only; `audit.handoff_complete` also requires context and plan. `audit.timing.deadline_met` and `clock.outcome` keep completeness separate from timing. The clock is completed only after the report and audit are saved. Without a clock, exit 0 is not evidence of deadline compliance.

Write records and decisions progressively. At the reporting reserve, use existing sources and explicit unresolved dispositions rather than acquiring more or revisiting the entire ledger. Run `handoff` once: it already validates cards, cases and strict accounting. Read its audit, repair genuine errors only within the remaining target, and return the artifact. Use the saved clock/audit for timing metrics instead of writing an extra accounting script. Final response latency is separate and still belongs in a parent end-to-end timing audit. A late valid handoff is still a timing failure.

For implicit invocation, the installed skill description and Codex policy expose the skill to selection. Model selection remains probabilistic. A consuming project's AGENTS.md or CLAUDE.md can reinforce routing with:

```text
Before planning or implementing a substantial feature, choosing a dependency, or working on an unfamiliar integration, use the installed reuse-research skill and reconcile the plan with its findings. Skip cosmetic changes and routine fixes; honor explicit requests to bypass research. If the skill is unavailable, record that limitation and perform equivalent bounded research.
```

Apply that fragment only to a project the user has authorized changing. A routing instruction helps invocation; it is not a host-enforced pre-implementation hook.
