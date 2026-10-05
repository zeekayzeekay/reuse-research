# Executable discovery mechanics

Use the bundled Python 3.11+ standard-library script for nontrivial discovery when Python is available. It validates query coverage, executes bounded public GitHub repository searches, merges host web results, preserves indirect leads and records triage. It uses existing `gh` authentication if available, otherwise anonymous public API access; no credentials are printed and no repository code is executed. Host web tools remain necessary for broader terminology and result recall.

## Plan, retrieve, merge

Write a task-specific JSON plan. Critical requirements need targeted capability/ecosystem queries in addition to a whole-purpose query. Include library/SDK/package vocabulary and common domain terms; GitHub search is keyword-based, so short complementary queries are often better than a single sentence containing every requirement. Stack-specific searches supplement purpose queries.

Mark initial ordinary task-keyword queries with `phase: "broad"`; other queries default to `focused`. This origin is retained in query records, candidate hits and generated briefs. Phase does not determine fit or change provider ranking. Start with a few broad IDs from the complete validated plan using `search --query-ids B1 B2`; then run the focused IDs and use enrichment `merge-new` to preserve sources and the whole shortlist. Missing capabilities remain visibly unrun until actually searched. User exclusions apply in both phases.

Vary both product category and behavior vocabulary. Repeating the same category with small wording changes can miss projects that solve the task under a different label. Use a few orthogonal variants for consequential capabilities, and supplement default repository search with a short `in:readme` query: important support details may not appear in the repository name/description. Product/provider terms from the actual requirement can help, but do not require every provider or every capability in every query. Preserve broad purpose searches alongside these targeted variants. When close wrappers appear, follow their source dependencies before concluding a capability is missing.

Split synonyms/category alternatives into different queries; concatenating them requires a narrower keyword match. Search non-AI base engines and acquisition/API libraries too when their behavior is reusable. [GitHub's search scopes](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories) cover only name/description/topics by default, require `in:readme` for README content, and exclude forks unless `fork:true` or `fork:only` is supplied. Use a bounded supplementary fork-inclusive query where fork adaptations matter; keep upstream/fork identities distinct until their differences are checked. A zero-result query is successful transport, not evidence that the required capability has no implementations.

```json
{
  "task": "Current feature",
  "requirements": [{"id": "R1", "description": "Required capability", "critical": true}],
  "queries": [
    {"id": "B1", "text": "domain framework", "family": "whole", "phase": "broad", "requirements": ["R1"], "provider": "github"},
    {"id": "G2", "text": "capability library", "family": "ecosystem", "requirements": ["R1"], "provider": "github"},
    {"id": "W1", "text": "domain capability implementations", "family": "capability", "requirements": ["R1"], "provider": "web"}
  ]
}
```

Use the actual script path relative to this skill, not the consuming project's working directory:

```text
python <skill>/scripts/reuse_search.py validate --plan plan.json
python <skill>/scripts/reuse_search.py search --plan plan.json --out discovery --seconds 120 --per-page 50 --pages 1
```

The search adapter adds `is:public` and records that executed query. Its default is 40 results per page; override this under the source/time budget. It visits the first page of each GitHub query before second pages, uses a deadline and bounded request timeout, and saves each packet plus a ledger. Failures remain visible; unavailable web queries remain unrun. A deadline cannot force a misbehaving operating-system request to finish, and the research/report budget remains the agent's responsibility.

Run each web query through the host's available search tool. Import actual results as a packet, not invented retrieval:

```json
{
  "query_id": "W1",
  "query_text": "domain capability implementations",
  "provider": "web",
  "observed_at": "actual observation time",
  "state": "ok",
  "results": [{"url": "https://github.com/owner/repo", "title": "Actual result title", "description": "Actual result summary"}],
  "raw_text": "Actual returned text, optionally including indirect GitHub source links"
}
```

Use `state: failed` plus an error category for a failed request, with no fabricated results. Batched search results may be saved once per query with explicit batch attribution in the raw text; do not invent query-specific ranking. Return text without a GitHub URL may still be relevant; follow documentation/package links to primary source rather than treating it as a negative result. Add a follow-up query to the plan before importing new evidence under its ID.

For developer/documentation search use `provider: web` and record `channel: developer` in the packet. For a combined batch use the same `vote_group` in all associated packets and `ranked: false` unless the provider returned actual per-query rankings. Duplicate identical queries and pages share one ranking vote by default. Imported paginated packets need `page` and `per_page` for global ranks. Raw-text/indirect links receive no provider-ranking vote. These records describe retrieval, not semantic fit.

```text
python <skill>/scripts/reuse_search.py merge --plan plan.json --packets discovery/packets web-packets.json --out ledger.json
```

The ledger retains every candidate and each query/source association, including `github.com/owner/repo` links returned without a URL scheme. Per-query review cues prevent one whole-feature ranking from erasing specialist matches; they are not fit/health scores. URLs from text have only retrieved-link identity until primary metadata/source verifies them. Search reach does not verify behavior, completeness, compatibility or maintenance.

## Follow underlying components and triage

When a close result is a demo, wrapper or whole application, inspect its manifest/source links before choosing a custom implementation. The helper can extract explicit GitHub links and package leads:

```text
python <skill>/scripts/reuse_search.py leads --file candidate/package.json --out leads.json
```

Supported manifests: package.json, pyproject.toml project dependencies, Cargo.toml package/workspace/target dependencies, and requirements*.txt. Cargo aliases retain the actual package name and scope; workspace inheritance still needs the relevant workspace manifest. Other formats and bare library names in prose need host-tool inspection. Relevant unresolved package names require registry/documentation lookup and source resolution; do not invent a repository or assume every dependency solves the task. Keep newly resolved libraries as candidates even if the wrapper is rejected.

For raw discovery, an optional triage JSON list can record `repo`, `disposition` (`verify`, `study`, `defer`, `exclude`) and an evidence-based `reason`. An excluded candidate stays in the ledger; `pending` never means irrelevant. Final handoff requires individual reasons for queued/high-priority and inspected candidates, with a grouped deferral for the remaining retained pool. `triage_complete` measures this optional per-candidate list, not final handoff readiness. After source import, use enrichment `merge-new` rather than rebuilding the enriched ledger here.

```text
python <skill>/scripts/reuse_search.py merge --plan plan.json --packets discovery/packets web-packets.json --triage triage.json --out ledger.json
```

Prioritize verification per important requirement, not just popularity or provider rank. Return the research report and its source-backed decisions alongside the ledger; a mechanically complete triage file is not sufficient recommendation evidence.

## Captured sources and evidence review (v0.3)

Fetch consequential README/docs, ecosystem lists, manifests or source through host tools. Keep actual returned content in a source JSON list. Each capture needs a unique `id`, actual `url`, `parent_url` from the original search results/candidates, `observed_at`, `kind`, scoped `requirements`, and `text`. Kinds: `readme`, `documentation`, `curated_list`, `manifest`, `code`, `test`, `issue`, `metadata`. Pinned code/test/manifest inspection also needs a full 40-hex commit `revision`. GitHub file, raw.githubusercontent.com and api.github.com/repos URLs establish their own source repository. URLs in captured text create one-hop leads without invented search ranks. Non-GitHub source pages must have been retained as actual search results. A newly followed repository can be inspected at its primary GitHub source URL with its canonical candidate URL as parent; its outgoing links cannot start another discovery hop. Bare package names remain leads for primary-source resolution with host tools.

Discovery requirement mappings are hypotheses. When a source reveals another known task capability, add that requirement with an explicit `association_reason`; do not issue an unnecessary query merely to repair bookkeeping. The later evidence card still needs the actual supporting passage and a justified state. Unknown requirement IDs remain errors; revise the task plan/ledger deliberately for newly added requirements.

Treat the enriched ledger as one evidence record: preserve both `source_captures` and each candidate's `source_leads`. Copying new captures into older candidate objects drops their evidence bindings and causes review to fail even when the source text is present. When preserving a fixed candidate pool, retain the complete corresponding candidate objects from the enriched ledger. For incremental `follow` calls, supply only new captures; source IDs are unique and the source budget counts existing plus new captures. Validate cards before investing in case authoring; a failed binding check is an unfinished evidence handoff, not evidence that the component is unsuitable.

```json
[{"id":"S1","url":"https://docs.example/components","parent_url":"https://docs.example/components",
  "kind":"documentation","observed_at":"actual time","requirements":["R1"],
  "text":"Actual fetched text with https://github.com/owner/component source link"}]
```

```text
python <skill>/scripts/reuse_review.py follow --ledger ledger.json --sources sources.json --out enriched.json --max-sources 12 --max-links 100
python <skill>/scripts/reuse_review.py review --ledger enriched.json --out queue.json --method interleave --limit 20
```

Source limits are explicit: excess source captures fail; excess links follow document order and are bounded and flagged, so a large list may need a justified higher link budget. A primary source's own repository is kept first. Captures retain text and SHA-256 for local replay. The bounded queue supplements per-requirement targeted/followed lanes; it never deletes the remaining ledger. Compare `--method rrf` if useful. RRF uses one best rank per vote group with constant 60, excludes unranked/indirect votes, and cannot recover absent candidates. Neither method applies stack/activity/popularity exclusion gates.

After reading sources, write cards as a JSON list:

```json
[{"id":"E1","repo":"owner/component","requirement":"R1","source_id":"S1",
  "state":"partial","role":"study","method":"documented",
  "excerpt":"Exact passage present in the captured source",
  "claim":"Agent's scoped interpretation","limits":"Decisive unknowns and scope limits"}]
```

Allowed states: `supported`, `partial`, `contradicted`, `unknown`; roles: `dependency`, `adaptation`, `study`; methods: `documented`, `inspected`. Curated-list cards must remain `unknown`: verify fit in primary sources. The source must link explicitly to the candidate or be its own GitHub source. `inspected` requires pinned code/test/manifest capture. Runtime tests and eligibility conclusions belong in the research report; this helper does not certify them.

```text
python <skill>/scripts/reuse_review.py review --ledger enriched.json --cards cards.json --out review.json --method interleave --limit 20
```

The output separates retrieval, queue size, source captures, reviewed evidence and inspected source, plus requirement gaps. `evidence_backed_candidate` means scoped evidence exists, with its stated method and limits; it does not mean adoption is approved or corner cases are covered. Excerpt matching checks provenance, not interpretation. Make one bounded query expansion for a consequential gap using observed terminology, then reconcile decisions and transferred cases in the report. Report the actual global research deadline and any overrun; helper deadlines cover only GitHub requests.

## Qualification audits

For controlled pilots only, keep expected identities separate from discovery inputs and resolve ambiguous names independently. After discovery freezes:

```text
python <skill>/scripts/reuse_search.py audit --ledger ledger.json --expected holdout.json --out recall.json
```

Expected entries use `repo: owner/name` and optional verified aliases. This reports retrieval and triage status without injecting candidates into discovery. Audit named-query contamination separately. A small holdout set is not a comprehensive recall benchmark.

If Python or search access is unavailable, use host tools with equivalent query, coverage, candidate and exclusion records; disclose the fallback. No added subscription/backend is required.
