#!/usr/bin/env python3
"""Replay captured sources, preserve one-hop leads, and prepare bounded evidence review.

No model, network calls, candidate execution, or automatic adoption decisions.
"""
import argparse
import copy
import hashlib
import re
import sys
import urllib.parse

from reuse_search import GITHUB_URL, now, read_json, repo_id, write_json

KINDS = {"readme", "documentation", "curated_list", "manifest", "code", "test", "issue", "metadata"}
STATES = {"supported", "partial", "contradicted", "unknown"}
ROLES = {"dependency", "adaptation", "study"}


def source_repo(url):
    """Primary GitHub file/API URLs establish a source's own repository identity."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        return None
    path = parsed.path.strip("/").split("/")
    if parsed.hostname in {"github.com", "www.github.com", "raw.githubusercontent.com"} and len(path) >= 2:
        return repo_id("https://github.com/" + "/".join(path[:2]))
    if parsed.hostname == "api.github.com" and len(path) >= 3 and path[0] == "repos":
        return repo_id("https://github.com/" + "/".join(path[1:3]))
    return None


def validate_capture(source):
    """Check retained text integrity; this is not remote-source authentication."""
    content = source.get("text")
    if not isinstance(content, str) or source.get("sha256") != hashlib.sha256(content.encode("utf-8")).hexdigest():
        raise ValueError(f"{source.get('id')}: captured source text hash mismatch")


def pinned_source(source, identity):
    revision = source.get("revision", "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision) or source_repo(source["url"]) != identity:
        return False
    url = urllib.parse.urlsplit(source["url"])
    path = url.path.strip("/").split("/")
    ref = None
    if url.hostname in {"github.com", "www.github.com"} and len(path) >= 5 and path[2] == "blob":
        ref = path[3]
    elif url.hostname == "raw.githubusercontent.com" and len(path) >= 4:
        ref = path[2]
    elif url.hostname == "api.github.com" and len(path) >= 5 and path[:1] == ["repos"] and path[3] == "contents":
        refs = urllib.parse.parse_qs(url.query).get("ref", [])
        ref = refs[0] if len(refs) == 1 else None
    return isinstance(ref, str) and ref.lower() == revision.lower()


def follow_sources(ledger, sources, max_sources=12, max_links=100):
    """Import actual host-fetched source captures; a source is at most one hop from retrieval."""
    value = copy.deepcopy(ledger)
    captures = value.setdefault("source_captures", [])
    for capture in captures:
        validate_capture(capture)
    identities = {c["repo"]: c for c in value["candidates"]}
    known_ids = {s["id"] for s in captures}
    roots = {s["url"]: s for s in value.get("discovery_sources", [])}
    for candidate in value["candidates"]:
        if candidate["hits"]:
            roots.setdefault(candidate["url"], {"requirements": candidate["requirements"]})
        for hit in candidate["hits"]:
            roots.setdefault(hit["source_url"], {"requirements": candidate["requirements"]})
    requirements = set(value["coverage"])
    if len(captures) + len(sources) > max_sources:
        raise ValueError("source budget exceeded; choose consequential sources explicitly")
    if max_links < 1:
        raise ValueError("max_links must be positive")
    for source in sources:
        sid = source.get("id")
        if not isinstance(sid, str) or not sid or sid in known_ids:
            raise ValueError("source IDs must be unique nonempty strings")
        known_ids.add(sid)
        parent = source.get("parent_url")
        # Inspecting a newly discovered component is permitted, but its outgoing
        # links cannot initiate another discovery hop.
        inspection_repo = source_repo(source.get("url", ""))
        inspect_only = (parent not in roots and inspection_repo in identities
                        and parent == identities[inspection_repo]["url"]
                        and source.get("kind") != "curated_list")
        if parent not in roots and not inspect_only:
            raise ValueError(f"{sid}: parent must be an original retrieved source/candidate URL")
        refs = source.get("requirements", [])
        parent_refs = identities[inspection_repo]["requirements"] if inspect_only else roots[parent]["requirements"]
        if not refs or not set(refs) <= requirements:
            raise ValueError(f"{sid}: requirement mapping must use known task requirements")
        if not set(refs) <= set(parent_refs) and not source.get("association_reason"):
            raise ValueError(f"{sid}: newly observed requirement association needs an explicit reason")
        content = source.get("text")
        if not isinstance(content, str) or not content.strip() or len(content) > 262144:
            raise ValueError(f"{sid}: actual source text required, maximum 256 KiB characters")
        if source.get("kind") not in KINDS or not source.get("url", "").startswith("https://") or not source.get("observed_at"):
            raise ValueError(f"{sid}: kind, HTTPS source URL and observation time required")
        capture = {**source, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "depth": 1,
                   "inspection_only": inspect_only}
        links = list(dict.fromkeys(repo_id(m[0]) for m in GITHUB_URL.finditer(content) if repo_id(m[0])))
        # A fetched primary repository file may supply evidence about its own repository.
        own_repo = source_repo(source["url"])
        if own_repo:
            links = [own_repo] + [identity for identity in links if identity != own_repo]
        if inspect_only:
            links = [identity for identity in links if identity in identities]
        capture["link_count"] = len(links)
        capture["links_bounded"] = len(links) > max_links
        captures.append(capture)
        for identity in links[:max_links]:
            candidate = identities.get(identity)
            if candidate is None:
                candidate = {"repo": identity, "url": "https://github.com/" + identity,
                             "identity_state": "retrieved_link", "requirements": [], "hits": [], "metadata": [],
                             "triage": {"disposition": "pending", "reason": None}, "verification": "unverified"}
                value["candidates"].append(candidate)
                identities[identity] = candidate
                value["triage_complete"] = False
            candidate["requirements"] = sorted(set(candidate["requirements"] + refs))
            candidate.setdefault("source_leads", []).append({"source_id": sid, "source_url": source["url"],
                                                           "parent_url": parent, "depth": 1, "requirements": refs,
                                                           "association_reason": source.get("association_reason")})
    value["candidates"].sort(key=lambda c: c["repo"])
    return value


def review_order(ledger, method="interleave", limit=20):
    """RRF is a review-order experiment. Keep a separate per-requirement specialist lane."""
    if method not in {"interleave", "rrf"} or limit < 1:
        raise ValueError("method interleave/rrf and positive limit required")
    votes = {}
    streams = {}
    candidates = {c["repo"]: c for c in ledger["candidates"]}
    for candidate in candidates.values():
        groups = {}
        for hit in candidate["hits"]:
            rank = hit.get("provider_rank", None if hit.get("indirect") else hit["rank"])
            if rank is None:
                continue
            if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
                raise ValueError("provider ranks must be positive integers or null")
            group = hit.get("vote_group", hit["query_id"])
            groups[group] = min(groups.get(group, rank), rank)
        votes[candidate["repo"]] = sum(1 / (60 + rank) for rank in groups.values())
        for group, rank in groups.items():
            streams.setdefault(group, []).append((rank, candidate["repo"]))
    for entries in streams.values():
        entries.sort()
    if method == "rrf":
        order = sorted(candidates, key=lambda r: (-votes[r], r))
    else:
        order = []
        seen = set()
        depth = 0
        while any(depth < len(entries) for entries in streams.values()):
            for group in sorted(streams):
                if depth < len(streams[group]):
                    identity = streams[group][depth][1]
                    if identity not in seen:
                        order.append(identity)
                        seen.add(identity)
            depth += 1
        order.extend(sorted(set(candidates) - seen))
    # Discovery maps are hypotheses, not relevance judgments. Separate lanes avoid
    # erasing a low-vote specialist or a useful underlying source-link candidate.
    lanes = {}
    for req in ledger["coverage"]:
        pool = [r for r in order if req in candidates[r]["requirements"]]
        targeted = [r for r in pool if any(h["family"] in {"ecosystem", "capability"}
                     and req in h.get("requirements", candidates[r]["requirements"]) for h in candidates[r]["hits"])]
        followed = [r for r in pool if any(req in lead["requirements"] for lead in candidates[r].get("source_leads", []))]
        lanes[req] = {"targeted": targeted[:3], "followed": followed[:3]}
    return {"method": method, "review_queue": order[:limit], "specialist_lanes": lanes,
            "candidate_count": len(candidates), "queue_count": min(limit, len(order)),
            "unqueued_count": max(0, len(order) - limit), "rrf_scores": votes if method == "rrf" else None,
            "limits": "Order is a retrieval hint, never evidence of fit. Lanes are additional review cues; the full ledger is retained."}


def review_evidence(ledger, cards, method="interleave", limit=20):
    candidates = {c["repo"]: c for c in ledger["candidates"]}
    for capture in ledger.get("source_captures", []):
        validate_capture(capture)
    sources = {s["id"]: s for s in ledger.get("source_captures", [])}
    seen = set()
    by_req = {r: [] for r in ledger["coverage"]}
    for card in cards:
        cid, identity, req = card.get("id"), card.get("repo"), card.get("requirement")
        if not cid or cid in seen or identity not in candidates or req not in by_req:
            raise ValueError("card needs unique ID, retrieved repo and known requirement")
        seen.add(cid)
        source = sources.get(card.get("source_id"))
        if source is None or req not in source["requirements"]:
            raise ValueError(f"{cid}: captured source must cover this requirement")
        if not any(lead["source_id"] == source["id"] for lead in candidates[identity].get("source_leads", [])):
            raise ValueError(f"{cid}: source must explicitly link to this candidate; captured source "
                             f"{source['id']} has no matching candidate.source_leads record. Import it "
                             "with follow and preserve candidate/source bindings when copying a ledger.")
        if card.get("state") not in STATES or card.get("role") not in ROLES:
            raise ValueError(f"{cid}: valid evidence state and reuse role required")
        excerpt = card.get("excerpt", "")
        if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in source["text"]:
            raise ValueError(f"{cid}: verbatim excerpt must occur in captured source")
        if not card.get("claim") or not card.get("limits"):
            raise ValueError(f"{cid}: claim and limitations required")
        method_name = card.get("method")
        if method_name not in {"documented", "inspected"}:
            raise ValueError(f"{cid}: use documented/inspected; runtime testing belongs in the experiment report")
        if method_name == "inspected" and (source["kind"] not in {"code", "test", "manifest"}
                                           or not pinned_source(source, identity)):
            raise ValueError(f"{cid}: inspected evidence requires code/test/manifest URL pinned to the recorded commit")
        if source["kind"] == "curated_list" and card["state"] != "unknown":
            raise ValueError(f"{cid}: curated lists supply leads, not functional-fit evidence")
        by_req[req].append(card)
    gaps = {}
    for req, findings in by_req.items():
        hypotheses = [r for r, c in candidates.items() if req in c["requirements"]]
        reviewed = {c["repo"] for c in findings}
        if any(c["state"] == "supported" for c in findings):
            state = "evidence_backed_candidate"
        elif any(c["state"] == "partial" for c in findings):
            state = "partial_evidence"
        elif set(hypotheses) - reviewed:
            state = "unreviewed_leads"
        elif findings and all(c["state"] == "contradicted" for c in findings):
            state = "reviewed_unsuitable"
        elif hypotheses:
            state = "decisive_unknown"
        else:
            state = "no_retrieved_lead"
        gaps[req] = {"state": state, "candidate_count": len(hypotheses), "reviewed_count": len(reviewed),
                     "unreviewed_count": len(set(hypotheses) - reviewed), "card_ids": [c["id"] for c in findings],
                     "next": "Verify decisive source/eligibility gates" if state == "evidence_backed_candidate" else
                             "One bounded expansion using source-observed terminology, or report the unresolved gap"}
    return {"created_at": now(), "ordering": review_order(ledger, method, limit), "cards": cards, "gaps": gaps,
            "stages": {"retrieved": len(candidates), "queued": min(limit, len(candidates)),
                       "source_captured": len(sources), "evidence_reviewed": len({c["repo"] for c in cards}),
                       "source_inspected": len({c["repo"] for c in cards if c["method"] == "inspected"})},
            "limits": "Excerpt checks validate provenance, not the agent's interpretation. Evidence-backed is not adoption-ready; eligibility, integration and case transfer still need judgment."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("follow", "review"):
        part = sub.add_parser(command)
        part.add_argument("--ledger", required=True)
        part.add_argument("--out", required=True)
        if command == "follow":
            part.add_argument("--sources", required=True)
            part.add_argument("--max-sources", type=int, default=12)
            part.add_argument("--max-links", type=int, default=100)
        else:
            part.add_argument("--cards")
            part.add_argument("--method", choices=["interleave", "rrf"], default="interleave")
            part.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        ledger = read_json(args.ledger)
        if args.command == "follow":
            value = follow_sources(ledger, read_json(args.sources), args.max_sources, args.max_links)
        else:
            value = review_evidence(ledger, read_json(args.cards) if args.cards else [], args.method, args.limit)
        write_json(args.out, value)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
