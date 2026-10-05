"""Provenance, specialist retention and evidence-stage checks with synthetic inputs."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/reuse-research/scripts"))
from reuse_search import build_ledger
from reuse_review import follow_sources, review_evidence, review_order


def ledger():
    plan = {"requirements": [{"id": "R1"}, {"id": "R2"}], "queries": [
        {"id": "A", "text": "workspace", "provider": "github", "family": "whole", "requirements": ["R1", "R2"]},
        {"id": "B", "text": "profiles library", "provider": "web", "family": "ecosystem", "requirements": ["R1"]},
        {"id": "C", "text": "memory transfer", "provider": "web", "family": "capability", "requirements": ["R2"]}]}
    packets = [{"query_id": q["id"], "query_text": q["text"], "provider": q["provider"], "state": "ok",
                "results": [{"url": "https://github.com/a/app"}] if q["id"] == "A" else
                           [{"url": "https://docs.example/library"}] if q["id"] == "B" else []}
               for q in plan["queries"]]
    return build_ledger(plan, packets)


def source(**extra):
    return {"id": "S1", "parent_url": "https://docs.example/library", "url": "https://docs.example/library",
            "kind": "documentation", "observed_at": "2026-10-04", "requirements": ["R1"],
            "text": "The library https://github.com/b/profiles supports merging profiles.", **extra}


def card(**extra):
    return {"id": "E1", "repo": "b/profiles", "requirement": "R1", "source_id": "S1",
            "state": "supported", "role": "study", "method": "documented", "excerpt": "supports merging profiles",
            "claim": "Profile merging is documented", "limits": "Cross-stack; integration and edge cases unknown", **extra}


class ReviewMechanics(unittest.TestCase):
    def test_one_hop_adds_underlying_component_without_fabricating_query_rank(self):
        before = ledger()
        value = follow_sources(before, [source()])
        c = next(c for c in value["candidates"] if c["repo"] == "b/profiles")
        self.assertEqual(c["hits"], [])
        self.assertEqual(c["source_leads"][0]["depth"], 1)
        self.assertEqual(c["verification"], "unverified")
        self.assertEqual(len(before["candidates"]), 1)
        with self.assertRaises(ValueError):
            follow_sources(value, [source(id="S2", parent_url="https://github.com/b/profiles")])

    def test_follow_budget_and_unknown_parent_fail_explicitly(self):
        with self.assertRaises(ValueError):
            follow_sources(ledger(), [source()], max_sources=0)
        with self.assertRaises(ValueError):
            follow_sources(ledger(), [source(parent_url="https://unknown.example")])

    def test_new_component_can_be_inspected_without_recursive_discovery(self):
        value = follow_sources(ledger(), [source()])
        value = follow_sources(value, [source(id="S2", parent_url="https://github.com/b/profiles",
                              url="https://github.com/b/profiles/blob/" + "a" * 40 + "/merge.py", kind="code", revision="a" * 40,
                              text="supports merging profiles; imports https://github.com/c/third-hop")])
        self.assertEqual({c["repo"] for c in value["candidates"]}, {"a/app", "b/profiles"})
        report = review_evidence(value, [card(source_id="S2", method="inspected")])
        self.assertEqual(report["stages"]["source_inspected"], 1)

    def test_source_links_keep_cross_stack_partial_lane(self):
        value = follow_sources(ledger(), [source()])
        order = review_order(value, "rrf", 1)
        self.assertEqual(order["specialist_lanes"]["R1"]["followed"], ["b/profiles"])
        self.assertEqual(order["candidate_count"], 2)
        self.assertEqual(order["unqueued_count"], 1)

    def test_repeated_batch_and_pages_do_not_multiply_rank_votes(self):
        value = ledger()
        c = value["candidates"][0]
        c["hits"] = [{"query_id": "A", "family": "whole", "provider_rank": r, "rank": r,
                      "vote_group": "shared-batch", "requirements": ["R1"]} for r in (1, 1, 101)]
        self.assertAlmostEqual(review_order(value, "rrf")["rrf_scores"]["a/app"], 1 / 61)
        self.assertEqual(review_order(value)["specialist_lanes"]["R2"]["targeted"], [])

    def test_indirect_and_unranked_links_never_receive_rrf_votes(self):
        value = ledger()
        c = value["candidates"][0]
        c["hits"][0]["provider_rank"] = None
        self.assertEqual(review_order(value, "rrf")["rrf_scores"]["a/app"], 0)
        self.assertEqual(review_order(value)["review_queue"], ["a/app"])

    def test_page_rank_is_global_and_non_repo_sources_survive(self):
        value = ledger()
        self.assertEqual(value["discovery_sources"][1]["url"], "https://docs.example/library")
        from test_reuse_search import plan, packet
        value = build_ledger(plan(), [packet("Q2", [{"url": "https://github.com/x/deep"}], page=2, per_page=50)])
        self.assertEqual(value["candidates"][0]["hits"][0]["provider_rank"], 51)

    def test_excerpt_provenance_and_pinned_inspection_gate(self):
        value = follow_sources(ledger(), [source()])
        with self.assertRaises(ValueError):
            review_evidence(value, [card(excerpt="invented support")])
        with self.assertRaises(ValueError):
            review_evidence(value, [card(method="inspected")])
        value = follow_sources(ledger(), [source(kind="code", revision="a" * 40,
                              url="https://github.com/b/profiles/blob/" + "a" * 40 + "/merge.py")])
        self.assertEqual(review_evidence(value, [card(method="inspected")])["stages"]["source_inspected"], 1)

    def test_new_capability_association_is_recorded_not_blocked_by_original_query(self):
        with self.assertRaises(ValueError):
            follow_sources(ledger(), [source(requirements=["R1", "R2"])])
        value = follow_sources(ledger(), [source(requirements=["R1", "R2"],
                              association_reason="Source also documents project handoff")])
        c = next(c for c in value["candidates"] if c["repo"] == "b/profiles")
        self.assertEqual(c["requirements"], ["R1", "R2"])
        self.assertEqual(c["source_leads"][0]["association_reason"], "Source also documents project handoff")

    def test_raw_source_identity_and_immutable_revision(self):
        url = "https://raw.githubusercontent.com/b/profiles/" + "a" * 40 + "/merge.py"
        value = follow_sources(ledger(), [source(url=url, kind="code", revision="a" * 40)])
        self.assertEqual(review_evidence(value, [card(method="inspected")])["stages"]["source_inspected"], 1)
        value = follow_sources(ledger(), [source(url=url, kind="code", revision="main")])
        with self.assertRaises(ValueError):
            review_evidence(value, [card(method="inspected")])
        from reuse_review import source_repo
        self.assertIsNone(source_repo("https://evil.example/github.com/b/profiles"))
        self.assertEqual(source_repo("https://api.github.com/repos/b/profiles/contents/merge.py"), "b/profiles")

    def test_bounded_following_preserves_document_order_and_flags_omissions(self):
        value = follow_sources(ledger(), [source(text="Relevant https://github.com/z/specialist then https://github.com/a/general")], max_links=1)
        self.assertIn("z/specialist", {c["repo"] for c in value["candidates"]})
        self.assertNotIn("a/general", {c["repo"] for c in value["candidates"]})
        self.assertTrue(value["source_captures"][0]["links_bounded"])

    def test_curated_list_is_a_lead_not_fit_evidence(self):
        value = follow_sources(ledger(), [source(kind="curated_list")])
        with self.assertRaises(ValueError):
            review_evidence(value, [card()])
        self.assertEqual(review_evidence(value, [card(state="unknown")])["gaps"]["R1"]["state"], "unreviewed_leads")

    def test_query_success_does_not_imply_requirement_evidence_or_adoption(self):
        value = follow_sources(ledger(), [source()])
        report = review_evidence(value, [card()])
        self.assertEqual(report["gaps"]["R1"]["state"], "evidence_backed_candidate")
        self.assertEqual(report["gaps"]["R2"]["state"], "unreviewed_leads")
        self.assertEqual(value["coverage"]["R2"]["behavior_state"], "unverified")
        self.assertTrue(all(c["verification"] == "unverified" for c in value["candidates"]))


if __name__ == "__main__":
    unittest.main()
