"""Read-only historical retrieval audit. Expected identities are audit inputs only.

No search, candidate execution, ledger mutation, or inference of unseen results.
Run with --manifest YOUR_MANIFEST.json --out PATH.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
URL = re.compile(r"(?<![\w./:=?&%-])(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)", re.I)
RESERVED = {"topics", "search", "orgs", "settings", "marketplace", "features", "sponsors", "login"}


def identities(value):
    """Explicit repository links only; a bare project name stays a mention."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {f"{m[1]}/{m[2].removesuffix('.git').rstrip('.')}".lower()
            for m in URL.finditer(text) if m[1].lower() not in RESERVED}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_first(base, names, artifacts):
    for name in names:
        path = base / name
        if path.exists():
            artifacts[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
            return read(path)
    return None


def query_logs(value):
    """Keep actual search calls separate from subsequent opens/source reads."""
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = value.get("web_calls", value.get("logs", value.get("discovery_queries", value.get("records", value.get("queries", [])))))
    else:
        return []
    result = []
    for index, item in enumerate(items):
        request = item.get("input", {})
        search = request.get("search_query", [])
        texts = [x["q"] for x in search if "q" in x]
        if not texts and not request and not item.get("route"):
            texts = item.get("queries", []) or [item.get("query", item.get("text"))]
        texts = [t for t in texts if t and not t.startswith(("https://api.", "git "))]
        if not texts:
            continue
        raw = item.get("result", item.get("results", item.get("raw_text", item.get("result_candidates", ""))))
        result.append({"id": item.get("id", f"batch-{index + 1}"), "texts": texts,
                       "state": item.get("status", "recorded"), "raw": raw,
                       "links": sorted(identities(raw)),
                       "rank_limit": "Batched text has no reliable per-query repository rank."})
    return result


def candidates(ledger):
    return {c["repo"].lower(): c for c in (ledger or {}).get("candidates", [])}


def queue(value):
    return None if value is None else value.get("review_queue", value.get("ordering", {}).get("review_queue", []))


def audit_run(spec, expected):
    base = ROOT / spec["path"]
    artifacts = {}
    initial = load_first(base, spec.get("initial", ["discovery/ledger.json"]), artifacts)
    final = load_first(base, spec.get("final", ["final-ledger.json", "ledger.json"]), artifacts)
    if final is None:
        final = initial
    plan = load_first(base, ["plan.json", "supplied-plan.json"], artifacts)
    logs = load_first(base, ["queries.json"], artifacts)
    briefs = load_first(base, ["briefs.json"], artifacts)
    ordering = load_first(base, ["semantic-queue.json", "queue.json"], artifacts)
    review = load_first(base, ["final-review.json", "review.json"], artifacts)
    cards = (review or {}).get("cards")
    if cards is None:
        data = load_first(base, ["cards.json"], artifacts)
        cards = data if isinstance(data, list) else (data or {}).get("cards")
    packet_files = sorted(base.glob(spec.get("packet_glob", "discovery/packets/*.json")))
    packet_files += [base / n for n in ["web-packets.json", "expansion-packet.json", "followup-web-packet.json", "dependency-packet.json"] if (base / n).exists()]
    packets = []
    for path in packet_files:
        artifacts[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
        value = read(path)
        for p in value if isinstance(value, list) else [value]:
            if isinstance(p, dict) and "query_id" in p:
                packets.append({**p, "artifact": str(path.relative_to(ROOT)).replace("\\", "/")})
    recorded_logs = query_logs(logs)
    discovery_file = base / "sources/discovery-results.json"
    if discovery_file.exists():
        artifacts[str(discovery_file.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(discovery_file.read_bytes()).hexdigest()
        recorded_logs.append({"id": "saved-fallback-discovery", "texts": ["Per-query attribution unavailable"],
                              "state": "recorded", "raw": read(discovery_file),
                              "links": sorted(identities(read(discovery_file))),
                              "rank_limit": "Merged discovery records; no per-query ranking."})
    report_path = base / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    if report is not None:
        artifacts[str(report_path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    initial_ids, final_ids = candidates(initial), candidates(final)
    brief_ids = None if briefs is None else {b["repo"].lower() for b in briefs.get("briefs", [])}
    queued = queue(ordering)
    rows = []
    for ref in expected:
        names = {ref["repo"].lower(), *[a.lower() for a in ref.get("aliases", [])]}
        raw_hits = []
        unusable_links = []
        bare_mentions = []
        nested_links = []
        for p in packets:
            if p.get("state", "ok") != "ok":
                continue
            direct = set()
            for index, hit in enumerate(p.get("results", [])):
                url_ids = identities(hit.get("url", ""))
                direct |= url_ids
                if names & url_ids:
                    raw_hits.append({"query_id": p["query_id"], "artifact": p["artifact"], "kind": "result_url",
                                     "provider_rank": None if p.get("ranked", True) is False or hit.get("indirect") else
                                     (p.get("page", 1) - 1) * p.get("per_page", len(p.get("results", []))) + index + 1})
                if names & identities({k: v for k, v in hit.items() if k != "url"}):
                    nested_links.append({"query_id": p["query_id"], "artifact": p["artifact"]})
            raw = p.get("raw_text", "")
            if names & identities(raw):
                raw_hits.append({"query_id": p["query_id"], "artifact": p["artifact"], "kind": "raw_text_link", "provider_rank": None})
            content = json.dumps(p, ensure_ascii=False).lower()
            if not names & (direct | identities(raw)) and any(re.search(r"(?<![\w-])" + re.escape(n.split("/", 1)[1]) + r"(?![\w-])", content) for n in names):
                bare_mentions.append({"query_id": p["query_id"], "artifact": p["artifact"]})
        for item in recorded_logs:
            if item["state"] not in {"ok", "success", "completed", "usable"}:
                if names & set(item["links"]):
                    unusable_links.append({"query_id": item["id"], "state": item["state"]})
                continue
            if names & set(item["links"]):
                raw_hits.append({"query_id": item["id"], "kind": "logged_batch_link", "provider_rank": None})
            elif any(re.search(r"(?<![\w-])" + re.escape(n.split("/", 1)[1]) + r"(?![\w-])", str(item["raw"]).lower()) for n in names):
                bare_mentions.append({"query_id": item["id"], "kind": "logged_batch_mention"})
        found = next((final_ids[n] for n in names if n in final_ids), None)
        reviewed = None if cards is None else any(c.get("repo", "").lower() in names for c in cards)
        inspected = None if cards is None else any(c.get("repo", "").lower() in names and c.get("method") == "inspected" for c in cards)
        mentioned = None if report is None else bool(names & identities(report)) or any(re.search(
            r"(?<![\w.-])" + re.escape(n) + r"(?![\w.-])", report, re.I) for n in names)
        if mentioned is False and ref.get("report_names"):
            mentioned = any(re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", report, re.I) for n in ref["report_names"])
        retrieved = None if final is None else bool(found)
        briefed = None if brief_ids is None else bool(names & brief_ids)
        queue_rank = None if queued is None else next((i + 1 for i, n in enumerate(queued) if n.lower() in names), None)
        if retrieved is False:
            usable_trace = any(p.get("state", "ok") == "ok" for p in packets) or any(
                q["state"] in {"ok", "success", "completed", "usable"} for q in recorded_logs)
            loss = "ledger_merge" if raw_hits else "provider_return_boundary" if usable_trace else "unknown_failed_or_unconfirmed_trace" if packets or recorded_logs else "unknown_missing_trace"
        elif retrieved is True and briefed is False:
            loss = "brief_limit"
        elif briefed is True and queue_rank is None and queued is not None:
            loss = "review_queue"
        elif retrieved is True and reviewed is False:
            loss = "evidence_review_selection"
        elif retrieved is True and mentioned is False:
            loss = "report_selection"
        elif retrieved is True:
            loss = "surfaced_or_later_stage_unknown"
        else:
            loss = "unknown_missing_ledger"
        rows.append({"repo": ref["repo"], "aliases": ref.get("aliases", []), "raw_hits": raw_hits,
                     "bare_mentions": bare_mentions, "nested_links": nested_links, "unusable_logged_links": unusable_links,
                     "initial_pool": None if initial is None else bool(names & set(initial_ids)),
                     "final_pool": retrieved, "briefed": briefed, "queue_rank": queue_rank,
                     "card_reviewed": reviewed, "code_inspected": inspected, "report_mention": mentioned,
                     "triage": found.get("triage") if found else None,
                     "ledger_hits": found.get("hits", []) if found else [], "first_observed_loss": loss})
    packet_summary = [{k: p.get(k) for k in ["query_id", "query_text", "executed_query", "provider", "state", "page", "total_count", "incomplete_results", "pagination_bounded", "observed_at", "artifact"]} | {"returned": len(p.get("results", []))} for p in packets]
    return {"id": spec["id"], "path": spec["path"], "notes": spec.get("notes"), "plan": plan,
            "logged_searches": [{k: v for k, v in q.items() if k != "raw"} for q in recorded_logs],
            "packet_summary": packet_summary, "initial_pool_count": None if initial is None else len(initial_ids),
            "final_pool_count": None if final is None else len(final_ids), "rows": rows, "artifacts_sha256": artifacts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = read(args.manifest)
    results = []
    for group in manifest["scenarios"]:
        results.append({"scenario": group["id"], "prompt": group.get("prompt"), "prompt_artifact": group.get("prompt_artifact"),
                        "runs": [audit_run(run, group["expected"]) for run in group["runs"]]})
    result = {"observed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "scenarios": results,
              "limits": ["Expected names used only by this read-only audit, never as pilot inputs.",
                         "Null means the stage trace is unavailable. A report omission is not proof of a search miss.",
                         "Provider-return boundary records absence from captured results; it does not identify a historical indexing/ranking cause.",
                         "Report mention is visibility only, not endorsement or primary-source review.",
                         "Historical captured inputs are separate from current diagnostic searches."]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"scenarios": len(results), "runs": sum(len(g["runs"]) for g in results), "out": str(args.out)}))


if __name__ == "__main__":
    main()
