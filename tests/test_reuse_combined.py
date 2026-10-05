"""Protected whole solutions and broad/focused discovery; synthetic, no network."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'skills/reuse-research/scripts'))
from reuse_search import build_ledger, validate_plan, write_json, read_json
from reuse_review import follow_sources, review_evidence
from reuse_enrich import protect_whole_solutions, make_briefs, rank_briefs, merge_discovery
from reuse_enrich import reconcile_selection, digest, main as enrich_main
from reuse_run import render_report, render_snapshot


class CombinedResearch(unittest.TestCase):
    def fixture(self):
        plan = {'task': 'Production workspace with durable generation', 'requirements': [
            {'id': 'R1', 'description': 'Shared production application'},
            {'id': 'R2', 'description': 'Durable provider jobs'}], 'queries': [
            {'id': 'B1', 'text': 'production studio', 'family': 'whole', 'phase': 'broad',
             'provider': 'github', 'requirements': ['R1', 'R2']},
            {'id': 'G1', 'text': 'durable job library', 'family': 'ecosystem',
             'provider': 'github', 'requirements': ['R1', 'R2']}]}
        packets = [{'query_id': q['id'], 'query_text': q['text'], 'provider': q['provider'],
            'state': 'ok', 'results': [{'url': 'https://github.com/acme/' + r,
                'description': 'Production interface' if q['id'] == 'B1' else 'Durable jobs'}
                for r in (['studio', 'alternative'] if q['id'] == 'B1' else ['jobs'])]}
            for q in plan['queries']]
        value = build_ledger(plan, packets)
        sources = [{'id': r, 'parent_url': 'https://github.com/acme/' + r,
            'url': 'https://github.com/acme/' + r + '/blob/' + 'a' * 40 + '/README.md',
            'kind': 'readme', 'observed_at': '2026-10-05T00:00:00Z', 'requirements': ['R1', 'R2'],
            'text': 'Shared scenes, assets and generation jobs.'} for r in ['studio', 'alternative']]
        value = follow_sources(value, sources)
        requests = [{'repo': 'acme/' + r, 'source_id': r, 'requirements': ['R1', 'R2'],
            'excerpt': 'Shared scenes, assets and generation jobs.',
            'reason': 'Whole production workspace worth comparing before assembling components'}
            for r in ['studio', 'alternative']]
        value = protect_whole_solutions(value, requests)
        briefs = make_briefs(value)
        judgments = {'briefs_sha256': briefs['sha256'], 'judgments': [
            {'repo': 'acme/jobs', 'requirement': 'R2', 'passage_id': next(b for b in briefs['briefs']
                if b['repo'] == 'acme/jobs')['passages'][0]['id'], 'adoption': 'high', 'study': 'high',
             'reason': 'Important complementary execution component'}]}
        screened = rank_briefs(briefs, judgments, 1)
        reviewed = review_evidence(value, [{'id': 'E1', 'repo': 'acme/studio', 'requirement': 'R1',
            'source_id': 'studio', 'state': 'partial', 'role': 'adaptation', 'method': 'documented',
            'excerpt': requests[0]['excerpt'], 'claim': 'Documents a whole workspace', 'limits': 'Untested'}])
        records = {'candidates': [{'repo': c['repo'], 'reason': 'Defer implementation inspection pending target stack',
            'next_check': 'Compare revision and job persistence in the target deployment'} for c in value['candidates']],
            'whole_purpose': {'repo': 'acme/studio', 'card_id': 'E1', 'reason': 'Documented complete-workspace alternative'}}
        return plan, value, requests, briefs, screened, reviewed, records

    def test_origins_and_protected_sources_survive_expansion_and_reranking(self):
        plan, value, requests, briefs, screened, reviewed, records = self.fixture()
        expanded = copy.deepcopy(plan)
        expanded['queries'].append({'id': 'X1', 'text': 'render queue', 'family': 'capability',
            'provider': 'github', 'requirements': ['R2']})
        merged = merge_discovery(value, expanded, [{'query_id': 'X1', 'query_text': 'render queue',
            'provider': 'github', 'state': 'ok', 'results': [{'url': 'https://github.com/acme/render'}]}])
        self.assertEqual(merged['whole_shortlist'], value['whole_shortlist'])
        studio = next(c for c in merged['candidates'] if c['repo'] == 'acme/studio')
        self.assertEqual(studio['hits'][0]['phase'], 'broad')
        self.assertEqual(merged['query_records'][0]['phase'], 'broad')
        new = make_briefs(merged, limit=3)
        self.assertEqual([b['repo'] for b in new['briefs']][:2], ['acme/studio', 'acme/alternative'])
        jobs_passage = next(b for b in new['briefs'] if b['repo'] == 'acme/jobs')['passages'][0]['id']
        ranked = rank_briefs(new, {'briefs_sha256': new['sha256'], 'judgments': [
            {'repo': 'acme/jobs', 'requirement': 'R2', 'passage_id': jobs_passage, 'adoption': 'high',
             'study': 'high', 'reason': 'Complementary component'}]}, 3)
        self.assertEqual(ranked['review_queue'], ['acme/studio', 'acme/jobs', 'acme/alternative'])
        self.assertEqual(protect_whole_solutions(merged, requests), merged)

    def test_protected_lead_outside_queue_requires_named_visible_disposition(self):
        _, value, _, briefs, screened, reviewed, records = self.fixture()
        self.assertNotIn('acme/alternative', screened['review_queue'])
        report = '\n'.join([r['repo'] + ' ' + r['reason'] + ' ' + r['next_check'] for r in records['candidates']]
                           + [e['source_url'] for e in value['whole_shortlist']])
        audit = reconcile_selection(value, briefs, screened, reviewed, records, report)
        self.assertTrue(audit['accounted'])
        self.assertEqual(len(audit['whole_shortlist']), 2)
        records['candidates'] = [r for r in records['candidates'] if r['repo'] != 'acme/alternative']
        audit = reconcile_selection(value, briefs, screened, reviewed, records, report)
        self.assertFalse(audit['accounted'])
        self.assertTrue(any(g.get('repo') == 'acme/alternative' for g in audit['gaps']))

    def test_standalone_reconcile_detects_hidden_followup_and_primary_source(self):
        _, value, _, briefs, screened, reviewed, records = self.fixture()
        report = '\n'.join(r['repo'] + ' ' + r['reason'] for r in records['candidates'])
        audit = reconcile_selection(value, briefs, screened, reviewed, records, report)
        self.assertFalse(audit['accounted'])
        gaps = [g for g in audit['gaps'] if g.get('stage') == 'whole_shortlist']
        self.assertTrue(all('next_check_visibility' in g['missing'] and
            'primary_source_visibility' in g['missing'] for g in gaps))

    def test_missing_or_rebased_shortlist_cannot_evade_accounting(self):
        _, value, _, briefs, screened, reviewed, records = self.fixture()
        with self.assertRaises(ValueError): make_briefs(value, limit=1)
        forged = copy.deepcopy(briefs)
        forged['whole_shortlist'] = []
        forged['sha256'] = digest({k: v for k, v in forged.items() if k != 'sha256'})
        judgments = {'briefs_sha256': forged['sha256'], 'judgments': []}
        with self.assertRaises(ValueError):
            reconcile_selection(value, forged, rank_briefs(forged, judgments), reviewed, records, '')

    def test_shortlist_rejects_other_projects_lists_and_invented_passages(self):
        _, value, requests, _, _, _, _ = self.fixture()
        base = copy.deepcopy(value)
        base.pop('whole_shortlist')
        for change in [{'repo': 'acme/jobs'}, {'excerpt': 'Handles every failure'},
                       {'requirements': ['invented']}, {'source_id': 'missing'}]:
            bad = [{**requests[0], **change}]
            with self.subTest(change=change), self.assertRaises(ValueError):
                protect_whole_solutions(base, bad)
        bad = copy.deepcopy(base)
        bad['source_captures'][0]['kind'] = 'curated_list'
        with self.assertRaises(ValueError): protect_whole_solutions(bad, requests[:1])
        bad = copy.deepcopy(base)
        bad['source_captures'][0]['text'] += ' Modified capture.'
        with self.assertRaises(ValueError): protect_whole_solutions(bad, requests[:1])
        with self.assertRaises(ValueError): protect_whole_solutions(value, [], limit=1)

    def test_snapshot_and_handoff_keep_whole_choices_and_untested_limits(self):
        _, value, _, briefs, screened, reviewed, records = self.fixture()
        snapshot = render_snapshot(value)
        self.assertIn('acme/alternative', snapshot)
        self.assertIn('Assessment pending', snapshot)
        decisions = {'decisions': [{'requirement': r['id'], 'decision': 'DEFER', 'status': 'provisional',
            'reason': 'Target constraints unknown', 'next_check': 'Select deployment'} for r in value['requirements']]}
        context = {'goal': value['task'], 'stack': 'Unknown', 'constraints': 'No execution',
            'implementation_plan': [{'requirement': r['id'], 'action': 'Compare whole bases before adding specialist components',
                'evidence_ids': []} for r in value['requirements']]}
        report, audit = render_report(value, briefs, screened, reviewed, records, decisions, context=context)
        self.assertTrue(audit['handoff_complete'])
        self.assertIn('Whole solutions to compare', report)
        self.assertIn('behavior and eligibility remain unverified', report)
        self.assertTrue(all(r['next_check_visible'] for r in audit['whole_shortlist']))
        records['candidates'][0].pop('next_check')
        _, audit = render_report(value, briefs, screened, reviewed, records, decisions, context=context)
        self.assertFalse(audit['handoff_complete'])

    def test_shortlist_cli_persists_bindings_and_phase_validation_is_explicit(self):
        plan, value, requests, _, _, _, _ = self.fixture()
        base = copy.deepcopy(value)
        base.pop('whole_shortlist')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / 'ledger.json', base)
            write_json(root / 'requests.json', requests)
            self.assertEqual(enrich_main(['shortlist', '--ledger', str(root / 'ledger.json'),
                '--requests', str(root / 'requests.json'), '--out', str(root / 'out.json')]), 0)
            self.assertEqual(read_json(root / 'out.json')['whole_shortlist'], value['whole_shortlist'])
        plan['queries'][0]['phase'] = 'invented'
        self.assertTrue(any('phase' in e for e in validate_plan(plan)))


if __name__ == '__main__': unittest.main()
