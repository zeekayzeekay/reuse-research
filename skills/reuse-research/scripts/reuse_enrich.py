#!/usr/bin/env python3
"""Source-based screening, gap expansion, case transfer, local cache and qualification.

Host agents supply semantic judgments. No embedded model or candidate execution.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

from reuse_search import GITHUB_URL, build_ledger, check_plan, now, read_json, repo_id, write_json
from reuse_review import review_evidence, review_order, source_repo, validate_capture, pinned_source

PRIORITY = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
STOP = {"with", "that", "from", "this", "have", "into", "which", "their", "could", "should", "would", "and", "the", "for", "are"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def tokens(text):
    return set(re.findall(r"[a-z0-9_-]{3,}", text.lower())) - STOP


def snippets(text, terms, size=600):
    """Select literal windows; lexical selection is not the semantic fit judgment."""
    offsets = [0]
    offsets.extend(m.start() for m in re.finditer(r"\n\s*\n", text))
    rows = [(len(tokens(text[p:p + size]) & terms), p, text[p:p + size]) for p in offsets]
    return [s for _, _, s in sorted(rows, key=lambda r: (-r[0], r[1]))[:2] if s.strip()]


def link_context(text, match):
    """Keep a linked entry's literal line, not the next project's claims."""
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    end = len(text) if end < 0 else end
    line = text[start:end]
    identities = {repo_id(m[0]) for m in GITHUB_URL.finditer(line)}
    # Multiple projects on one line have ambiguous claim ownership. Keep only
    # the actual source link rather than attributing shared prose to one project.
    if len(identities) > 1:
        return match[0]
    return line


def mention_hints(ledger, limit=20):
    """Literal name cues for host disambiguation, never inferred repo identities."""
    task_terms = tokens(" ".join([ledger.get("task") or ""] + [r.get("description", "") for r in ledger.get("requirements", [])]))
    generic = STOP | {"simple", "open", "source", "library", "tool", "tools", "using", "built", "based", "supports", "support", "python", "javascript", "typescript", "rust", "node", "docker", "automatically", "automatic", "github", "readme", "this", "with", "fast", "free", "the", "powered", "windows", "linux", "macos"}
    hints = {}
    critical = {r["id"] for r in ledger.get("requirements", []) if r.get("critical")}
    for candidate in ledger["candidates"]:
        own_name = candidate["repo"].split("/")[-1].casefold()
        for index, hit in enumerate(candidate["hits"]):
            if hit.get("indirect"):
                continue
            for field in ("description", "title"):
                text = hit.get(field) or ""
                cues = list(re.finditer(r"\b(?:using|powered by|based on|built on|built with|fork of|inspired by|in)\s+(?:the\s+)?([A-Za-z][\w.-]{3,})", text, re.I))
                cue_names = {m[1].rstrip(".").casefold() for m in cues}
                cue_scores = {m[1].rstrip(".").casefold(): (1 if m[0].lower().startswith("in ") else 3) for m in cues}
                matches = [(m[1], m.start(1), m.end(1)) for m in cues]
                matches += [(m[0], m.start(), m.end()) for m in re.finditer(r"(?<![\w/])(?:[A-Z][a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*)(?![\w/])", text)]
                for name, begin, end in matches:
                    name = name.rstrip(".")
                    if len(name) < 4 or name.isupper() or name.casefold() in task_terms | generic or name.casefold() == own_name:
                        continue
                    excerpt = text[max(0, begin-65):min(len(text), end+90)]
                    entry = {"mention": name, "repo": candidate["repo"], "hit_index": index, "field": field,
                        "excerpt": excerpt, "requirements": hit.get("requirements", candidate["requirements"]),
                        "source_url": hit["source_url"], "state": "unresolved; literal cue may be an ordinary word"}
                    entry["relationship_cue"] = name.casefold() in cue_names
                    entry["cue_priority"] = max(cue_scores.get(name.casefold(), 0),
                        2 if own_name.startswith(name.casefold() + "-") and name.casefold() in cue_names else 0)
                    if re.match(r"\s+(?:library|framework|SDK|engine)\b", text[end:], re.I):
                        entry["cue_priority"] += 2
                    hints.setdefault(name.casefold(), []).append(entry)
    selected = {name: max(rows, key=lambda x: (bool(critical.intersection(x["requirements"])), x["cue_priority"]))
                for name, rows in hints.items()}
    ranked = sorted(hints, key=lambda name: (-selected[name]["cue_priority"],
        -len({x["repo"] for x in hints[name]}), name))
    return [{**selected[name],
             "observed_in_candidates": len({x["repo"] for x in hints[name]})} for name in ranked[:limit]]


def component_leads(ledger, hints, limit=4):
    """Bounded upstream cues for critical capabilities; identities remain unknown."""
    critical = {r["id"] for r in ledger.get("requirements", []) if r.get("critical")}
    selected = [h for h in hints if h["relationship_cue"] and h["cue_priority"] >= 3
                and critical.intersection(h["requirements"])]
    return [{**h, "id": digest([h["mention"], h["repo"], h["hit_index"], h["field"],
                               h["excerpt"], h["requirements"]])[:20]} for h in selected[:limit]]


def validate_component_leads(ledger, briefs):
    candidates = {c["repo"]: c for c in ledger["candidates"]}
    critical = {r["id"] for r in ledger["requirements"] if r.get("critical")}
    leads = {}
    for lead in briefs.get("component_leads", []):
        candidate = candidates.get(lead.get("repo"))
        index, field = lead.get("hit_index"), lead.get("field")
        if (candidate is None or not isinstance(index, int) or isinstance(index, bool)
                or not 0 <= index < len(candidate["hits"]) or field not in {"description", "title"}):
            raise ValueError("component lead needs its actual originating hit")
        hit = candidate["hits"][index]
        excerpt, mention, refs = lead.get("excerpt"), lead.get("mention"), lead.get("requirements")
        if (not isinstance(excerpt, str) or not excerpt or excerpt not in (hit.get(field) or "")
                or not isinstance(mention, str) or not mention
                or not re.search(r"(?<!\w)" + re.escape(mention) + r"(?!\w)", excerpt, re.I)
                or lead.get("source_url") != hit["source_url"]
                or not isinstance(refs, list) or not refs
                or not set(refs) <= set(hit.get("requirements", candidate["requirements"]))
                or not critical.intersection(refs)):
            raise ValueError("component lead needs an exact source cue and critical requirement binding")
        identity = digest([mention, lead["repo"], index, field, excerpt, refs])[:20]
        if lead.get("id") != identity or identity in leads:
            raise ValueError("component lead IDs must bind unique source cues")
        leads[identity] = lead
    return leads


def validate_whole_shortlist(ledger, briefs=None):
    """Validate protected documentation leads without judging semantic fit."""
    entries = ledger.get("whole_shortlist", [])
    if not isinstance(entries, list):
        raise ValueError("whole_shortlist must be a list")
    sources = {s["id"]: s for s in ledger.get("source_captures", [])}
    seen, cards = set(), []
    for entry in entries:
        identity = entry.get("repo")
        source = sources.get(entry.get("source_id"))
        refs = entry.get("requirements")
        if (not isinstance(identity, str) or identity in seen or not source
                or source["kind"] not in {"readme", "documentation"}
                or source_repo(source["url"]) != identity
                or entry.get("source_url") != source["url"]
                or not isinstance(refs, list) or not refs or len(set(refs)) != len(refs)
                or not isinstance(entry.get("reason"), str) or not entry["reason"].strip()):
            raise ValueError("whole shortlist needs unique canonical repos, primary documentation, requirements and purpose reasons")
        seen.add(identity)
        for req in refs:
            cards.append({"id": "shortlist:" + identity + ":" + str(req), "repo": identity,
                "requirement": req, "source_id": source["id"], "excerpt": entry.get("excerpt"),
                "method": "documented", "state": "unknown", "role": "adaptation",
                "claim": entry["reason"], "limits": "Protected relevance hypothesis; behavior and eligibility remain unverified"})
    review_evidence(ledger, cards)
    if briefs is not None and briefs.get("whole_shortlist", []) != entries:
        raise ValueError("brief packet must retain the unchanged whole shortlist; rebuild briefs after shortlist changes")
    return entries


def protect_whole_solutions(ledger, requests, limit=5):
    """Append host-chosen primary-documentation leads; never silently remove them."""
    if limit < 1 or not isinstance(requests, list):
        raise ValueError("positive whole-shortlist limit and request list required")
    value = copy.deepcopy(ledger)
    entries = copy.deepcopy(validate_whole_shortlist(value))
    sources = {s["id"]: s for s in value.get("source_captures", [])}
    existing = {e["repo"]: e for e in entries}
    for request in requests:
        source = sources.get(request.get("source_id"))
        entry = {key: request.get(key) for key in ("repo", "source_id", "excerpt", "requirements", "reason")}
        entry["source_url"] = source["url"] if source else None
        if entry["repo"] in existing:
            if entry != existing[entry["repo"]]:
                raise ValueError("protected whole lead already exists; retain its origin and update the final assessment")
            continue
        entries.append(entry)
        existing[entry["repo"]] = entry
    if len(entries) > limit:
        raise ValueError("whole shortlist exceeds explicit limit; narrow new selections rather than dropping protected leads")
    value["whole_shortlist"] = entries
    validate_whole_shortlist(value)
    return value


def make_briefs(ledger, limit=100, strategy="legacy"):
    if limit < 1:
        raise ValueError("positive brief limit required")
    protected = validate_whole_shortlist(ledger)
    if len(protected) > limit:
        raise ValueError("brief limit must accommodate the protected whole shortlist")
    base = review_order(ledger, "interleave", max(limit, len(ledger["candidates"])))
    candidates = {c["repo"]: c for c in ledger["candidates"]}
    sources = {s["id"]: s for s in ledger.get("source_captures", [])}
    followed = []
    for source in sources.values():
        links = [source_repo(source["url"])] + [repo_id(m[0]) for m in GITHUB_URL.finditer(source["text"])]
        for identity in links:
            if identity in candidates and identity not in followed and any(
                    lead["source_id"] == source["id"] for lead in candidates[identity].get("source_leads", [])):
                followed.append(identity)
    followed.extend(c["repo"] for c in ledger["candidates"] if c.get("source_leads") and c["repo"] not in followed)
    specialists = []
    for req, lane in base["specialist_lanes"].items():
        specialists.extend(lane["targeted"])
        specialists.extend([r for r in followed if req in candidates[r]["requirements"]][:3])
    # Balance retrieval, specialists and source links: a large directory cannot
    # consume the entire brief budget before ranked candidates are considered.
    specialists = list(dict.fromkeys(specialists))
    ranked = [r for r in base["review_queue"] if any(h.get("provider_rank", None if h.get("indirect") else h.get("rank"))
              for h in candidates[r]["hits"])]
    if strategy not in {"capabilities", "legacy"}:
        raise ValueError("brief strategy must be capabilities or legacy")
    streams = [specialists, ranked, followed]
    if strategy == "capabilities":
        # Allocate across task requirements rather than concatenating their
        # first three cues. Source order stays bounded within each requirement.
        streams = []
        for requirement in ledger.get("requirements", []):
            req = requirement["id"]
            linked = [r for r in followed if req in candidates[r]["requirements"]]
            targeted = [r for r in base["review_queue"] if any(
                h["family"] in {"capability", "ecosystem"} and req in h.get("requirements", [])
                and h.get("provider_rank", None if h.get("indirect") else h.get("rank"))
                for h in candidates[r]["hits"])]
            lane = []
            for depth in range(max(len(linked), len(targeted))):
                for items in (linked, targeted):
                    if depth < len(items) and items[depth] not in lane:
                        lane.append(items[depth])
            if lane:
                streams.append(lane)
        whole = [r for r in ranked if any(h["family"] == "whole" for h in candidates[r]["hits"])]
        streams.extend([whole, ranked])
    order = []
    for depth in range(max([len(s) for s in streams] or [0])):
        for stream in streams:
            if depth < len(stream) and stream[depth] not in order:
                order.append(stream[depth])
        if len(order) >= limit:
            break
    order = list(dict.fromkeys([e["repo"] for e in protected] + order + base["review_queue"]))[:limit]
    terms = tokens(" ".join(r.get("description", "") for r in ledger.get("requirements", [])))
    briefs = []
    for identity in order:
        candidate = candidates[identity]
        passages = []
        def add(text, url, kind):
            if not isinstance(text, str) or not text.strip():
                return
            text = text[:900]
            entry = {"text": text, "source_url": url, "kind": kind}
            entry["id"] = digest([identity, entry])[:20]
            if not any(p["id"] == entry["id"] for p in passages):
                passages.append(entry)
        for entry in protected:
            if entry["repo"] == identity:
                add(entry["excerpt"], entry["source_url"], sources[entry["source_id"]]["kind"])
        for lead in candidate.get("source_leads", []):
            source = sources.get(lead["source_id"])
            if source is None:
                continue
            if source_repo(source["url"]) == identity and source["kind"] != "curated_list":
                for text in snippets(source["text"], terms):
                    add(text, source["url"], source["kind"])
            else:
                for match in re.finditer(r"(?:https?://)?github\.com/[^\s)\]>\"']+", source["text"], re.I):
                    if repo_id(match[0]) == identity:
                        add(link_context(source["text"], match), source["url"], source["kind"])
                        break
        for hit in candidate["hits"]:
            for passage in hit.get("passages", [])[:3]:
                add(passage.get("text") if isinstance(passage, dict) else passage, hit["source_url"], "retrieved_passage")
            add(hit.get("description"), hit["source_url"], "retrieved_description")
            add(hit.get("title"), hit["source_url"], "retrieved_title")
        briefs.append({"repo": identity, "requirements": candidate["requirements"],
                       "discovery_origins": [{k: h.get(k) for k in ("query_id", "phase", "provider", "provider_rank", "source_url")}
                                             for h in candidate["hits"]],
                       "passages": passages[:4], "identity_state": candidate["identity_state"]})
    value = {"task": ledger.get("task"), "requirements": ledger.get("requirements", []), "briefs": briefs,
             "whole_shortlist": protected,
             "allocation_strategy": strategy,
             "mention_hints": mention_hints(ledger),
             "content_gaps": [{"repo": b["repo"], "requirements": b["requirements"],
                 "reason": "No source passages retained; fetch primary documentation before judging fit"}
                 for b in briefs if not b["passages"]],
             "unbriefed_frontpage": [{"repo": r, "requirements": candidates[r]["requirements"],
                 "reason": "Retrieved on a bounded front page; not briefed, fit remains unknown"}
                 for r in ranked if r not in order and any(
                     isinstance(h.get("provider_rank"), int) and h["provider_rank"] <= 10
                     for h in candidates[r]["hits"])],
             "pool_count": len(candidates), "unbriefed_count": len(candidates) - len(briefs),
             "limits": "Descriptions/list entries are leads; screening does not verify functional fit or eligibility."}
    eligible = {**ledger, "candidates": [candidates[r] for r in order]}
    value["component_leads"] = component_leads(ledger, value["mention_hints"])
    value["eligible_baselines"] = {method: review_order(eligible, method, len(order))
                                   for method in ("interleave", "rrf")}
    value["sha256"] = digest(value)
    return value


def recover_mentions(plan, ledger, requests, max_queries=4):
    """Prepare bounded searches from literal names already observed in evidence."""
    check_plan(plan)
    if plan.get("mention_recovery_rounds", 0) or not requests or not 1 <= len(requests) <= max_queries:
        raise ValueError("one bounded mention-recovery round with 1..max_queries requests required")
    value = copy.deepcopy(plan)
    candidates = {c["repo"]: c for c in ledger["candidates"]}
    sources = {s["id"]: s for s in ledger.get("source_captures", [])}
    ids = {q["id"] for q in value["queries"]}
    texts = {q["text"].casefold() for q in value["queries"]}
    added = []
    for request in requests:
        mention = request.get("mention", "")
        if not isinstance(mention, str) or not re.fullmatch(r"[\w .+-]{2,80}", mention):
            raise ValueError("mention must be a short literal project/package name")
        if request.get("source_id") in sources:
            source = sources[request["source_id"]]
            text, refs = source["text"], source["requirements"]
            url = source["url"]
        else:
            candidate = candidates.get(request.get("repo", "").lower())
            index = request.get("hit_index")
            field = request.get("field", "description")
            if candidate is None or not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(candidate["hits"]) or field not in {"description", "title"}:
                raise ValueError("mention needs an actual source ID or retrieved hit/field")
            hit = candidate["hits"][index]
            text, refs = hit.get(field) or "", hit.get("requirements", candidate["requirements"])
            url = hit["source_url"]
        excerpt = request.get("excerpt", "")
        if not excerpt or excerpt not in text or not re.search(r"(?<!\w)" + re.escape(mention) + r"(?!\w)", excerpt, re.I):
            raise ValueError("mention and exact excerpt must occur in its recorded evidence")
        requirements = request.get("requirements", [])
        if not requirements or not set(requirements) <= set(refs) or not request.get("reason"):
            raise ValueError("mention recovery needs evidence-linked requirements and a relevance reason")
        query_text = '"' + mention.strip() + '" in:name,description'
        if query_text.casefold() in texts:
            raise ValueError("duplicate mention recovery query")
        index = 1
        while f"M{index}" in ids:
            index += 1
        qid = f"M{index}"
        ids.add(qid)
        texts.add(query_text.casefold())
        value["queries"].append({"id": qid, "text": query_text, "provider": "github", "family": "ecosystem",
            "requirements": requirements, "recovery_basis": {**request, "source_url": url},
            "identity_resolution": "unknown until actual metadata and host disambiguation"})
        added.append(qid)
    value["mention_recovery_rounds"] = 1
    value["recovery_queries"] = added
    check_plan(value)
    return value


def merge_discovery(ledger, plan, packets):
    """Add captured retrieval without discarding enriched candidate/source bindings."""
    if ledger["requirements"] != plan["requirements"]:
        raise ValueError("new discovery must retain the unchanged task requirements")
    value = copy.deepcopy(ledger)
    added = build_ledger(plan, packets)
    existing = {c["repo"]: c for c in value["candidates"]}
    for candidate in added["candidates"]:
        identity = candidate["repo"]
        if identity not in existing:
            value["candidates"].append(candidate)
            existing[identity] = candidate
            value["triage_complete"] = False
        else:
            target = existing[identity]
            target["requirements"] = sorted(set(target["requirements"] + candidate["requirements"]))
            for field in ("hits", "metadata"):
                for row in candidate[field]:
                    if row not in target[field]:
                        target[field].append(row)
            if candidate["identity_state"] == "github_metadata":
                target["identity_state"] = "github_metadata"
    for field in ("query_records", "discovery_sources"):
        for row in added[field]:
            if row not in value.setdefault(field, []):
                value[field].append(row)
    value["unrun_queries"] = [q["id"] for q in plan["queries"] if not any(
        r["query_id"] == q["id"] for r in value["query_records"])]
    for req, state in added["coverage"].items():
        prior = value["coverage"][req]
        for field in ("planned", "successful_queries"):
            prior[field] = list(dict.fromkeys(prior[field] + state[field]))
        prior["discovery_state"] = "reached" if prior["successful_queries"] else "unknown"
    value["candidates"].sort(key=lambda c: c["repo"])
    return value


def rank_briefs(briefs, judgments, limit=20):
    unsigned = {k: v for k, v in briefs.items() if k != "sha256"}
    if briefs.get("sha256") != digest(unsigned) or judgments.get("briefs_sha256") != briefs["sha256"]:
        raise ValueError("judgments must bind to the unchanged brief packet")
    if limit < 1:
        raise ValueError("positive review limit required")
    candidates = {b["repo"]: b for b in briefs["briefs"]}
    positions = {identity: index for index, identity in enumerate(candidates)}
    requirements = {r["id"] for r in briefs["requirements"]}
    seen = set()
    rows = judgments.get("judgments", [])
    for row in rows:
        identity, req = row.get("repo"), row.get("requirement")
        pair = identity, req
        if identity not in candidates or req not in requirements or pair in seen:
            raise ValueError("screening requires unique retrieved repo/requirement pairs")
        seen.add(pair)
        passages = {p["id"]: p for p in candidates[identity]["passages"]}
        if row.get("passage_id") not in passages or not row.get("reason"):
            raise ValueError("screening needs an actual candidate passage and a reason")
        if row.get("adoption") not in PRIORITY or row.get("study") not in PRIORITY:
            raise ValueError("separate adoption/study priorities must be high/medium/low/unknown")
    lanes = {}
    queue = []
    protected = [e["repo"] for e in briefs.get("whole_shortlist", [])]
    if len(set(protected)) != len(protected) or not set(protected) <= set(candidates):
        raise ValueError("protected whole leads must remain unique and briefed")
    for req in sorted(requirements):
        lanes[req] = {}
        for role in ("adoption", "study"):
            selected = sorted((r for r in rows if r["requirement"] == req and PRIORITY[r[role]] >= 2),
                              key=lambda r: (-PRIORITY[r[role]], positions[r["repo"]]))
            lanes[req][role] = [r["repo"] for r in selected]
    # Round-robin capability/role lanes rather than a popularity-weighted global sum.
    streams = ([protected] if protected else []) + [rs for lane in lanes.values() for rs in lane.values()]
    for depth in range(max([len(rs) for rs in streams] or [0])):
        for rs in streams:
            if depth < len(rs) and rs[depth] not in queue:
                queue.append(rs[depth])
    queue.extend(r for r in candidates if r not in queue)
    return {"briefs_sha256": briefs["sha256"], "judgments": rows, "lanes": lanes,
            "whole_shortlist": protected, "review_queue": queue[:limit],
            "judged_pairs": len(rows), "judged_repos": len({r["repo"] for r in rows}),
            "unjudged_repos": len(candidates) - len({r["repo"] for r in rows}),
            "limits": "Semantic screening is host-agent judgment about inspection priority, not adoption evidence. Low/unjudged candidates remain in the ledger."}


def expand_plan(plan, review, requests, max_queries=4, ledger=None):
    check_plan(plan)
    if plan.get("expansion_rounds", 0) >= 1:
        raise ValueError("bounded expansion round already used")
    if not requests or len(requests) > max_queries:
        raise ValueError("one to max_queries expansion requests required")
    value = json.loads(json.dumps(plan))
    seen = {" ".join(q["text"].lower().split()) for q in plan["queries"]}
    ids = {q["id"] for q in plan["queries"]}
    added = []
    for request in requests:
        req = request.get("requirement")
        if req not in review.get("gaps", {}) or not request.get("gap_reason"):
            raise ValueError("expansion needs a known requirement gap and explicit reason")
        if request.get("basis") not in {"task", "observed_source"} or not request.get("basis_text"):
            raise ValueError("expansion needs task/source terminology and its recorded basis")
        if request["basis"] == "observed_source" and not request.get("source_url"):
            raise ValueError("observed-source expansion requires its source URL")
        if request["basis"] == "observed_source":
            sources = [s for s in (ledger or {}).get("source_captures", []) if s["url"] == request["source_url"]]
            if not any(request["basis_text"] in s["text"] for s in sources):
                raise ValueError("source expansion basis must occur in a captured source")
        else:
            task_text = " ".join([plan.get("task", "")] + [r.get("description", "") for r in plan["requirements"]])
            if request["basis_text"] not in task_text:
                raise ValueError("task expansion basis must quote the task/requirement brief")
        text = request.get("text", "").strip()
        if not text or " ".join(text.lower().split()) in seen:
            raise ValueError("expansion query must be new and nonempty")
        seen.add(" ".join(text.lower().split()))
        index = 1
        while "X" + str(index) in ids:
            index += 1
        qid = "X" + str(index)
        ids.add(qid)
        query = {"id": qid, "text": text, "provider": request.get("provider"),
                 "family": request.get("family", "capability"), "requirements": [req], "expansion_basis": request,
                 "prior_gap_state": review["gaps"][req]["state"]}
        value["queries"].append(query)
        added.append(qid)
    value["expansion_rounds"] = 1
    value["expansion_queries"] = added
    check_plan(value)
    return value


def case_inventory(ledger, review, cases):
    review_evidence(ledger, review["cards"])
    cards = {c["id"]: c for c in review["cards"]}
    sources = {s["id"]: s for s in ledger.get("source_captures", [])}
    seen = set()
    for case in cases:
        cid = case.get("id")
        card = cards.get(case.get("card_id"))
        if not cid or cid in seen or card is None:
            raise ValueError("case needs unique ID and existing evidence card")
        seen.add(cid)
        source = sources.get(card["source_id"])
        if source is None or source["kind"] == "curated_list":
            raise ValueError("cases require primary evidence, not a curated-list claim")
        excerpt = case.get("excerpt", "")
        if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in source["text"]:
            raise ValueError("case excerpt must occur in its captured source")
        if case.get("current_state") not in {"covered", "missing", "unknown", "needs_validation"}:
            raise ValueError("case current_state must be covered/missing/unknown/needs_validation")
        if case["current_state"] in {"covered", "missing"} and not case.get("current_evidence"):
            raise ValueError("claims about current implementation need current-project evidence")
        if any(not case.get(field) for field in ("input_or_trigger", "observed_behavior", "applicability", "proposed_check")):
            raise ValueError("case needs trigger, behavior, applicability and proposed check")
    return {"task": ledger.get("task"), "cases": cases, "created_at": now(),
            "limits": "Source-observed cases are not exhaustive. Proposed checks were not run; inferred applicability needs project validation."}


def resolve_relations(ledger, records, limit=6):
    """Resolve selected package leads from actual registry and GitHub metadata captures."""
    if not records or len(records) > limit:
        raise ValueError("one to limit selected dependency resolutions required")
    value = copy.deepcopy(ledger)
    sources = {s["id"]: s for s in value.get("source_captures", [])}
    candidates = {c["repo"]: c for c in value["candidates"]}
    known = set(sources)
    for record in records:
        parent = sources.get(record.get("source_id"))
        if parent is None or parent["kind"] != "manifest" or parent.get("inspection_only"):
            raise ValueError("dependency discovery requires a captured original manifest, within one hop")
        package = record.get("package", "")
        if not package or package not in parent["text"] or not record.get("reason"):
            raise ValueError("selected package must occur in manifest and have a relevance reason")
        registry_text, url = record.get("registry_text", ""), record.get("repo_url", "")
        requested = source_repo(url)
        metadata = record.get("github_metadata", {})
        identity = source_repo(metadata.get("html_url", ""))
        if not requested or url not in registry_text or not identity or metadata.get("full_name", "").lower() != identity:
            raise ValueError("actual registry source link and canonical GitHub metadata required")
        if requested != identity and record.get("redirect_from", "").lower() != requested:
            raise ValueError("canonical redirect must preserve its observed original repository")
        if not record.get("registry_url", "").startswith("https://") or not record.get("observed_at"):
            raise ValueError("registry URL and observation time required")
        reqs = record.get("requirements", parent["requirements"])
        if not reqs or not set(reqs) <= set(value["coverage"]):
            raise ValueError("dependency requirements must be known")
        sid = "registry-" + digest(record)[:16]
        if sid in known:
            raise ValueError("duplicate dependency resolution")
        known.add(sid)
        capture = {"id": sid, "url": record["registry_url"], "kind": "metadata", "text": registry_text,
                   "observed_at": record["observed_at"], "requirements": reqs, "parent_url": parent["url"],
                   "depth": 1, "sha256": hashlib.sha256(registry_text.encode("utf-8")).hexdigest()}
        value["source_captures"].append(capture)
        candidate = candidates.get(identity)
        if candidate is None:
            candidate = {"repo": identity, "url": metadata["html_url"], "requirements": [], "hits": [], "metadata": [],
                         "triage": {"disposition": "pending", "reason": None}, "verification": "unverified"}
            value["candidates"].append(candidate)
            candidates[identity] = candidate
            value["triage_complete"] = False
        candidate["identity_state"] = "github_metadata"
        candidate["requirements"] = sorted(set(candidate["requirements"] + reqs))
        candidate["metadata"].append(metadata)
        candidate.setdefault("source_leads", []).append({"source_id": sid, "source_url": record["registry_url"],
                      "parent_url": parent["url"], "depth": 1, "requirements": reqs, "relation": "dependency",
                      "package": package, "reason": record["reason"], "requested_repo": requested,
                      "canonical_repo": identity, "github_metadata": metadata})
    value["candidates"].sort(key=lambda c: c["repo"])
    return value


def cache_put(root, ledger, review, cases=None):
    if not review.get("cards"):
        raise ValueError("cache requires evidence cards, not retrieval alone")
    review_evidence(ledger, review["cards"])
    if cases:
        case_inventory(ledger, review, cases["cases"])
    wanted = {c["source_id"] for c in review["cards"]}
    entry = {"task": ledger.get("task"), "requirements": ledger.get("requirements", []), "cards": review["cards"],
             "sources": [s for s in ledger.get("source_captures", []) if s["id"] in wanted],
             "cases": cases.get("cases", []) if cases else [], "recorded_at": now()}
    key = digest(entry)
    write_json(Path(root) / (key + ".json"), entry)
    return {"entry": key, "cache": str(root), "state": "historical_evidence"}


def cache_find(root, query, revisions=None, max_age_days=7):
    if max_age_days < 0:
        raise ValueError("cache age limit must be nonnegative")
    revisions = revisions or {}
    matched = []
    for path in sorted(Path(root).glob("*.json")):
        entry = read_json(path)
        if path.stem != digest(entry):
            raise ValueError("cache entry content hash mismatch")
        saved_sources = {s["id"]: s for s in entry["sources"]}
        for source in saved_sources.values():
            validate_capture(source)
        for card in entry["cards"]:
            source = saved_sources.get(card["source_id"])
            if source is None or card["excerpt"] not in source["text"] or (
                    card["method"] == "inspected" and not pinned_source(source, card["repo"])):
                raise ValueError("cache evidence source binding mismatch")
        text = json.dumps([entry["task"], entry["requirements"], entry["cards"]], ensure_ascii=False)
        overlap = len(tokens(query) & tokens(text))
        if not overlap:
            continue
        ages = []
        unknown_time = False
        for source in entry["sources"]:
            try:
                observed = dt.datetime.fromisoformat(source["observed_at"].replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=dt.timezone.utc)
                ages.append((dt.datetime.now(dt.timezone.utc) - observed).total_seconds() / 86400)
            except (ValueError, KeyError):
                unknown_time = True
        changed = [s["id"] for s in entry["sources"] if source_repo(s["url"]) in revisions
                   and s.get("revision") != revisions[source_repo(s["url"])]]
        matched.append({"entry": path.stem, "task": entry["task"], "lexical_overlap": overlap,
                        "refresh_required": unknown_time or any(age > max_age_days for age in ages) or bool(changed), "changed_sources": changed,
                        "state": "historical_evidence", "adoption_health_refresh_required": True})
    return {"matches": sorted(matched, key=lambda r: (-r["lexical_overlap"], r["entry"]))[:20],
            "limits": "Cache matches are leads. Pinned observations remain historical; refresh decisive current facts and never turn missing cache entries into absence claims."}


def benchmark_score(ledger, queue, judgments):
    candidates = {c["repo"] for c in ledger["candidates"]}
    selected = set(queue)
    if not selected <= candidates:
        raise ValueError("benchmark queue must be a subset of its candidate ledger")
    positives, negatives = set(), set()
    for row in judgments:
        if not row.get("source") or not row.get("reason") or row.get("relevance") not in {"high", "partial", "irrelevant"}:
            raise ValueError("benchmark labels need primary source, reason and relevance")
        identity = row["repo"].lower()
        (negatives if row["relevance"] == "irrelevant" else positives).add(identity)
    if positives & negatives:
        raise ValueError("conflicting repository judgments; resolve context before scoring")
    judged = selected & (positives | negatives)
    return {"judgments_sha256": digest(judgments), "positive_count": len(positives),
            "positive_retrieved": len(positives & candidates), "positive_in_queue": len(positives & selected),
            "queue_size": len(selected), "judged_queue_size": len(judged),
            "judged_precision": len(selected & positives) / len(judged) if judged else None,
            "unjudged_queue_count": len(selected - positives - negatives),
            "limits": "Freeze judgments before evaluation. Precision covers judged items only; unjudged items are not negatives and partial relevance is not adoption eligibility."}


def reconcile_selection(ledger, briefs, screened, review, records, report):
    """Account for queued/high-priority leads without certifying semantic fit."""
    rank_briefs(briefs, screened, max(1, len(briefs["briefs"])))
    protected = validate_whole_shortlist(ledger, briefs)
    review_evidence(ledger, review.get("cards", []))
    candidates = {c["repo"] for c in ledger["candidates"]}
    briefed = {b["repo"] for b in briefs["briefs"]}
    queued = screened.get("review_queue", [])
    if len(set(queued)) != len(queued) or not set(queued) <= briefed:
        raise ValueError("selection queue must contain unique briefed identities")
    strong = {j["repo"] for j in screened["judgments"]
              if j["adoption"] == "high" or j["study"] == "high"}
    cards = review.get("cards", [])
    required = set(queued) | strong | {c["repo"] for c in cards} | {e["repo"] for e in protected}
    if not required <= candidates:
        raise ValueError("selection identities must remain in the final ledger")
    supplied = {}
    for record in records.get("candidates", []):
        identity = record.get("repo", "").lower()
        if identity not in candidates or identity in supplied:
            raise ValueError("unknown/duplicate selection record")
        if not isinstance(record.get("reason"), str) or not record["reason"].strip():
            raise ValueError("selection records need a concrete inspection/deferral reason")
        supplied[identity] = record
    methods = {}
    for card in cards:
        methods.setdefault(card["repo"], set()).add(card["method"])
    visible_links = {repo_id(m[0]) for m in GITHUB_URL.finditer(report)}
    rows, gaps = [], []
    for identity in sorted(required):
        # Full owner/name prose is also visible; unrelated same-name projects are not.
        visible = identity in visible_links or bool(re.search(
            r"(?<![\w./-])" + re.escape(identity) + r"(?![\w./-])", report, re.I))
        reason = supplied.get(identity, {}).get("reason")
        priorities = [j for j in screened["judgments"] if j["repo"] == identity]
        row = {"repo": identity, "queue_position": queued.index(identity) + 1 if identity in queued else None,
               "high_priority": identity in strong, "screening": priorities,
               "methods": sorted(methods.get(identity, [])), "reason": reason,
               "report_visible": visible, "source_inspection_missing": "inspected" not in methods.get(identity, set())}
        rows.append(row)
        if not reason or not visible:
            gaps.append({"repo": identity, "missing": [key for key, ok in [("reason", bool(reason)), ("report_visibility", visible)] if not ok]})
    whole_rows = []
    report_text = " ".join(report.replace("\\|", "|").split())
    for entry in protected:
        record = supplied.get(entry["repo"], {})
        next_check = record.get("next_check")
        visible = next(r["report_visible"] for r in rows if r["repo"] == entry["repo"])
        primary_visible = entry["source_url"] in report
        assessment_visible = bool(record.get("reason")) and " ".join(record["reason"].split()) in report_text
        next_visible = isinstance(next_check, str) and bool(next_check.strip()) and " ".join(next_check.split()) in report_text
        whole_rows.append({**entry, "assessment": record.get("reason"), "next_check": next_check,
            "report_visible": visible, "primary_source_visible": primary_visible,
            "assessment_visible": assessment_visible, "next_check_visible": next_visible,
            "source_inspected": "inspected" in methods.get(entry["repo"], set())})
        missing = ([] if isinstance(next_check, str) and next_check.strip() else ["next_check"])
        missing += [] if primary_visible else ["primary_source_visibility"]
        missing += [] if assessment_visible else ["assessment_visibility"]
        missing += [] if next_visible else ["next_check_visibility"]
        if missing:
            gaps.append({"stage": "whole_shortlist", "repo": entry["repo"], "missing": missing})
    whole = records.get("whole_purpose", {})
    whole_state = "unknown"
    if whole.get("card_id"):
        card = next((c for c in cards if c["id"] == whole["card_id"]), None)
        sources = {s["id"]: s for s in ledger.get("source_captures", [])}
        if (not card or card["repo"] != whole.get("repo", "").lower() or not whole.get("reason")
                or sources[card["source_id"]]["kind"] not in {"readme", "documentation"}
                or source_repo(sources[card["source_id"]]["url"]) != card["repo"]):
            raise ValueError("whole-purpose review needs a matching primary documentation card and role reason")
        whole_state = "primary_documentation_reviewed"
    elif not isinstance(whole.get("deferred_reason"), str) or not whole["deferred_reason"].strip():
        gaps.append({"stage": "whole_purpose", "missing": ["primary_documentation_or_explicit_deferral"]})
    leads = validate_component_leads(ledger, briefs)
    dispositions = {}
    for record in records.get("component_leads", []):
        identity = record.get("lead_id")
        if identity not in leads or identity in dispositions:
            raise ValueError("unknown/duplicate component lead record")
        if (record.get("status") not in {"resolved", "deferred", "dismissed"}
                or not isinstance(record.get("reason"), str) or not record["reason"].strip()):
            raise ValueError("component leads need resolved/deferred/dismissed status and a reason")
        if record["status"] == "resolved":
            resolved = record.get("repos")
            if not isinstance(resolved, list) or not resolved or not all(
                    isinstance(r, str) and r.lower() in candidates for r in resolved):
                raise ValueError("resolved component leads need actual retained canonical repositories")
        dispositions[identity] = record
    lead_rows = []
    for identity, lead in leads.items():
        visible = bool(re.search(r"(?<!\w)" + re.escape(lead["mention"]) + r"(?!\w)", report, re.I)) and lead["source_url"] in report
        lead_rows.append({**lead, "disposition": dispositions.get(identity), "report_visible": visible})
        missing = ([] if identity in dispositions else ["resolution_or_explicit_deferral"]) + ([] if visible else ["report_visibility"])
        if missing:
            gaps.append({"stage": "component_lead", "lead_id": identity, "mention": lead["mention"], "missing": missing})
    return {"created_at": now(), "briefs_sha256": briefs["sha256"], "report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
            "required_count": len(required), "rows": rows, "gaps": gaps, "whole_purpose": whole,
            "component_leads": lead_rows,
            "whole_shortlist": whole_rows,
            "whole_purpose_state": whole_state, "accounted": not gaps,
            "limits": "Accountability only: priorities, deferral quality and whole-purpose fit remain host judgments. Visibility is not endorsement, inspection is not execution, and accounted does not certify recall, timing or adoption."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("briefs", "shortlist", "rank", "expand", "mentions", "merge-new", "cases", "relations", "cache-put", "cache-find", "score", "reconcile"):
        part = sub.add_parser(command)
        part.add_argument("--out", required=True)
        if command in {"briefs", "shortlist", "expand", "mentions", "merge-new", "cases", "relations", "cache-put", "score", "reconcile"}:
            part.add_argument("--ledger", required=True)
        if command in {"expand", "cases", "cache-put", "reconcile"}:
            part.add_argument("--review", required=True)
        if command in {"briefs", "rank"}:
            part.add_argument("--limit", type=int, default=100 if command == "briefs" else 20)
        if command in {"rank", "score"}:
            part.add_argument("--judgments", required=True)
        if command in {"rank", "reconcile"}:
            part.add_argument("--briefs", required=True)
        if command == "relations":
            part.add_argument("--records", required=True)
            part.add_argument("--limit", type=int, default=6)
        if command == "briefs":
            part.add_argument("--strategy", choices=["capabilities", "legacy"], default="legacy")
        if command in {"expand", "mentions"}:
            part.add_argument("--plan", required=True)
            part.add_argument("--requests", required=True)
            part.add_argument("--max-queries", type=int, default=4)
        if command == "shortlist":
            part.add_argument("--requests", required=True)
            part.add_argument("--limit", type=int, default=5)
        if command == "merge-new":
            part.add_argument("--plan", required=True)
            part.add_argument("--packets", nargs="+", required=True)
        if command in {"cases", "cache-put"}:
            part.add_argument("--cases", required=command == "cases")
        if command.startswith("cache-"):
            part.add_argument("--cache", required=True)
        if command == "cache-find":
            part.add_argument("--query", required=True)
            part.add_argument("--revisions")
            part.add_argument("--max-age-days", type=float, default=7)
        if command == "score":
            part.add_argument("--queue", required=True)
        if command == "reconcile":
            part.add_argument("--screened", required=True)
            part.add_argument("--records", required=True)
            part.add_argument("--report", required=True)
            part.add_argument("--strict", action="store_true", help="Exit 1 when selection/report accountability gaps remain")
    args = parser.parse_args(argv)
    try:
        if args.command == "briefs":
            value = make_briefs(read_json(args.ledger), args.limit, args.strategy)
        elif args.command == "shortlist":
            value = protect_whole_solutions(read_json(args.ledger), read_json(args.requests), args.limit)
        elif args.command == "rank":
            value = rank_briefs(read_json(args.briefs), read_json(args.judgments), args.limit)
        elif args.command == "expand":
            value = expand_plan(read_json(args.plan), read_json(args.review), read_json(args.requests), args.max_queries, read_json(args.ledger))
        elif args.command == "mentions":
            value = recover_mentions(read_json(args.plan), read_json(args.ledger), read_json(args.requests), args.max_queries)
        elif args.command == "merge-new":
            packets = []
            for path in args.packets:
                if Path(path).is_dir():
                    packets.extend(read_json(p) for p in sorted(Path(path).glob("*.json")))
                else:
                    packet = read_json(path)
                    packets.extend(packet if isinstance(packet, list) else [packet])
            value = merge_discovery(read_json(args.ledger), read_json(args.plan), packets)
        elif args.command == "cases":
            value = case_inventory(read_json(args.ledger), read_json(args.review), read_json(args.cases))
        elif args.command == "relations":
            value = resolve_relations(read_json(args.ledger), read_json(args.records), args.limit)
        elif args.command == "cache-put":
            value = cache_put(args.cache, read_json(args.ledger), read_json(args.review), read_json(args.cases) if args.cases else None)
        elif args.command == "cache-find":
            value = cache_find(args.cache, args.query, read_json(args.revisions) if args.revisions else None, args.max_age_days)
        elif args.command == "reconcile":
            value = reconcile_selection(read_json(args.ledger), read_json(args.briefs), read_json(args.screened),
                                        read_json(args.review), read_json(args.records), Path(args.report).read_text(encoding="utf-8"))
        else:
            value = benchmark_score(read_json(args.ledger), read_json(args.queue)["review_queue"], read_json(args.judgments))
        write_json(args.out, value)
        if args.command == "reconcile" and args.strict and not value["accounted"]:
            return 1
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
