#!/usr/bin/env python3
"""Persist a research clock and assemble compact, provenance-checked handoffs.

No model, network, candidate execution or background host timer.
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path


def utc():
    return dt.datetime.now(dt.timezone.utc)


def start(task, seconds=600, reserve=90, at=None):
    if not task or seconds <= 0 or not 0 < reserve < seconds:
        raise ValueError("task and positive total/reserve with reserve < total required")
    at = at or utc()
    return {"task": task, "start_utc": at.isoformat(), "budget_seconds": seconds,
        "reserve_seconds": reserve, "acquisition_stop_utc": (at + dt.timedelta(seconds=seconds-reserve)).isoformat(),
        "deadline_utc": (at + dt.timedelta(seconds=seconds)).isoformat(),
        "status": "active", "limits": "Shared clock for participating helpers; direct host tools require checkpoints. No host kill timer."}


def status(run, at=None):
    at = at or utc()
    started = dt.datetime.fromisoformat(run["start_utc"])
    cutoff = dt.datetime.fromisoformat(run["acquisition_stop_utc"])
    deadline = dt.datetime.fromisoformat(run["deadline_utc"])
    if any(x.tzinfo is None for x in (at, started, cutoff, deadline)) or not started < cutoff < deadline:
        raise ValueError("valid ordered timezone-aware run timestamps required")
    elapsed = max(0, (at-started).total_seconds())
    return {"observed_at": at.isoformat(), "elapsed_seconds": elapsed,
        "remaining_seconds": max(0, (deadline-at).total_seconds()),
        "acquisition_remaining_seconds": max(0, (cutoff-at).total_seconds()),
        "phase": "stopped" if run.get("status") == "complete" else "deadline" if at >= deadline else "report" if at >= cutoff else "acquisition",
        "overrun_seconds": max(0, (at-deadline).total_seconds())}


def allowance(run, requested, at=None):
    state = status(run, at)
    if requested <= 0:
        raise ValueError("positive acquisition allowance required")
    if state["phase"] != "acquisition":
        raise ValueError("acquisition closed; save the handoff with current evidence")
    return min(requested, state["acquisition_remaining_seconds"])


def cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def frontpage_lines(briefs, records=None):
    prominent = briefs.get("unbriefed_frontpage", [])
    lines = []
    if prominent:
        lines += ["", "Unbriefed front-page leads (retrieval hints; all remain uninspected with fit unknown):", "",
            ", ".join(cell(r["repo"]) for r in prominent) + "."]
    gaps = briefs.get("content_gaps", [])
    if gaps:
        lines += ["", "Briefed leads missing source text (fit unknown; read primary documentation or defer explicitly):", "",
            ", ".join(cell(r["repo"]) for r in gaps) + "."]
    leads = briefs.get("component_leads", [])
    if leads:
        supplied = {r.get("lead_id"): r for r in (records or {}).get("component_leads", [])}
        lines += ["", "Critical upstream component cues (literal names; repository identity and fit need disambiguation):", "",
                  "| Cue / requirement | Literal source excerpt | Source | Disposition / next check |",
                  "| --- | --- | --- | --- |"]
        for lead in leads:
            disposition = supplied.get(lead["id"], {})
            state = cell(disposition.get("status", "unresolved")) + ": " + cell(disposition.get("reason", "Resolve primary identity with the bounded mentions round, or record a deferral"))
            if isinstance(disposition.get("repos"), list) and disposition["repos"]:
                state += "; retained identities: " + ", ".join(cell(r) for r in disposition["repos"])
            lines.append("| " + " | ".join(cell(x) for x in (lead["mention"] + " / " + ", ".join(lead["requirements"]),
                lead["excerpt"], lead["source_url"], state)) + " |")
    return lines


def whole_solution_lines(ledger, records=None):
    from reuse_enrich import validate_whole_shortlist
    entries = validate_whole_shortlist(ledger)
    if not entries:
        return []
    supplied = {r["repo"].lower(): r for r in (records or {}).get("candidates", [])}
    lines = ["", "## Whole solutions to compare", "",
        "Protected primary-documentation leads; relevance is a host judgment, behavior and eligibility remain unverified.", "",
        "| Candidate | Documented purpose / relevance hypothesis | Primary source | Assessment / deferral | Next check |",
        "| --- | --- | --- | --- | --- |"]
    for entry in entries:
        record = supplied.get(entry["repo"], {})
        lines.append("| " + " | ".join(cell(x) for x in (entry["repo"], entry["reason"], entry["source_url"],
            record.get("reason") or "Assessment pending; keep this alternative visible",
            record.get("next_check") or "Unresolved; name the check that would change its disposition")) + " |")
    return lines


def render_snapshot(ledger, briefs=None, review=None, run=None):
    """Save usable unfinished evidence without inventing semantic judgments."""
    from reuse_review import review_evidence
    from reuse_enrich import validate_component_leads, validate_whole_shortlist
    validate_component_leads(ledger, briefs or {})
    validate_whole_shortlist(ledger, briefs)
    checked = review_evidence(ledger, (review or {}).get("cards", []))
    sources = {s["id"]: s for s in ledger.get("source_captures", [])}
    lines = ["# Research checkpoint: " + cell(ledger.get("task", "task")), "",
        "UNFINISHED. This recovery artifact has no completed selection reconciliation or adoption recommendation.",
        "Source inspection is not execution. Candidate fit and consuming implementation coverage remain unresolved.", "",
        "## Open decisions", ""]
    lines.extend("- " + cell(r["id"]) + ": DEFER / provisional. Complete capability and eligibility checks before choosing a reuse plan."
        for r in ledger["requirements"])
    lines += ["", "## Validated evidence available", ""]
    for card in checked["cards"]:
        lines.append("- " + cell(card["repo"]) + " / " + cell(card["requirement"]) + ": " + cell(card["claim"])
            + " (" + cell(card["method"]) + " / " + cell(card["state"]) + "). Source: "
            + cell(sources[card["source_id"]]["url"]) + ". Limits: " + cell(card["limits"]))
    if not checked["cards"]:
        lines.append("No validated evidence cards saved yet.")
    lines += whole_solution_lines(ledger)
    lines += frontpage_lines(briefs or {})
    lines += ["", f"Retained {len(ledger['candidates'])} candidate leads. Complete retrieval and source bindings remain in the supplied ledger.",
        "Next: finish selection reasons, whole-purpose review and per-requirement decisions, then run handoff. If time has expired, retain this unfinished checkpoint."]
    if run:
        state = status(run)
        lines.append(f"Checkpoint clock: {state['elapsed_seconds']:.1f} seconds; target {run['budget_seconds']}; overrun {state['overrun_seconds']:.1f}.")
    return "\n".join(lines) + "\n"


def render_report(ledger, briefs, screened, review, records, decisions, cases=None, run=None, context=None):
    from reuse_enrich import case_inventory, reconcile_selection, validate_component_leads, validate_whole_shortlist
    from reuse_review import review_evidence
    validate_component_leads(ledger, briefs)
    protected = validate_whole_shortlist(ledger, briefs)
    checked = review_evidence(ledger, review.get("cards", []))
    reqs = {r["id"] for r in ledger["requirements"]}
    rows = decisions.get("decisions", [])
    if {r.get("requirement") for r in rows} != reqs or len(rows) != len(reqs):
        raise ValueError("one decision or explicit unresolved disposition per requirement required")
    for row in rows:
        if row.get("decision") not in {"USE", "ADAPT", "CONTRIBUTE", "FORK", "STUDY", "BUILD", "DEFER"} or row.get("status") not in {"provisional", "recommended"} or not row.get("reason") or not row.get("next_check"):
            raise ValueError("decisions need disposition, status, reason and next check")
    inventory = case_inventory(ledger, review, cases["cases"]) if cases is not None else None
    sources = {s["id"]: s for s in ledger.get("source_captures", [])}
    context = context if context is not None else decisions.get("context", {})
    context_gaps = [key for key in ("goal", "stack", "constraints") if not context.get(key)]
    descriptions = {r["id"]: r.get("description", "") for r in ledger["requirements"]}
    context_gaps.extend("requirement description: " + req for req, description in descriptions.items() if not description)
    plan = context.get("implementation_plan", [])
    if not isinstance(plan, list):
        raise ValueError("implementation_plan must be a list of requirement/action/evidence_ids records")
    for step in plan:
        if (step.get("requirement") not in reqs or not step.get("action")
                or not isinstance(step.get("evidence_ids", []), list)
                or not set(step.get("evidence_ids", [])) <= {c["id"] for c in checked["cards"]}):
            raise ValueError("plan steps need known requirement, action and valid evidence IDs")
    context_gaps.extend("implementation plan: " + req for req in sorted(reqs - {s["requirement"] for s in plan}))
    lines = ["# Reuse research: " + cell(ledger.get("task", "task")), "",
        "Bounded research. Source inspection is not execution; adoption and consuming coverage depend on the recorded checks.", "",
        "## Task context", "", "Goal: " + cell(context.get("goal") or "unknown"),
        "Stack: " + cell(context.get("stack") or "unknown"), "Constraints: " + cell(context.get("constraints") or "unknown"),
        "Observation: " + cell(checked["created_at"]), "",
        "## Decisions", "", "| Requirement | Decision | Status | Reason | Next check |", "| --- | --- | --- | --- | --- |"]
    lines.extend("| " + " | ".join(cell(x) for x in (r["requirement"] + ": " + (descriptions[r["requirement"]] or "description missing"), r["decision"], r["status"], r["reason"], r["next_check"])) + " |" for r in rows)
    lines += ["", "## Reconciled implementation plan", ""]
    lines.extend("- " + cell(s["requirement"]) + ": " + cell(s["action"]) + "; evidence: " + cell(", ".join(s.get("evidence_ids", [])) or "unresolved / no source support") for s in plan)
    if not plan:
        lines.append("UNFINISHED: no reconciled implementation plan supplied.")
    lines += whole_solution_lines(ledger, records)
    lines += ["", "## Evidence", "", "| Card / candidate / requirement / role | Method / state | Finding | Source / observed | Limits |", "| --- | --- | --- | --- | --- |"]
    for card in checked["cards"]:
        lines.append("| " + " | ".join(cell(x) for x in (card["id"] + " / " + card["repo"] + " / " + card["requirement"] + " / " + card["role"],
            card["method"] + " / " + card["state"], card["claim"], sources[card["source_id"]]["url"] + " / " + sources[card["source_id"]]["observed_at"], card["limits"])) + " |")
    lines += ["", "## Selection and deferrals", "", "| Canonical candidate | Inspection / deferral reason |", "| --- | --- |"]
    protected_ids = {e["repo"] for e in protected}
    lines.extend("| " + cell(r["repo"]) + " | " + cell(r["reason"]) + " |" for r in records.get("candidates", []) if r["repo"].lower() not in protected_ids)
    lines += frontpage_lines(briefs, records)
    unreported = max(0, len(ledger["candidates"]) - len({r["repo"] for r in records.get("candidates", [])}))
    lines += ["", f"Remaining {unreported} ledger leads are deferred without a suitability judgment. Complete identities and source bindings remain in the ledger.", ""]
    whole = records.get("whole_purpose", {})
    lines.append("Whole-purpose review: " + cell(whole.get("reason") or whole.get("deferred_reason") or "unfinished"))
    if inventory:
        lines += ["", "## Source-observed cases", "", "| Case / evidence | Trigger | Observed behavior | Applicability | Current state | Proposed check |", "| --- | --- | --- | --- | --- | --- |"]
        lines.extend("| " + " | ".join(cell(x) for x in (c["id"] + " / " + c["card_id"], c["input_or_trigger"], c["observed_behavior"], c["applicability"], c["current_state"], c["proposed_check"])) + " |" for c in inventory["cases"])
    lines += ["", "## Search and timing boundaries", "", f"Retained leads: {len(ledger['candidates'])}; briefed: {len(briefs['briefs'])}; cards: {len(checked['cards'])}.",
        "Failed/unrun queries and bounded pagination remain recorded in the ledger. A bounded search does not establish exhaustive recall."]
    for row in ledger.get("query_records", []):
        if row["state"] != "ok":
            lines.append("- " + cell(row["query_id"]) + ": " + cell(row["state"]) + "; " + cell(row.get("error")))
    if run:
        state = status(run)
        lines.append(f"Artifact assembly clock: {state['elapsed_seconds']:.1f} seconds; target {run['budget_seconds']}; overrun {state['overrun_seconds']:.1f}. Final delivery latency is separate.")
    report = "\n".join(lines) + "\n"
    audit = reconcile_selection(ledger, briefs, screened, review, records, report)
    audit["report_gaps"] = context_gaps
    audit["handoff_complete"] = audit["accounted"] and not context_gaps
    marker = "ACCOUNTED HANDOFF. Provisional decisions and open checks remain." if audit["handoff_complete"] else "UNFINISHED. Selection accounting or required task context/plan is incomplete."
    report = marker + "\n\n" + report
    audit["report_sha256"] = hashlib.sha256(report.encode("utf-8")).hexdigest()
    return report, audit


def main(argv=None):
    from reuse_search import read_json, write_json
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    begin = sub.add_parser("start")
    begin.add_argument("--task", required=True)
    begin.add_argument("--seconds", type=float, default=600)
    begin.add_argument("--reserve", type=float, default=90)
    begin.add_argument("--out", required=True)
    checkpoint = sub.add_parser("status")
    checkpoint.add_argument("--run", required=True)
    checkpoint.add_argument("--acquisition", action="store_true")
    snapshot = sub.add_parser("snapshot")
    for field in ("ledger", "out"):
        snapshot.add_argument("--" + field, required=True)
    for field in ("briefs", "review", "run"):
        snapshot.add_argument("--" + field)
    handoff = sub.add_parser("handoff")
    for field in ("ledger", "briefs", "screened", "review", "records", "decisions", "out", "audit-out"):
        handoff.add_argument("--" + field, required=True)
    handoff.add_argument("--cases")
    handoff.add_argument("--run")
    handoff.add_argument("--context")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            if Path(args.out).exists():
                raise ValueError("existing run clock must be preserved; choose a separate continuation file")
            write_json(args.out, start(args.task, args.seconds, args.reserve))
            return 0
        if args.command == "status":
            result = status(read_json(args.run))
            print(json.dumps(result))
            return int(result["phase"] in {"deadline", "stopped"} or args.acquisition and result["phase"] != "acquisition")
        if args.command == "snapshot":
            run = read_json(args.run) if args.run else None
            report = render_snapshot(read_json(args.ledger), read_json(args.briefs) if args.briefs else None,
                read_json(args.review) if args.review else None, run)
            target = Path(args.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(report, encoding="utf-8")
            if run:
                run["checkpoint_save"] = status(run)
                write_json(args.run, run)
            return 3 if run and run["checkpoint_save"]["overrun_seconds"] > 0 else 0
        report, audit = render_report(*(read_json(getattr(args, k)) for k in ("ledger", "briefs", "screened", "review", "records", "decisions")),
            cases=read_json(args.cases) if args.cases else None, run=read_json(args.run) if args.run else None,
            context=read_json(args.context) if args.context else None)
        report += "\nAccounting audit: [saved audit](" + Path(args.audit_out).resolve().as_posix() + ").\n"
        audit["report_sha256"] = hashlib.sha256(report.encode("utf-8")).hexdigest()
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
        late = False
        if args.run:
            run = read_json(args.run)
            run["artifact_save"] = status(run)
            late = run["artifact_save"]["overrun_seconds"] > 0
            audit["timing"] = {**run["artifact_save"], "deadline_met": not late}
        write_json(args.audit_out, audit)
        if args.run:
            run["status"] = "complete" if audit["handoff_complete"] else "unfinished"
            run["outcome"] = "late" if late else "accounted" if audit["handoff_complete"] else "unfinished"
            write_json(args.run, run)
        return 3 if late else 0 if audit["handoff_complete"] else 1
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
