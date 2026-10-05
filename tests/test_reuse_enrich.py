"""Screening and transfer invariants; synthetic data, no live network."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/reuse-research/scripts"))
from reuse_enrich import (make_briefs, rank_briefs, expand_plan, case_inventory, cache_put, cache_find,
                          benchmark_score, resolve_relations, reconcile_selection, main)
from reuse_search import read_json
from reuse_review import follow_sources, review_evidence
from test_reuse_review import ledger, source, card
from test_reuse_search import plan


class EnrichmentMechanics(unittest.TestCase):
    def selection_fixture(self):
        original = ledger()
        original['candidates'][0]['hits'][0]['description'] = 'Common configuration interface'
        value = follow_sources(original, [source()])
        briefs = make_briefs(value)
        judgments = {'briefs_sha256': briefs['sha256'], 'judgments': [
            {'repo': b['repo'], 'requirement': 'R1', 'adoption': 'low', 'study': 'high',
             'passage_id': b['passages'][0]['id'], 'reason': 'Matching behavior worth source study'}
            for b in briefs['briefs']]}
        screened = rank_briefs(briefs, judgments, 1)
        records = {'candidates': [{'repo': b['repo'], 'reason': 'Source depth reserved for an existing base; retained for later comparison'}
                                 for b in briefs['briefs']],
                   'whole_purpose': {'deferred_reason': 'No plausible complete-base documentation reviewed in this bounded fixture'}}
        report = '\n'.join('https://github.com/' + b['repo'] for b in briefs['briefs'])
        return value, briefs, screened, {'cards': []}, records, report

    def test_reconcile_catches_high_study_lead_outside_review_queue(self):
        value, briefs, screened, review, records, _ = self.selection_fixture()
        report = 'https://github.com/' + screened['review_queue'][0]
        audit = reconcile_selection(value, briefs, screened, review, records, report)
        self.assertFalse(audit['accounted'])
        self.assertEqual(audit['required_count'], 2)
        self.assertEqual(len(audit['gaps']), 1)
        self.assertEqual(audit['gaps'][0]['missing'], ['report_visibility'])

    def test_reconcile_visibility_and_reason_keep_uninspected_unknown(self):
        audit = reconcile_selection(*self.selection_fixture())
        self.assertTrue(audit['accounted'])
        self.assertEqual(audit['whole_purpose_state'], 'unknown')
        self.assertTrue(all(r['source_inspection_missing'] and not r['methods'] for r in audit['rows']))

    def test_reconcile_requires_reason_even_for_visible_lead(self):
        args = list(self.selection_fixture())
        args[4]['candidates'] = []
        audit = reconcile_selection(*args)
        self.assertEqual(len(audit['gaps']), 2)
        self.assertTrue(all(g['missing'] == ['reason'] for g in audit['gaps']))

    def test_reconcile_rejects_invented_queue_or_mutated_briefs(self):
        args = list(self.selection_fixture())
        args[2]['review_queue'] = ['invented/repo']
        with self.assertRaises(ValueError):
            reconcile_selection(*args)
        args = list(self.selection_fixture())
        args[1]['task'] = 'changed'
        with self.assertRaises(ValueError):
            reconcile_selection(*args)

    def test_reconcile_whole_base_requires_primary_documentation(self):
        value, briefs, screened, _, records, report = self.selection_fixture()
        reviewed = review_evidence(value, [card()])
        records['whole_purpose'] = {'repo': 'b/profiles', 'card_id': 'E1', 'reason': 'Plausible complete base'}
        with self.assertRaises(ValueError):
            reconcile_selection(value, briefs, screened, reviewed, records, report)
        primary = source(id='S2', parent_url='https://github.com/b/profiles',
                         url='https://github.com/b/profiles/blob/main/README.md', kind='readme')
        value = follow_sources(value, [primary])
        reviewed = review_evidence(value, [card(source_id='S2')])
        audit = reconcile_selection(value, briefs, screened, reviewed, records, report)
        self.assertEqual(audit['whole_purpose_state'], 'primary_documentation_reviewed')

    def test_reconcile_strict_cli_retains_gaps_before_failure_exit(self):
        import json
        value, briefs, screened, review, records, _ = self.selection_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = ['reconcile', '--strict']
            for option, data in [('ledger', value), ('briefs', briefs), ('screened', screened), ('review', review), ('records', records)]:
                path = root / (option + '.json')
                path.write_text(json.dumps(data), encoding='utf-8')
                args += ['--' + option, str(path)]
            (root / 'report.md').write_text('An incomplete handoff.', encoding='utf-8')
            args += ['--report', str(root / 'report.md'), '--out', str(root / 'audit.json')]
            self.assertEqual(main(args), 1)
            self.assertFalse(read_json(root / 'audit.json')['accounted'])

    def test_equal_semantic_priority_retains_balanced_brief_order(self):
        original = ledger()
        original["candidates"][0]["hits"][0]["description"] = "Shared profile interface"
        value = follow_sources(original, [source()])
        briefs = make_briefs(value)
        rows = {"briefs_sha256": briefs["sha256"], "judgments": [
            {"repo": b["repo"], "requirement": "R1", "adoption": "low", "study": "high",
             "passage_id": b["passages"][0]["id"], "reason": "Matching interface study"}
            for b in briefs["briefs"]]}
        ranked = rank_briefs(briefs, rows)
        self.assertEqual(ranked["review_queue"], [b["repo"] for b in briefs["briefs"]])

    def test_link_brief_does_not_borrow_neighboring_project_claim(self):
        value = follow_sources(ledger(), [source(kind="curated_list", text=(
            '- https://github.com/b/profiles merges profiles.\n'
            '- https://github.com/c/other migrates every transcript.'))])
        b = next(b for b in make_briefs(value)["briefs"] if b["repo"] == "b/profiles")
        self.assertIn("merges profiles", b["passages"][0]["text"])
        self.assertNotIn("migrates", b["passages"][0]["text"])

    def test_bounded_briefs_balance_ranked_and_document_order_source_leads(self):
        text = '\n'.join('https://github.com/z/item' + str(i) + ' source lead' for i in range(12))
        value = follow_sources(ledger(), [source(kind="curated_list", text=text)])
        queue = [b["repo"] for b in make_briefs(value, 6)["briefs"]]
        self.assertIn("a/app", queue)
        self.assertLess(queue.index("z/item2"), queue.index("z/item3") if "z/item3" in queue else 6)
        self.assertNotIn("z/item10", queue)
        briefed = make_briefs(value, 6)
        for baseline in briefed["eligible_baselines"].values():
            self.assertEqual(set(baseline["review_queue"]), set(queue))

    def test_shared_line_multiple_projects_supplies_link_without_unscoped_claim(self):
        value = follow_sources(ledger(), [source(kind="curated_list", text=(
            'https://github.com/b/profiles and https://github.com/c/other have different features'))])
        b = next(b for b in make_briefs(value)["briefs"] if b["repo"] == "b/profiles")
        self.assertEqual(b["passages"][0]["text"], "https://github.com/b/profiles")

    def test_briefs_preserve_source_link_context_and_omit_no_ledger_data(self):
        value = follow_sources(ledger(), [source(kind="curated_list")])
        before = copy.deepcopy(value)
        briefs = make_briefs(value, 1)
        self.assertEqual(value, before)
        self.assertEqual(briefs["unbriefed_count"], 1)
        self.assertEqual(briefs["briefs"][0]["repo"], "b/profiles")
        self.assertIn("merging profiles", briefs["briefs"][0]["passages"][0]["text"])

    def test_semantic_judgment_keeps_cross_stack_study_when_adoption_is_low(self):
        value = follow_sources(ledger(), [source()])
        briefs = make_briefs(value)
        b = next(b for b in briefs["briefs"] if b["repo"] == "b/profiles")
        rows = {"briefs_sha256": briefs["sha256"], "judgments": [{"repo": "b/profiles", "requirement": "R1",
                "adoption": "low", "study": "high", "passage_id": b["passages"][0]["id"],
                "reason": "Different runtime but matching merge behavior"}]}
        ranked = rank_briefs(briefs, rows, 1)
        self.assertEqual(ranked["review_queue"], ["b/profiles"])
        self.assertEqual(ranked["lanes"]["R1"]["adoption"], [])
        self.assertEqual(ranked["lanes"]["R1"]["study"], ["b/profiles"])
        rows["judgments"][0]["passage_id"] = "invented"
        with self.assertRaises(ValueError):
            rank_briefs(briefs, rows)

    def test_mutated_brief_packet_cannot_receive_original_judgments(self):
        briefs = make_briefs(ledger())
        judgments = {"briefs_sha256": briefs["sha256"], "judgments": []}
        briefs["task"] = "altered"
        with self.assertRaises(ValueError):
            rank_briefs(briefs, judgments)

    def test_bounded_expansion_records_gap_basis_and_rejects_repeat(self):
        request = {"requirement": "R2", "text": "native session migration", "provider": "web",
                   "gap_reason": "No inspected migration candidate", "basis": "task", "basis_text": "synthetic app"}
        review = {"gaps": {"R2": {"state": "unreviewed_leads"}}}
        expanded = expand_plan(plan(), review, [request])
        self.assertEqual(expanded["queries"][-1]["prior_gap_state"], "unreviewed_leads")
        with self.assertRaises(ValueError):
            expand_plan(expanded, review, [request])
        request["basis"] = "observed_source"
        request["source_url"] = "https://not-observed.example"
        with self.assertRaises(ValueError):
            expand_plan(plan(), review, [request], ledger=ledger())

    def test_case_transfer_requires_actual_source_and_project_evidence_for_missing_claim(self):
        value = follow_sources(ledger(), [source()])
        review = review_evidence(value, [card()])
        case = {"id": "C1", "card_id": "E1", "excerpt": "supports merging profiles",
                "input_or_trigger": "two profiles", "observed_behavior": "merging", "current_state": "unknown",
                "applicability": "shared settings", "proposed_check": "conflict fixture"}
        self.assertEqual(len(case_inventory(value, review, [case])["cases"]), 1)
        case["current_state"] = "missing"
        with self.assertRaises(ValueError):
            case_inventory(value, review, [case])
        case["current_state"] = "unknown"
        review["cards"][0]["excerpt"] = "fabricated evidence"
        with self.assertRaises(ValueError):
            case_inventory(value, review, [case])

    def test_cache_remains_historical_and_refreshes_changed_revisions(self):
        value = follow_sources(ledger(), [source(url="https://github.com/b/profiles/blob/" + "a"*40 + "/merge.py",
                                                revision="a"*40, kind="code")])
        review = review_evidence(value, [card(method="inspected")])
        with tempfile.TemporaryDirectory() as root:
            result = cache_put(root, value, review)
            found = cache_find(root, "profiles", {"b/profiles": "b"*40})
            self.assertTrue(found["matches"][0]["refresh_required"])
            self.assertTrue(found["matches"][0]["adoption_health_refresh_required"])
            path = Path(root) / (result["entry"] + ".json")
            path.write_text(path.read_text().replace('Profile merging', 'Invented behavior'), encoding="utf-8")
            with self.assertRaises(ValueError):
                cache_find(root, "profiles")

    def test_unjudged_benchmark_items_are_not_false_negatives(self):
        judgments = [{"repo": "a/app", "relevance": "high", "source": "https://github.com/a/app", "reason": "Relevant"}]
        value = follow_sources(ledger(), [source(text='https://github.com/unjudged/alternative')])
        result = benchmark_score(value, ["a/app", "unjudged/alternative"], judgments)
        self.assertEqual(result["judged_precision"], 1)
        self.assertEqual(result["unjudged_queue_count"], 1)

    def test_dependency_resolution_retains_primary_chain_without_inventing_repo(self):
        value = follow_sources(ledger(), [source(kind="manifest", text='{"dependencies":{"profile-sdk":"1"}}')])
        record = {"source_id": "S1", "package": "profile-sdk", "registry_url": "https://registry.example/profile-sdk",
                  "registry_text": '{"repository":"https://github.com/old/profiles"}', "repo_url": "https://github.com/old/profiles",
                  "github_metadata": {"full_name": "b/profiles", "html_url": "https://github.com/b/profiles"},
                  "redirect_from": "old/profiles", "observed_at": "2026-10-04", "reason": "Merging component"}
        resolved = resolve_relations(value, [record])
        c = next(c for c in resolved["candidates"] if c["repo"] == "b/profiles")
        self.assertEqual(c["hits"], [])
        self.assertEqual(c["source_leads"][0]["requested_repo"], "old/profiles")
        record["repo_url"] = "https://github.com/invented/name"
        with self.assertRaises(ValueError):
            resolve_relations(value, [record])
        record["repo_url"] = "https://github.com/old/profiles"
        record["github_metadata"]["html_url"] = "https://example.com/github.com/b/profiles"
        with self.assertRaises(ValueError):
            resolve_relations(value, [record])


if __name__ == "__main__":
    unittest.main()
