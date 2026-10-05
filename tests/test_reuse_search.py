"""Behavioral checks for discovery mechanics, without live search or candidate execution."""

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills/reuse-research/scripts/reuse_search.py"
SPEC = importlib.util.spec_from_file_location("reuse_search", SCRIPT)
SEARCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SEARCH)


def plan():
    return {"task": "synthetic app", "requirements": [{"id": "R1"}, {"id": "R2"}], "queries": [
        {"id": "Q1", "text": "application workspace", "family": "whole", "requirements": ["R1", "R2"], "provider": "github"},
        {"id": "Q2", "text": "shared profiles library", "family": "ecosystem", "requirements": ["R1"], "provider": "github"},
        {"id": "Q3", "text": "handoff memory", "family": "capability", "requirements": ["R2"], "provider": "web"}]}


def packet(qid, results=None, **extra):
    query = next(q for q in plan()["queries"] if q["id"] == qid)
    return {"query_id": qid, "query_text": query["text"], "provider": query["provider"], "state": "ok", "results": results or [], **extra}


class DiscoveryMechanics(unittest.TestCase):
    def test_expansion_subset_retains_complete_plan_without_rerunning_initial_queries(self):
        calls = []
        def transport(text, page, per_page, timeout):
            calls.append(text)
            return {"items": [], "total_count": 0}
        with tempfile.TemporaryDirectory() as root:
            value = SEARCH.run_search(plan(), root, transport=transport, query_ids=["Q2"])
            self.assertEqual(calls, ["shared profiles library is:public"])
            self.assertEqual([q["query_id"] for q in value["query_records"]], ["Q2"])
            self.assertEqual(set(value["unrun_queries"]), {"Q1", "Q3"})
            with self.assertRaises(ValueError):
                SEARCH.run_search(plan(), root, transport=transport, query_ids=["invented"])

    def test_scheme_less_source_link_is_retained_without_false_domain(self):
        value = SEARCH.build_ledger(plan(), [packet("Q3", raw_text="source github.com/acme/memory-sdk; ignore fakegithub.com/spam/repo")])
        self.assertEqual([c["repo"] for c in value["candidates"]], ["acme/memory-sdk"])
        self.assertEqual(value["candidates"][0]["identity_state"], "retrieved_link")

    def test_cargo_alias_workspace_and_target_leads_keep_package_identity(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / "Cargo.toml"
            manifest.write_text('[dependencies]\nbridge = { package = "protocol-sdk", version = "2" }\n[workspace.dependencies]\nshared = "1"\n[target.windows.dependencies]\nwin-helper = { git = "https://github.com/acme/win-helper" }\n', encoding="utf-8")
            value = SEARCH.extract_leads(manifest)
            self.assertEqual(value["repos"], ["acme/win-helper"])
            self.assertEqual([p["name"] for p in value["packages"]], ["protocol-sdk", "shared", "win-helper"])
            self.assertEqual(value["packages"][0]["alias"], "bridge")
            self.assertEqual(value["packages"][1]["scope"], "workspace")
            self.assertEqual(value["packages"][2]["scope"], "target:windows")

    def test_whole_match_does_not_replace_critical_subtask_search(self):
        value = plan()
        value["queries"].pop()
        self.assertIn("R2: critical capability has no targeted search", SEARCH.validate_plan(value))

    def test_query_id_cannot_escape_output_directory(self):
        value = plan()
        value["queries"][0]["id"] = "../outside"
        with self.assertRaises(ValueError):
            SEARCH.check_plan(value)

    def test_merge_preserves_complementary_and_archived_study_repos(self):
        packets = [packet("Q1", [{"url": "https://github.com/Org/App", "full_name": "Org/App"}]),
                   packet("Q2", [{"url": "https://github.com/Other/Profiles", "full_name": "Other/Profiles", "archived": True}]),
                   packet("Q3", [{"url": "https://github.com/org/app/blob/main/context.md"}],
                          raw_text="Implementation uses https://github.com/Small/Memory.git; see https://github.com/topics/agents")]
        value = SEARCH.build_ledger(plan(), packets)
        repos = {c["repo"]: c for c in value["candidates"]}
        self.assertEqual(set(repos), {"org/app", "other/profiles", "small/memory"})
        self.assertEqual(repos["org/app"]["requirements"], ["R1", "R2"])
        self.assertEqual(len(repos["org/app"]["hits"]), 2)
        self.assertEqual(repos["other/profiles"]["verification"], "unverified")
        self.assertTrue(repos["small/memory"]["hits"][0]["indirect"])
        self.assertFalse(value["triage_complete"])

    def test_failure_and_missing_web_route_remain_unknown(self):
        value = SEARCH.build_ledger(plan(), [packet("Q1"), packet("Q2", state="failed", error="rate_limited")])
        self.assertEqual(value["coverage"]["R1"]["discovery_state"], "unknown")
        self.assertEqual(value["coverage"]["R2"]["discovery_state"], "unknown")
        self.assertEqual(value["unrun_queries"], ["Q3"])
        self.assertEqual(value["candidates"], [])

    def test_mismatched_packet_cannot_contaminate_plan(self):
        bad = packet("Q2", query_text="unlogged named query")
        with self.assertRaises(ValueError):
            SEARCH.build_ledger(plan(), [bad])
        with self.assertRaises(ValueError):
            SEARCH.build_ledger(plan(), [packet("Q2", [{"url": "https://github.com/a/b"}], state="failed")])

    def test_every_exclusion_requires_a_reason_and_identity(self):
        packets = [packet("Q2", [{"url": "https://github.com/a/b"}])]
        with self.assertRaises(ValueError):
            SEARCH.build_ledger(plan(), packets, [{"repo": "a/b", "disposition": "exclude"}])
        value = SEARCH.build_ledger(plan(), packets, [{"repo": "a/b", "disposition": "study", "reason": "Useful partial capability"}])
        self.assertTrue(value["triage_complete"])
        self.assertEqual(len(value["candidates"]), 1)

    def test_pagination_covers_queries_before_more_pages_and_stops_at_deadline(self):
        value = plan()
        value["queries"][2]["provider"] = "github"
        ticks = [0]
        calls = []
        def transport(text, page, count, timeout):
            calls.append((text, page))
            ticks[0] += 2
            return {"items": [], "total_count": 99, "incomplete_results": True}
        with tempfile.TemporaryDirectory() as root:
            ledger = SEARCH.run_search(value, root, seconds=5, pages=2, transport=transport, clock=lambda: ticks[0])
            self.assertEqual([p for _, p in calls], [1, 1, 1])
            self.assertEqual([r["state"] for r in ledger["query_records"]], ["ok"] * 3 + ["not_run"] * 3)
            self.assertTrue(all(r["incomplete_results"] for r in ledger["query_records"][:3]))
            self.assertEqual(len(list((Path(root) / "packets").glob("*.json"))), 6)

    def test_dependency_leads_do_not_invent_repository_identity(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "pyproject.toml"
            source.write_text('[project]\ndependencies = ["source-parser>=1", "gallery-sdk"]\n', encoding="utf-8")
            leads = SEARCH.extract_leads(source)
            self.assertEqual(leads["repos"], [])
            self.assertEqual([p["name"] for p in leads["packages"]], ["source-parser>=1", "gallery-sdk"])
            self.assertEqual(leads["status"], "unverified_leads")

    def test_holdout_audit_never_injects_named_candidates(self):
        ledger = SEARCH.build_ledger(plan(), [packet("Q2", [{"url": "https://github.com/a/b"}])])
        before = copy.deepcopy(ledger)
        result = SEARCH.audit(ledger, [{"repo": "a/b"}, {"repo": "missing/target"}])
        self.assertEqual(result["retrieved_count"], 1)
        self.assertEqual(ledger, before)


if __name__ == "__main__":
    unittest.main()
