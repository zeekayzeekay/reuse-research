#!/usr/bin/env python3
"""Bounded discovery and auditable candidate handling; Python standard library only."""

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


FAMILIES = {"whole", "capability", "ecosystem", "integration"}
GITHUB_URL = re.compile(r"(?<![\w./:=?&%-])(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)", re.I)
RESERVED = {"topics", "search", "orgs", "settings", "marketplace", "features", "sponsors", "login"}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def repo_id(url):
    match = GITHUB_URL.match((url or "").strip())
    if not match or match[1].lower() in RESERVED:
        return None
    name = match[2].removesuffix(".git").rstrip(".")
    return f"{match[1]}/{name}".lower() if name else None


def validate_plan(plan):
    errors = []
    excluded = plan.get("excluded_discovery_terms", [])
    if not isinstance(excluded, list) or any(not isinstance(t, str) or not t.strip() for t in excluded):
        errors.append("excluded_discovery_terms must be a list of nonempty strings")
        excluded = []
    requirements = plan.get("requirements", [])
    queries = plan.get("queries", [])
    ids = [r.get("id") for r in requirements]
    qids = [q.get("id") for q in queries]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        errors.append("requirements need unique nonempty string IDs")
    if not queries or any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", i) for i in qids) or len(set(qids)) != len(qids):
        errors.append("queries need unique safe IDs: letters, digits, underscore or hyphen, 1..64 characters")
    for query in queries:
        if query.get("family") not in FAMILIES:
            errors.append(f"{query.get('id')}: unknown query family")
        if query.get("provider") not in {"github", "web"}:
            errors.append(f"{query.get('id')}: provider must be github or web")
        if query.get("phase", "focused") not in {"broad", "focused"}:
            errors.append(f"{query.get('id')}: phase must be broad or focused")
        if not isinstance(query.get("text"), str) or not query["text"].strip():
            errors.append(f"{query.get('id')}: missing query text")
        normalized = " " + re.sub(r"[\W_]+", " ", str(query.get("text", "")).casefold()).strip() + " "
        for term in excluded:
            needle = re.sub(r"[\W_]+", " ", term.casefold()).strip()
            if not needle or " " + needle + " " in normalized:
                errors.append(f"{query.get('id')}: excluded discovery term: {term}")
        refs = query.get("requirements", [])
        if not isinstance(refs, list) or not refs or any(r not in ids for r in refs):
            errors.append(f"{query.get('id')}: invalid or empty requirement mapping")
    if not any(q.get("family") == "whole" for q in queries):
        errors.append("include a whole-purpose search")
    if not any(q.get("family") == "ecosystem" for q in queries):
        errors.append("include an ecosystem/library search, not only wrapper apps")
    for requirement in requirements:
        if requirement.get("critical", True) and not any(
            requirement.get("id") in q.get("requirements", [])
            and q.get("family") in {"capability", "ecosystem"} for q in queries
        ):
            errors.append(f"{requirement.get('id')}: critical capability has no targeted search")
    return errors


def check_plan(plan):
    errors = validate_plan(plan)
    if errors:
        raise ValueError("; ".join(errors))


def github_search(text, page, per_page, timeout):
    """Use existing gh auth when available; otherwise anonymous public GitHub API."""
    if shutil.which("gh"):
        command = ["gh", "api", "--method", "GET", "search/repositories",
                   "-f", f"q={text}", "-f", f"per_page={per_page}", "-f", f"page={page}"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                timeout=timeout, shell=False)
        if result.returncode:
            # Preserve category without printing stderr that could contain local auth information.
            message = result.stderr.lower()
            kind = "rate_limited" if "rate limit" in message or "429" in message else "access_failed"
            raise RuntimeError(kind)
        return json.loads(result.stdout)
    params = urllib.parse.urlencode({"q": text, "page": page, "per_page": per_page})
    request = urllib.request.Request("https://api.github.com/search/repositories?" + params,
                                     headers={"User-Agent": "reuse-research", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def packet_hits(packet):
    hits = packet.get("results", [])
    if not isinstance(hits, list) or any(not isinstance(hit, dict) for hit in hits):
        raise ValueError("packet results must be a list of objects")
    hits = list(hits)
    # Raw text preserves indirect GitHub source links even when a result is a wrapper or docs page.
    for match in GITHUB_URL.finditer(packet.get("raw_text", "")):
        hits.append({"url": match[0], "description": "Indirect link in returned source text", "indirect": True})
    return hits


def build_ledger(plan, packets, triage=None):
    check_plan(plan)
    queries = {q["id"]: q for q in plan["queries"]}
    by_repo = {}
    records = []
    sources = []
    for packet in packets:
        qid = packet.get("query_id")
        if qid not in queries:
            raise ValueError(f"unplanned packet query: {qid}")
        query = queries[qid]
        vote_group = packet.get("vote_group", query["provider"] + ":" + " ".join(query["text"].lower().split()))
        if packet.get("query_text") != query["text"] or packet.get("provider") != query["provider"]:
            raise ValueError(f"packet text/provider mismatch: {qid}")
        state = packet.get("state", "ok")
        if state not in {"ok", "failed", "not_run"}:
            raise ValueError(f"unknown query state: {state}")
        if state != "ok" and (packet.get("results") or packet.get("raw_text")):
            raise ValueError(f"{qid}: failed/unrun packets cannot introduce candidate evidence")
        records.append({"query_id": qid, "state": state, "error": packet.get("error"),
                        "phase": query.get("phase", "focused"),
                        "executed_query": packet.get("executed_query", packet.get("query_text")),
                        "observed_at": packet.get("observed_at"), "page": packet.get("page"),
                        "total_count": packet.get("total_count"),
                        "incomplete_results": packet.get("incomplete_results"),
                        "pagination_bounded": packet.get("pagination_bounded", True),
                        "channel": packet.get("channel", query["provider"]),
                        "vote_group": vote_group})
        if state == "ok":
            for hit in packet.get("results", []):
                if hit.get("url"):
                    sources.append({"url": hit["url"], "query_id": qid,
                                    "requirements": query["requirements"], "kind": hit.get("kind", "search_result")})
        for rank, hit in enumerate(packet_hits(packet), 1):
            identity = repo_id(hit.get("url", ""))
            if not identity:
                continue
            item = by_repo.setdefault(identity, {"repo": identity, "url": "https://github.com/" + identity,
                "identity_state": "retrieved_link", "requirements": [], "hits": [], "metadata": [],
                "triage": {"disposition": "pending", "reason": None}, "verification": "unverified"})
            item["requirements"] = sorted(set(item["requirements"] + query["requirements"]))
            indirect = hit.get("indirect", False)
            if packet.get("ranked", True) is False or indirect:
                provider_rank = None
            else:
                provider_rank = (packet.get("page", 1) - 1) * packet.get("per_page", len(packet.get("results", []))) + rank
            item["hits"].append({"query_id": qid, "family": query["family"], "provider": query["provider"],
                                "phase": query.get("phase", "focused"),
                                "rank": rank, "provider_rank": provider_rank,
                                "vote_group": vote_group, "channel": packet.get("channel", query["provider"]),
                                "requirements": query["requirements"],
                                "source_url": hit["url"], "indirect": indirect,
                                "description": hit.get("description"), "title": hit.get("title"),
                                "passages": hit.get("passages", [])})
            if query["provider"] == "github" and hit.get("full_name"):
                item["identity_state"] = "github_metadata"
                item["metadata"].append({k: hit.get(k) for k in ["full_name", "fork", "archived", "pushed_at", "stargazers_count", "license"]})
    dispositions = triage or []
    seen = set()
    for entry in dispositions:
        identity = entry.get("repo", "").lower()
        if identity not in by_repo or identity in seen:
            raise ValueError(f"unknown/duplicate triage identity: {identity}")
        seen.add(identity)
        if entry.get("disposition") not in {"verify", "study", "defer", "exclude"} or not entry.get("reason"):
            raise ValueError(f"{identity}: disposition and explicit reason required")
        by_repo[identity]["triage"] = entry
    # A review cue per query preserves specialist/partial matches without claiming a quality ranking.
    cues = set()
    for qid in queries:
        ranked = [(h["rank"], identity) for identity, item in by_repo.items() for h in item["hits"] if h["query_id"] == qid]
        cues.update(identity for _, identity in sorted(ranked)[:3])
    for identity in cues:
        by_repo[identity]["review_cue"] = True
    coverage = {}
    for requirement in plan["requirements"]:
        targeted = [q["id"] for q in queries.values() if requirement["id"] in q["requirements"] and q["family"] in {"capability", "ecosystem"}]
        successful = [qid for qid in targeted if any(r["query_id"] == qid and r["state"] == "ok" for r in records)]
        coverage[requirement["id"]] = {"planned": targeted, "successful_queries": successful,
            "discovery_state": "reached" if successful else "unknown",
            "behavior_state": "unverified"}
    return {"schema_version": 1, "task": plan.get("task"), "created_at": now(), "coverage": coverage,
            "query_records": records, "discovery_sources": sources,
            "requirements": plan["requirements"],
            "unrun_queries": [qid for qid in queries if not any(r["query_id"] == qid for r in records)],
            "candidates": [by_repo[k] for k in sorted(by_repo)],
            "triage_complete": len(seen) == len(by_repo) and bool(by_repo),
            "limits": ["Search coverage is not behavioral verification.", "Review cues are provider-rank hints, not adoption scores.",
                       "Bounded search and source links do not prove exhaustive recall or eligibility."]}


def run_search(plan, output, seconds=120, per_page=40, pages=1, transport=github_search, clock=time.monotonic, query_ids=None):
    check_plan(plan)
    selected = None if query_ids is None else set(query_ids)
    if selected is not None and (not selected or not selected <= {q["id"] for q in plan["queries"]}):
        raise ValueError("selected query IDs must be known and nonempty")
    if not 1 <= per_page <= 100 or not 1 <= pages <= 3 or seconds <= 0:
        raise ValueError("per_page 1..100, pages 1..3, seconds >0 required")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    packets = []
    started = clock()
    deadline = started + seconds
    # Round-robin pages: cover query diversity before extending one result list.
    for page in range(1, pages + 1):
        for query in plan["queries"]:
            if query["provider"] != "github" or (selected is not None and query["id"] not in selected):
                continue
            remaining = deadline - clock()
            base = {"query_id": query["id"], "query_text": query["text"], "provider": "github", "page": page, "observed_at": now()}
            if remaining <= 0:
                packet = {**base, "state": "not_run", "error": "budget_exhausted"}
            else:
                try:
                    executed_query = query["text"] + " is:public"
                    result = transport(executed_query, page, per_page, max(0.01, min(remaining, 30)))
                    packet = {**base, "per_page": per_page, "executed_query": executed_query, "state": "ok", "results": result.get("items", []),
                              "total_count": result.get("total_count"), "incomplete_results": result.get("incomplete_results"),
                              "pagination_bounded": result.get("total_count", 0) > page * per_page}
                    for item in packet["results"]:
                        item["url"] = item.get("html_url", item.get("url", ""))
                except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired, urllib.error.URLError) as exc:
                    error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                    packet = {**base, "executed_query": query["text"] + " is:public", "state": "failed", "error": error}
            packets.append(packet)
            write_json(root / "packets" / f"{query['id']}-page{page}.json", packet)
            write_json(root / "ledger.json", build_ledger(plan, packets))
    value = build_ledger(plan, packets)
    write_json(root / "ledger.json", value)
    return value


def extract_leads(path):
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig")
    repos = sorted({repo_id(m[0]) for m in GITHUB_URL.finditer(text) if repo_id(m[0])})
    packages = []
    if source.name == "package.json":
        value = json.loads(text)
        for key in ("dependencies", "optionalDependencies", "peerDependencies"):
            packages.extend({"name": name, "ecosystem": "npm", "declared": version} for name, version in value.get(key, {}).items())
    elif source.name == "pyproject.toml":
        import tomllib
        value = tomllib.loads(text)
        packages.extend({"name": dep, "ecosystem": "python"} for dep in value.get("project", {}).get("dependencies", []))
    elif source.name == "Cargo.toml":
        import tomllib
        value = tomllib.loads(text)
        groups = [("package", value.get("dependencies", {})),
                  ("workspace", value.get("workspace", {}).get("dependencies", {}))]
        groups.extend(("target:" + target, settings.get("dependencies", {}))
                      for target, settings in value.get("target", {}).items())
        for scope, dependencies in groups:
            for alias, declared in dependencies.items():
                name = declared.get("package", alias) if isinstance(declared, dict) else alias
                packages.append({"name": name, "alias": alias, "ecosystem": "cargo",
                                 "scope": scope, "declared": declared})
    elif source.name.startswith("requirements") and source.suffix == ".txt":
        packages.extend({"name": line.strip(), "ecosystem": "python"} for line in text.splitlines()
                        if line.strip() and not line.lstrip().startswith(("#", "-")))
    return {"source": str(source), "repos": repos, "packages": packages,
            "status": "unverified_leads", "next": "Resolve relevant packages to primary sources; not every dependency is relevant."}


def audit(ledger, expected):
    candidates = {c["repo"]: c for c in ledger["candidates"]}
    rows = []
    for entry in expected:
        aliases = [entry["repo"].lower()] + [a.lower() for a in entry.get("aliases", [])]
        found = next((candidates[a] for a in aliases if a in candidates), None)
        rows.append({"repo": entry["repo"], "retrieved": bool(found), "triage": found["triage"] if found else None,
                     "verification": found["verification"] if found else None})
    return {"expected_count": len(rows), "retrieved_count": sum(r["retrieved"] for r in rows), "rows": rows,
            "limits": "Expected identities must be verified separately. Named auditing does not change discovery results."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "search", "merge"):
        part = sub.add_parser(command)
        part.add_argument("--plan", required=True)
        if command != "validate":
            part.add_argument("--out", required=True)
        if command == "search":
            part.add_argument("--seconds", type=float, default=120)
            part.add_argument("--per-page", type=int, default=40)
            part.add_argument("--pages", type=int, default=1)
            part.add_argument("--query-ids", nargs="+", help="Execute only these IDs while validating the complete plan")
            part.add_argument("--run", help="Shared research clock; acquisition stops before its report reserve")
        if command == "merge":
            part.add_argument("--packets", nargs="+", required=True)
            part.add_argument("--triage")
    leads = sub.add_parser("leads")
    leads.add_argument("--file", required=True)
    leads.add_argument("--out", required=True)
    review = sub.add_parser("audit")
    review.add_argument("--ledger", required=True)
    review.add_argument("--expected", required=True)
    review.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            errors = validate_plan(read_json(args.plan))
            print(json.dumps({"valid": not errors, "errors": errors}))
            return 1 if errors else 0
        if args.command == "search":
            if args.run:
                from reuse_run import allowance
                args.seconds = allowance(read_json(args.run), args.seconds)
            value = run_search(read_json(args.plan), args.out, args.seconds, args.per_page, args.pages, query_ids=args.query_ids)
            print(json.dumps({"candidates": len(value["candidates"]), "coverage": value["coverage"], "ledger": str(Path(args.out) / "ledger.json")}))
        elif args.command == "merge":
            packets = []
            for path in args.packets:
                if Path(path).is_dir():
                    packets.extend(read_json(p) for p in sorted(Path(path).glob("*.json")))
                else:
                    value = read_json(path)
                    packets.extend(value if isinstance(value, list) else [value])
            value = build_ledger(read_json(args.plan), packets, read_json(args.triage) if args.triage else None)
            write_json(args.out, value)
            print(json.dumps({"candidates": len(value["candidates"]), "triage_complete": value["triage_complete"]}))
        elif args.command == "leads":
            write_json(args.out, extract_leads(args.file))
        else:
            write_json(args.out, audit(read_json(args.ledger), read_json(args.expected)))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
