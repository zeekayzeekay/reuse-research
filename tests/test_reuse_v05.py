"""Observed retrieval-loss and clock/handoff regressions; no candidate execution."""
import copy
import datetime as dt
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]/"skills/reuse-research/scripts"))
from reuse_enrich import make_briefs, mention_hints, recover_mentions, merge_discovery, rank_briefs
from reuse_run import start, status, allowance, render_report, render_snapshot, main
from reuse_search import check_plan, build_ledger, read_json, write_json, main as search_main
from reuse_review import follow_sources, review_evidence
from test_reuse_review import ledger, source, card
from test_reuse_search import plan


class Recovery(unittest.TestCase):
    def request(self):
        return {"source_id":"S1", "mention":"ProfileKit", "excerpt":"ProfileKit helps merge profiles",
                "requirements":["R1"], "reason":"Resolve a component actually mentioned in captured documentation"}

    def test_unseen_mention_never_becomes_a_repository_without_metadata(self):
        value=follow_sources(ledger(),[source(text='ProfileKit helps merge profiles')])
        before=copy.deepcopy(value)
        result=recover_mentions(plan(),value,[self.request()])
        self.assertEqual(value,before)
        self.assertEqual(result['queries'][-1]['text'],'"ProfileKit" in:name,description')
        self.assertEqual(len(value['candidates']),1)
        with self.assertRaises(ValueError):
            recover_mentions(result,value,[self.request()])

    def test_unknown_name_and_borrowed_requirement_rejected(self):
        value=follow_sources(ledger(),[source(text='ProfileKit helps merge profiles')])
        req=self.request()
        req['mention']='MadeUpLibrary'
        with self.assertRaises(ValueError): recover_mentions(plan(),value,[req])
        req=self.request(); req['requirements']=['R2']
        with self.assertRaises(ValueError): recover_mentions(plan(),value,[req])

    def test_hit_description_can_supply_a_literal_but_not_an_invented_excerpt(self):
        value=ledger(); value['candidates'][0]['hits'][0]['description']='Uses ProfileKit for merging'
        req={'repo':'a/app','hit_index':0,'mention':'ProfileKit','excerpt':'Uses ProfileKit for merging',
             'requirements':['R1'],'reason':'Follow documented underlying component'}
        self.assertEqual(recover_mentions(plan(),value,[req])['recovery_queries'],['M1'])
        req['excerpt']='ProfileKit is production ready'
        with self.assertRaises(ValueError): recover_mentions(plan(),value,[req])

    def test_excluded_phrase_blocked_before_search_in_both_spellings(self):
        value=plan(); value['excluded_discovery_terms']=['agent-native']
        for text in ['agent native framework','agent-native framework']:
            value['queries'][0]['text']=text
            with self.assertRaises(ValueError): check_plan(value)
        value['queries'][0]['text']='agent interface application framework'
        check_plan(value)

    def test_merge_new_retrieval_retains_exact_enriched_bindings_and_prior_cards(self):
        value=follow_sources(ledger(),[source()]); value['task']=plan()['task']
        before=copy.deepcopy(value)
        packet={'query_id':'Q2','query_text':'shared profiles library','provider':'github','state':'ok',
                'results':[{'url':'https://github.com/c/new','full_name':'c/new'},
                           {'url':'https://github.com/b/profiles','full_name':'b/profiles'}]}
        result=merge_discovery(value,plan(),[packet])
        old=next(c for c in value['candidates'] if c['repo']=='b/profiles')
        new=next(c for c in result['candidates'] if c['repo']=='b/profiles')
        self.assertEqual(new['source_leads'],old['source_leads'])
        self.assertEqual(result['source_captures'],value['source_captures'])
        self.assertEqual(review_evidence(result,[card()])['cards'],[card()])
        self.assertEqual(value,before)
        again=merge_discovery(result,plan(),[packet])
        self.assertEqual(again['candidates'],result['candidates'])

    def test_bounded_briefing_spreads_saturated_requirement_lanes(self):
        p=plan(); p['queries'][2]['provider']='github'
        packets=[]
        for q in p['queries']:
            hits=[{'url':f'https://github.com/lane{q["id"]}/item{i}','full_name':f'lane{q["id"]}/item{i}'} for i in range(30)]
            packets.append({'query_id':q['id'],'query_text':q['text'],'provider':q['provider'],'state':'ok','results':hits})
        value=build_ledger(p,packets)
        briefs=make_briefs(value,6,'capabilities')
        self.assertEqual(len(briefs['briefs']),6)
        identities={b['repo'] for b in briefs['briefs']}
        self.assertTrue(any(r.startswith('laneq2/') for r in identities))
        self.assertTrue(any(r.startswith('laneq3/') for r in identities))
        for baseline in briefs['eligible_baselines'].values():
            self.assertEqual(set(baseline['review_queue']),identities)
        self.assertTrue(briefs['unbriefed_frontpage'])

    def test_literal_relationship_hints_preserve_lowercase_and_library_evidence(self):
        value=ledger(); hit=value['candidates'][0]['hits'][0]
        hit['description']='Downloads media using the ProfileKit library; messages in rhino.'
        names={h['mention'].lower():h for h in mention_hints(value)}
        self.assertIn('profilekit',names); self.assertIn('rhino',names)
        for name in ['profilekit','rhino']:
            hint=names[name]
            self.assertIn(hint['excerpt'],hit['description'])
            self.assertEqual(hint['repo'],'a/app')
        self.assertEqual(len(value['candidates']),1)


class RunClock(unittest.TestCase):
    def setUp(self): self.at=dt.datetime(2026,10,5,tzinfo=dt.timezone.utc)

    def test_shared_clock_clamps_each_call_and_stops_at_report_reserve(self):
        run=start('task',60,15,self.at)
        self.assertEqual(allowance(run,100,self.at+dt.timedelta(seconds=30)),15)
        self.assertEqual(status(run,self.at+dt.timedelta(seconds=45))['phase'],'report')
        with self.assertRaises(ValueError): allowance(run,1,self.at+dt.timedelta(seconds=45))
        late=status(run,self.at+dt.timedelta(seconds=72))
        self.assertEqual(late['overrun_seconds'],12)

    def test_finished_clock_cannot_restart_acquisition(self):
        run=start('task',60,15,self.at); run['status']='complete'
        with self.assertRaises(ValueError): allowance(run,10,self.at)

    def test_new_start_cannot_erase_existing_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'run.json'
            args=['start','--task','task','--out',str(path)]
            self.assertEqual(main(args),0)
            before=path.read_bytes()
            self.assertEqual(main(args),2)
            self.assertEqual(path.read_bytes(),before)

    def test_closed_search_cli_rejects_before_network_or_packets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            write_json(root/'plan.json',plan())
            write_json(root/'clock.json',start('task',60,15,self.at))
            with patch('reuse_run.utc',return_value=self.at+dt.timedelta(seconds=46)), patch('reuse_search.run_search') as transport:
                self.assertEqual(search_main(['search','--plan',str(root/'plan.json'),'--run',str(root/'clock.json'),
                    '--out',str(root/'packets')]),2)
                transport.assert_not_called()
            self.assertFalse((root/'packets').exists())

    def test_progress_snapshot_is_available_without_semantic_records_and_keeps_last_frontpage_lead(self):
        value=follow_sources(ledger(),[source()])
        briefs={'unbriefed_frontpage':[{'repo':f'a/lead{i}'} for i in range(32)]}
        report=render_snapshot(value,briefs,review_evidence(value,[card()]))
        self.assertIn('UNFINISHED',report)
        self.assertIn('R2: DEFER / provisional',report)
        self.assertIn('a/lead31',report)
        self.assertIn('documented / supported',report)
        self.assertNotIn('tested /',report)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            write_json(root/'ledger.json',value)
            write_json(root/'clock.json',start('task',60,15,self.at))
            with patch('reuse_run.utc',return_value=self.at+dt.timedelta(seconds=40)):
                self.assertEqual(main(['snapshot','--ledger',str(root/'ledger.json'),'--run',str(root/'clock.json'),
                    '--out',str(root/'progress.md')]),0)
            saved=read_json(root/'clock.json')
            self.assertEqual(saved['status'],'active')
            self.assertEqual(saved['checkpoint_save']['elapsed_seconds'],40)

    def test_handoff_requires_every_requirement_and_accounts_high_unqueued_leads(self):
        value=follow_sources(ledger(),[source()]); value['task']='fixture'
        expanded=plan(); expanded['task']='fixture'; packets=[]
        for i in range(32):
            qid=f'Q{i+4}'
            expanded['queries'].append({'id':qid,'text':f'capability variant {i}','provider':'github',
                                       'family':'capability','requirements':['R1']})
            packets.append({'query_id':qid,'query_text':f'capability variant {i}','provider':'github','state':'ok',
                'results':[{'url':f'https://github.com/a/lead{i}','full_name':f'a/lead{i}',
                            'description':'Documented capability hypothesis'}]})
        value=merge_discovery(value,expanded,packets)
        briefs=make_briefs(value,2)
        judgments={'briefs_sha256':briefs['sha256'],'judgments':[
            {'repo':b['repo'],'requirement':'R1','adoption':'low','study':'high',
             'passage_id':b['passages'][0]['id'],'reason':'Study interface'}
            for b in briefs['briefs'] if b['passages']]}
        screened=rank_briefs(briefs,judgments,1)
        review=review_evidence(value,[card()])
        records={'candidates':[{'repo':r,'reason':'Source-reviewed or explicitly deferred'}
                              for r in set([b['repo'] for b in briefs['briefs']]+['a/app','b/profiles'])],
                 'whole_purpose':{'deferred_reason':'No complete-app documentation reviewed in fixture'}}
        decisions={'decisions':[{'requirement':r,'decision':'DEFER','status':'provisional',
                                'reason':'Target integration unknown','next_check':'Adapter fixture'} for r in ['R1','R2']]}
        report,audit=render_report(value,briefs,screened,review,records,decisions)
        self.assertTrue(audit['accounted']); self.assertIn('b/profiles',report)
        self.assertIn('documented / supported',report)
        self.assertNotIn('tested /',report)
        self.assertGreater(len(briefs['unbriefed_frontpage']),20)
        last=briefs['unbriefed_frontpage'][-1]['repo']
        self.assertIn(last,report)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            args=['handoff']
            for name,data in [('ledger',value),('briefs',briefs),('screened',screened),('review',review),
                              ('records',records),('decisions',decisions),('run',start('task',60,15,self.at))]:
                path=root/(name+'.json'); write_json(path,data); args+=['--'+name,str(path)]
            args+=['--out',str(root/'report.md'),'--audit-out',str(root/'audit.json')]
            with patch('reuse_run.utc',return_value=self.at+dt.timedelta(seconds=72)):
                self.assertEqual(main(args),3)
            audit=read_json(root/'audit.json')
            self.assertTrue(audit['accounted'])
            self.assertFalse(audit['timing']['deadline_met'])
            self.assertEqual(read_json(root/'run.json')['outcome'],'late')
            self.assertIn(last,(root/'report.md').read_text(encoding='utf-8'))
        decisions['decisions'].pop()
        with self.assertRaises(ValueError): render_report(value,briefs,screened,review,records,decisions)


if __name__=='__main__': unittest.main()
