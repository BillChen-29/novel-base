"""Contract tests use synthetic reviewer decisions, not semantic accuracy labels."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from recommendation_session import new_session, source_token, append_scene, canonical_digest
from recommendation_engine import (prepare_state, review_state, prepare_recommendations,
    review_recommendations, accept_current)


def review(packet, reject=(), unknown=(), hidden=()):
    decisions = []
    for candidate in packet['candidates']:
        fid = candidate['fact_id']
        scene = next(s for s in packet['scenes'] if s['id'] == candidate['scene_id'])
        evidence = [{'scene_id': scene['id'], 'start': 0, 'end': len(scene['text']), 'quote': scene['text']}]
        verdict = 'contradicted' if fid in reject else 'insufficient_evidence' if fid in unknown else 'supported'
        decisions.append({'fact_id': fid, 'verdict': verdict, 'epistemic_type': 'established',
            'reason': 'Synthetic gate contract only', 'evidence': evidence,
            'knowledge': [{'character_id': c, 'verdict': 'insufficient_evidence' if fid in hidden else verdict,
                'reason': 'Synthetic gate contract only', 'evidence': evidence} for c in candidate['claimed_known_by']]})
    return {'schema_version': 1, **{k: packet[k] for k in ('project_id','project_sha256','packet_sha256')},
            'reviewer': {'kind': 'agent_review', 'name': 'synthetic-test'}, 'decisions': decisions}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        text = '林拿着纸条，尚未读取。另一张单据已经核对完。'
        self.project = {'schema_version': 1, 'project_id': 'p', 'title': 'P', 'pov_character': '林',
            'characters': ['林'], 'goal': {'id':'recover_and_investigate','description':'读纸条'},
            'scenes': [{'id':'s1','order':1,'function':'current','tension':2,'present_characters':['林'],'text':text}],
            'facts': [], 'threads': []}
        anchor = {'scene_id':'s1','start':0,'end':len(text)}
        self.annotations = {'facts':[{'id':'base','text':'林持有未读纸条。','scene_id':'s1','quote':text,
            'start':0,'end':len(text),'known_by':['林']}], 'registry': {
            'characters':[{'id':'lin','label':'林'}], 'entities':[{'id':'note','label':'纸条'}],
            'tasks':[{'id':'understand','label':'弄清纸条内容'}], 'actions':[{
                'id':'read_note','actor_id':'lin','target_ids':['note'],'task_id':'understand','operation':'read',
                'description':'读取纸条','origin':'proposed','status':'proposed','anchor':anchor}]}}
        path = self.root/'assets/motif_library/example.md'; path.parent.mkdir(parents=True); path.write_text('纸条读取流程')
        self.catalog = {'schema_version':1,'status':'experimental_operationalization','motifs':[{
            'id':'read','title':'纸条读取','knowledge_kind':'situation',
            'source':{'path':'assets/motif_library/example.md','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'evidence':[{'start':0,'end':6,'quote':'纸条读取流程'}]},
            'roles':{'actor':'character','target':'object','task':'object','action':'object'},
            'conditions':[{'id':'unread','kind':'world_state','claim_template':'{actor}尚未读{target}；任务{task}；动作{action}。'}],
            'entry_conditions':[],'stage_mode':'alternatives',
            'stages':[{'id':'start','title':'未读','requires':['unread'],'chronological':[]}],
            'variants':[{'id':'read_start','title':'读取','from_stage':'start','requires':[],
                'proposal':'读取','proposal_template':'{actor}开始{action}，针对{target}推进{task}，结果待正文。',
                'operations':['read'],'action_states':['proposed','pending']}],
            'retrieval_text':'纸条 未读 读取 信息 内容'}]}

    def state(self, annotations=None, **kwargs):
        session = new_session(self.project)
        req = prepare_state(session, annotations or self.annotations)
        return review_state(session, req, review(req['packet'], **kwargs)), req

    def batch(self, session, **kwargs):
        req = prepare_recommendations(session, self.catalog, self.root)
        reviews = {x['id']: review(x['prepared']['packet'], **kwargs) for x in req['instances']}
        return review_recommendations(session, req, reviews, self.catalog, self.root), req

    def test_acceptance_is_intent_and_append_invalidates(self):
        state, _ = self.state(); session, req = self.batch(state)
        proposal = session['current_batch']['proposals'][0]
        accepted = accept_current(session, proposal['id'], source_token(session), session['batch_sha256'], self.catalog, self.root)
        self.assertEqual(accepted['current_state'], session['current_state'])
        self.assertEqual(accepted['source'], session['source'])
        self.assertEqual(len(accepted['plans']), 1)
        next_scene = dict(self.project['scenes'][0], id='s2',order=2,text='林打开纸条，读完内容。')
        changed = append_scene(accepted, next_scene, source_token(accepted))
        self.assertIsNone(changed['current_state']); self.assertIsNone(changed['current_batch'])
        with self.assertRaises(ValueError):
            review_recommendations(changed, req, {}, self.catalog, self.root)

    def test_unreviewed_binding_and_state_fail_closed(self):
        state, request = self.state()
        binding = request['action_claims']['read_note']['binding']
        state, _ = self.state(hidden=[binding])
        session, _ = self.batch(state)
        self.assertEqual(session['current_batch']['proposals'], [])

    def test_renamed_action_or_task_cannot_bypass_completion(self):
        annotations = copy.deepcopy(self.annotations)
        old = copy.deepcopy(annotations['registry']['actions'][0])
        old.update(id='already_read',origin='observed',status='completed')
        annotations['registry']['actions'].append(old)
        annotations['registry']['tasks'].append({'id':'newtask','label':'另外安排'})
        annotations['registry']['actions'][0]['task_id'] = 'newtask'
        state, _ = self.state(annotations)
        session, _ = self.batch(state)
        self.assertFalse(session['current_batch']['proposals'])

    def test_catalog_change_rejects_acceptance(self):
        state, _ = self.state(); session, _ = self.batch(state)
        changed = copy.deepcopy(self.catalog); changed['motifs'][0]['retrieval_text'] += ' 新版'
        with self.assertRaises(ValueError):
            accept_current(session, session['current_batch']['proposals'][0]['id'], source_token(session),session['batch_sha256'],changed,self.root)

    def test_no_query_no_backfill_and_no_probe_query_contamination(self):
        annotations = copy.deepcopy(self.annotations); annotations['facts'] = []
        state,_ = self.state(annotations); session,req = self.batch(state)
        self.assertEqual(req['query'], ''); self.assertEqual(req['ranking'], [])
        self.assertEqual(session['current_batch']['proposals'], [])
        state,_ = self.state(); _, req = self.batch(state)
        self.assertEqual(req['query'], '林持有未读纸条。')

    def test_request_and_cross_project_review_binding(self):
        session = new_session(self.project); req = prepare_state(session, self.annotations)
        altered=copy.deepcopy(req); altered['annotations']['registry']['entities'][0]['label']='另一纸条'
        with self.assertRaises(ValueError): review_state(session,altered,review(req['packet']))
        other=new_session(dict(self.project,project_id='other'))
        with self.assertRaises(ValueError): review_state(other,req,review(req['packet']))

    def test_unsupported_condition_never_recommends(self):
        state,_=self.state(); req=prepare_recommendations(state,self.catalog,self.root)
        reviews={x['id']:review(x['prepared']['packet'],unknown=[f['fact_id'] for f in x['prepared']['packet']['candidates']]) for x in req['instances']}
        session=review_recommendations(state,req,reviews,self.catalog,self.root)
        self.assertFalse(session['current_batch']['proposals'])


if __name__ == '__main__': unittest.main()
