"""Material v0.5.2 counterexamples and repaired handoff boundaries; offline."""
import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_reuse_review import ledger, source, card
import test_reuse_enrich as enrichment_fixtures
from test_reuse_search import plan
from reuse_review import follow_sources, review_evidence
from reuse_enrich import cache_put, cache_find, digest, benchmark_score, main as enrich_main
from reuse_enrich import make_briefs, rank_briefs, component_leads, mention_hints, reconcile_selection
from reuse_run import render_report, main as run_main, start
from reuse_search import repo_id, write_json, read_json, build_ledger
import trace_retrieval as trace


class MaterialRepairs(unittest.TestCase):
    def fixture(self):
        value, briefs, screened, _, records, _ = enrichment_fixtures.EnrichmentMechanics().selection_fixture()
        value['requirements'] = [{'id':'R1','description':'Recover profile history'},
                                 {'id':'R2','description':'Keep project provenance'}]
        reviewed = review_evidence(value, [card()])
        decisions = {'decisions':[{'requirement':r,'decision':'STUDY','status':'provisional',
            'reason':'Observed merge behavior informs the adapter','next_check':'Run conflict fixtures'} for r in ['R1','R2']]}
        context = {'goal':'Switch agents on an existing project','stack':'Existing Python CLI',
            'constraints':'Preserve history without lossy overwrites',
            'implementation_plan':[{'requirement':'R1','action':'Implement an adapter after studying the merge rule','evidence_ids':['E1']},
                                   {'requirement':'R2','action':'Defer migration until provenance checks pass','evidence_ids':[]}]}
        cases = {'cases':[{'id':'C1','card_id':'E1','excerpt':'supports merging profiles',
            'input_or_trigger':'Conflicting profile histories','observed_behavior':'Profile merging documented',
            'applicability':'Check before switching agents','current_state':'unknown','proposed_check':'Duplicate/conflict fixture'}]}
        return value, briefs, screened, reviewed, records, decisions, context, cases

    def test_mutable_mismatched_and_duplicate_api_refs_cannot_be_inspected(self):
        revision = 'a'*40
        for url in ['https://github.com/b/profiles/blob/main/merge.py',
                    'https://github.com/b/profiles/blob/'+'b'*40+'/merge.py',
                    'https://raw.githubusercontent.com/b/profiles/main/merge.py',
                    'https://api.github.com/repos/b/profiles/contents/merge.py?ref='+revision+'&ref=main']:
            with self.subTest(url=url):
                value = follow_sources(ledger(), [source(kind='code', revision=revision, url=url)])
                with self.assertRaises(ValueError): review_evidence(value, [card(method='inspected')])
                self.assertEqual(review_evidence(value, [card()])['stages']['source_inspected'], 0)

    def test_matching_pins_work_for_all_supported_file_urls(self):
        revision = 'a'*40
        for url in ['https://github.com/b/profiles/blob/'+revision+'/merge.py',
                    'https://raw.githubusercontent.com/b/profiles/'+revision+'/merge.py',
                    'https://api.github.com/repos/b/profiles/contents/merge.py?ref='+revision]:
            with self.subTest(url=url):
                value = follow_sources(ledger(), [source(kind='code', revision=revision, url=url)])
                self.assertEqual(review_evidence(value, [card(method='inspected')])['stages']['source_inspected'], 1)

    def test_changed_capture_is_rejected_before_cache_write(self):
        value = follow_sources(ledger(), [source()])
        value['source_captures'][0]['text'] += ' Handles all conflicts losslessly.'
        reviewed = {'cards':[card(excerpt='Handles all conflicts losslessly.') ]}
        with self.assertRaises(ValueError): review_evidence(value, reviewed['cards'])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): cache_put(directory, value, reviewed)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cache_load_checks_nested_capture_even_with_valid_entry_digest(self):
        value = follow_sources(ledger(), [source()])
        entry = {'task':'profiles','requirements':value['requirements'],'cards':[card()],
                 'sources':value['source_captures'],'cases':[],'recorded_at':'2026-10-05'}
        entry['sources'][0]['text'] += ' Unexpected changes.'
        with tempfile.TemporaryDirectory() as directory:
            write_json(Path(directory)/(digest(entry)+'.json'), entry)
            with self.assertRaises(ValueError): cache_find(directory, 'profiles')

    def test_expansion_cli_keeps_captures_source_only_candidates_and_valid_cards(self):
        value = follow_sources(ledger(), [source()])
        expanded = {'requirements':value['requirements'],'queries':[
            {'id':'A','text':'workspace','provider':'github','family':'whole','requirements':['R1','R2']},
            {'id':'B','text':'profiles library','provider':'web','family':'ecosystem','requirements':['R1']},
            {'id':'C','text':'memory transfer','provider':'web','family':'capability','requirements':['R2']},
            {'id':'X1','text':'profile recovery','provider':'github','family':'capability','requirements':['R1']}]}
        packet = [{'query_id':'X1','query_text':'profile recovery','provider':'github','state':'ok',
                   'results':[{'url':'https://github.com/c/new'}]}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in [('enriched',value),('expanded-plan',expanded),('added',packet)]:
                write_json(root/(name+'.json'),data)
            self.assertEqual(enrich_main(['merge-new','--ledger',str(root/'enriched.json'),
                '--plan',str(root/'expanded-plan.json'),'--packets',str(root/'added.json'),'--out',str(root/'final.json')]),0)
            final = read_json(root/'final.json')
            self.assertEqual({c['repo'] for c in final['candidates']},{'a/app','b/profiles','c/new'})
            self.assertEqual(final['source_captures'],value['source_captures'])
            self.assertEqual(review_evidence(final,[card()])['cards'],[card()])

    def test_report_retains_task_plan_and_case_meaning(self):
        value,briefs,screened,reviewed,records,decisions,context,cases = self.fixture()
        report,audit = render_report(value,briefs,screened,reviewed,records,decisions,context=context,cases=cases)
        self.assertTrue(audit['handoff_complete'])
        for text in ['Recover profile history',context['goal'],context['stack'],context['constraints'],
                     context['implementation_plan'][0]['action'],'2026-10-04','C1 / E1','Check before switching agents']:
            self.assertIn(text,report)
        self.assertEqual(audit['report_sha256'],hashlib.sha256(report.encode()).hexdigest())
        incomplete,gaps = render_report(value,briefs,screened,reviewed,records,decisions)
        self.assertTrue(gaps['accounted']); self.assertFalse(gaps['handoff_complete'])
        self.assertIn('UNFINISHED',incomplete)
        records['candidates'] = []
        report,audit = render_report(value,briefs,screened,reviewed,records,decisions,context=context)
        self.assertFalse(audit['accounted']); self.assertIn('UNFINISHED',report)

    def test_cli_saves_complete_report_and_audit_before_clock_completion(self):
        self.cli_case(False)

    def test_failed_audit_save_cannot_complete_clock(self):
        self.cli_case(True)

    def cli_case(self, fail_save):
        value,briefs,screened,reviewed,records,decisions,context,cases = self.fixture()
        at = dt.datetime(2026,10,5,tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); args=['handoff']
            for name,data in [('ledger',value),('briefs',briefs),('screened',screened),('review',reviewed),
                             ('records',records),('decisions',decisions),('context',context),('cases',cases),('run',start('fixture',60,15,at))]:
                path=root/(name+'.json');write_json(path,data);args+=['--'+name,str(path)]
            audit_path=root/'audit.json'
            if fail_save: audit_path.mkdir()
            args+=['--out',str(root/'report.md'),'--audit-out',str(audit_path)]
            with patch('reuse_run.utc',return_value=at+dt.timedelta(seconds=30)):
                self.assertEqual(run_main(args),2 if fail_save else 0)
            clock=read_json(root/'run.json')
            self.assertEqual(clock['status'],'active' if fail_save else 'complete')
            if not fail_save:
                audit=read_json(audit_path);report=(root/'report.md').read_text(encoding='utf-8')
                self.assertTrue(audit['handoff_complete']); self.assertIn(audit_path.as_posix(),report)
                self.assertEqual(audit['report_sha256'],hashlib.sha256(report.encode()).hexdigest())

    def test_other_hosts_do_not_create_canonical_github_candidates(self):
        self.assertIsNone(repo_id('https://mirror.example/github.com/a/profiles'))
        self.assertIsNone(repo_id('https://evil.example/?url=https://github.com/a/profiles'))
        self.assertEqual(repo_id('https://github.com/a/profiles/blob/main/x.py'),'a/profiles')
        value=build_ledger(plan(),[{'query_id':'Q1','query_text':plan()['queries'][0]['text'],'provider':'github',
            'state':'ok','results':[{'url':'https://mirror.example/github.com/a/profiles'}]}])
        self.assertEqual(value['candidates'],[])

    def test_benchmark_queue_cannot_score_an_out_of_pool_positive(self):
        labels=[{'repo':'b/profiles','source':'https://github.com/b/profiles','reason':'Observed merge support','relevance':'high'}]
        with self.assertRaises(ValueError): benchmark_score(ledger(),['b/profiles'],labels)

    def test_failed_and_unconfirmed_search_logs_keep_unknown_state(self):
        for state, expected in [('failed','unknown_failed_or_unconfirmed_trace'),('recorded','unknown_failed_or_unconfirmed_trace'),('ok','ledger_merge')]:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); run=root/'run'; run.mkdir()
                write_json(run/'final-ledger.json',{'candidates':[]})
                write_json(run/'queries.json',{'logs':[{'queries':['profile library'],'status':state,
                            'result':'https://github.com/a/profiles'}]})
                with patch.object(trace,'ROOT',root):
                    row=trace.audit_run({'id':'fixture','path':'run'},[{'repo':'a/profiles'}])['rows'][0]
                self.assertEqual(bool(row['raw_hits']),state=='ok')
                self.assertEqual(row['first_observed_loss'],expected)

    def test_empty_brief_stays_visible_unknown_and_cannot_be_screened_without_passage(self):
        value=ledger()
        briefs=make_briefs(value)
        self.assertEqual(briefs['briefs'][0]['passages'],[])
        self.assertEqual(briefs['content_gaps'][0]['repo'],'a/app')
        from reuse_run import render_snapshot
        report=render_snapshot(value,briefs)
        self.assertIn('a/app',report); self.assertIn('missing source text',report)
        with self.assertRaises(ValueError):
            rank_briefs(briefs,{'briefs_sha256':briefs['sha256'],'judgments':[{'repo':'a/app','requirement':'R1',
                'adoption':'high','study':'high','passage_id':'invented','reason':'Guess from name'}]})
        value=follow_sources(value,[source(id='PRIMARY',parent_url='https://github.com/a/app',
                url='https://github.com/a/app/blob/main/README.md',kind='readme',text='Actual workspace history documentation')])
        enriched=make_briefs(value)
        self.assertEqual(enriched['content_gaps'],[])
        self.assertIn('Actual workspace history documentation',enriched['briefs'][0]['passages'][0]['text'])

    def test_actual_returned_title_is_retained_as_a_retrieval_passage(self):
        value=ledger();value['candidates'][0]['hits'][0]['title']='Workspace history browser'
        briefs=make_briefs(value)
        self.assertEqual(briefs['content_gaps'],[])
        self.assertEqual(briefs['briefs'][0]['passages'][0]['text'],'Workspace history browser')
        self.assertEqual(briefs['briefs'][0]['passages'][0]['kind'],'retrieved_title')

    def test_critical_upstream_cue_cannot_silently_finish_a_handoff(self):
        value, _, _, reviewed, records, decisions, context, _ = self.fixture()
        value['requirements'][0]['critical'] = True
        value['candidates'][0]['hits'][0]['description'] = 'Downloads content using the ProfileKit library.'
        briefs = make_briefs(value)
        cue = briefs['component_leads'][0]
        self.assertEqual(cue['mention'], 'ProfileKit')
        judgments = [{'repo':b['repo'],'requirement':'R1','adoption':'low','study':'high',
            'passage_id':b['passages'][0]['id'],'reason':'Actual interface worth inspection'} for b in briefs['briefs']]
        screened = rank_briefs(briefs,{'briefs_sha256':briefs['sha256'],'judgments':judgments},1)
        report, audit = render_report(value,briefs,screened,reviewed,records,decisions,context=context)
        self.assertFalse(audit['accounted']); self.assertFalse(audit['handoff_complete'])
        self.assertIn('UNFINISHED',report); self.assertIn(cue['excerpt'],report)
        self.assertIn(cue['source_url'],report)
        self.assertEqual(audit['gaps'][0]['stage'],'component_lead')
        self.assertNotIn('profilekit/profilekit',{c['repo'] for c in value['candidates']})
        for status in ['deferred','dismissed']:
            records['component_leads'] = [{'lead_id':cue['id'],'status':status,
                'reason':'Identity check deferred under the budget; resolve before adoption' if status=='deferred' else 'Ambiguous label; no verified underlying public component'}]
            report, audit = render_report(value,briefs,screened,reviewed,records,decisions,context=context)
            self.assertTrue(audit['handoff_complete'])
            self.assertEqual(len(audit['rows']),2)
        records['component_leads'] = [{'lead_id':cue['id'],'status':'resolved','reason':'Observed primary source link', 'repos':['invented/library']}]
        with self.assertRaises(ValueError): render_report(value,briefs,screened,reviewed,records,decisions,context=context)
        records['component_leads'][0]['repos'] = ['b/profiles']
        report, audit = render_report(value,briefs,screened,reviewed,records,decisions,context=context)
        self.assertTrue(audit['handoff_complete']); self.assertIn('retained identities: b/profiles',report)
        self.assertEqual(reviewed['cards'],[card()])
        records['component_leads'][0]['reason'] = 42
        with self.assertRaises(ValueError): render_report(value,briefs,screened,reviewed,records,decisions,context=context)

    def test_upstream_cue_uses_strongest_literal_evidence_and_stays_bounded(self):
        value=ledger();value['requirements'][0]['critical']=True
        hit=value['candidates'][0]['hits'][0]
        hit['description']='ProfileKit dashboard'
        stronger=copy.deepcopy(hit);stronger['description']='Works using the ProfileKit library.'
        value['candidates'][0]['hits'].append(stronger)
        hints=mention_hints(value)
        cue=next(h for h in hints if h['mention']=='ProfileKit')
        self.assertTrue(cue['relationship_cue']);self.assertEqual(cue['hit_index'],1)
        self.assertIn('using the ProfileKit library',cue['excerpt'])
        many=[{**cue,'mention':'Component'+str(i)} for i in range(8)]
        self.assertEqual(len(component_leads(value,many)),4)
        self.assertEqual(component_leads(value,[{**cue,'requirements':['R2']},{**cue,'relationship_cue':False}]),[])
        from reuse_run import render_snapshot
        snapshot=render_snapshot(value,make_briefs(value))
        self.assertIn(cue['excerpt'],snapshot)

    def test_noncritical_observation_cannot_suppress_critical_component_lead(self):
        value=ledger();value['requirements'][0]['critical']=True
        hit=value['candidates'][0]['hits'][0]
        hit['description']='Downloads content using ProfileKit.';hit['requirements']=['R1']
        stronger=copy.deepcopy(hit);stronger['description']='Metadata using the ProfileKit library.';stronger['requirements']=['R2']
        value['candidates'][0]['hits'].append(stronger)
        cue=make_briefs(value)['component_leads'][0]
        self.assertEqual(cue['requirements'],['R1']);self.assertEqual(cue['hit_index'],0)
        self.assertIn('Downloads content using ProfileKit',cue['excerpt'])

    def component_fixture(self):
        value, _, _, reviewed, records, decisions, context, _ = self.fixture()
        value['requirements'][0]['critical']=True
        value['candidates'][0]['hits'][0]['description']='Downloads content using the ProfileKit library.'
        briefs=make_briefs(value)
        judgments=[{'repo':b['repo'],'requirement':'R1','adoption':'low','study':'high',
            'passage_id':b['passages'][0]['id'],'reason':'Actual interface worth inspection'} for b in briefs['briefs']]
        screened=rank_briefs(briefs,{'briefs_sha256':briefs['sha256'],'judgments':judgments},1)
        records['component_leads']=[{'lead_id':briefs['component_leads'][0]['id'],'status':'deferred',
            'reason':'Identity unresolved in budget; check primary metadata next'}]
        return value,briefs,screened,reviewed,records,decisions,context

    def test_standalone_reconciliation_requires_cue_and_source_visibility(self):
        value,briefs,screened,reviewed,records,decisions,context=self.component_fixture()
        report='\n'.join(b['repo'] for b in briefs['briefs'])
        audit=reconcile_selection(value,briefs,screened,reviewed,records,report)
        self.assertFalse(audit['accounted']);self.assertEqual(audit['gaps'][0]['missing'],['report_visibility'])
        report+='\n'+briefs['component_leads'][0]['mention']
        self.assertFalse(reconcile_selection(value,briefs,screened,reviewed,records,report)['accounted'])
        report+='\n'+briefs['component_leads'][0]['source_url']
        self.assertTrue(reconcile_selection(value,briefs,screened,reviewed,records,report)['accounted'])

    def test_rebound_brief_digest_cannot_hide_invented_component_cue_evidence(self):
        value,briefs,screened,reviewed,records,decisions,context=self.component_fixture()
        cue=briefs['component_leads'][0];cue['excerpt']='Made up evidence using the ProfileKit library.'
        cue['id']=digest([cue[k] for k in ['mention','repo','hit_index','field','excerpt','requirements']])[:20]
        records['component_leads'][0]['lead_id']=cue['id']
        briefs['sha256']=digest({k:v for k,v in briefs.items() if k!='sha256'})
        screened['briefs_sha256']=briefs['sha256']
        with self.assertRaises(ValueError): render_report(value,briefs,screened,reviewed,records,decisions,context=context)
        from reuse_run import render_snapshot
        with self.assertRaises(ValueError): render_snapshot(value,briefs)


if __name__ == '__main__': unittest.main()
