"""Software gates for imported semantic decisions; mock decisions are not model evals."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))
from semantic_review import prepare_review, apply_review, run_reviewed_pipeline, main


def project():
    return {'schema_version':1, 'project_id':'gate-test', 'title':'夜雨 🗝️', 'pov_character':'阿青',
        'characters':['阿青','阿白'], 'goal':{'id':'recover_and_investigate','description':'调查钥匙的用途。'},
        'scenes':[
            {'id':'s1','order':1,'function':'action','tension':5,'present_characters':['阿青','阿白'],
             'text':'阿青拿起铜钥匙。阿白亲眼看见。阿青左手被门框划伤。🔑\r\n'},
            {'id':'s2','order':2,'function':'action','tension':4,'present_characters':['阿青','阿白'],
             'text':'阿白独自读到纸条：暗号是夜航。他没有告诉阿青。阿青仍不知道暗号。'}],
        'facts':[
            {'id':'key','text':'阿青持有铜钥匙。','scene_id':'s1','quote':'阿青拿起铜钥匙。','known_by':['阿青','阿白']},
            {'id':'wrong','text':'阿青左手完好无伤。','scene_id':'s1','quote':'阿青左手被门框划伤。','known_by':['阿青']},
            {'id':'secret','text':'暗号是夜航。','scene_id':'s2','quote':'暗号是夜航。','known_by':['阿青','阿白']}],
        'threads':[{'id':'thread','description':'核对钥匙','status':'open','setup_fact_ids':['key'],
                    'resolution_fact_id':'secret','reveal_allowed':True}]}


def evidence(packet, scene_id, quote):
    scene = next(s for s in packet['scenes'] if s['id']==scene_id)
    start = scene['text'].index(quote)
    return {'scene_id':scene_id,'start':start,'end':start+len(quote),'quote':quote,
            'source_sha256':scene['source_sha256']}


def review_for(packet):
    decisions = []
    for candidate in packet['candidates']:
        ev = evidence(packet,candidate['scene_id'],candidate['quote'])
        decisions.append({'fact_id':candidate['fact_id'],
            'verdict':'contradicted' if candidate['fact_id']=='wrong' else 'supported',
            'epistemic_type':'established','reason':'软件契约测试用模拟审核，不代表自动语义评估。',
            'evidence':[ev], 'knowledge':[{'character_id':c,
                'verdict':'contradicted' if candidate['fact_id']=='secret' and c=='阿青' else 'supported',
                'reason':'用原文知识范围作为测试输入。',
                'evidence':[evidence(packet,'s2','阿青仍不知道暗号。')] if candidate['fact_id']=='secret' and c=='阿青' else [ev]}
                for c in candidate['claimed_known_by']]})
    return {'schema_version':1, 'project_id':packet['project_id'],'project_sha256':packet['project_sha256'],
        'packet_sha256':packet['packet_sha256'], 'reviewer':{'kind':'agent_review','name':'mock-for-software-contract'},
        'decisions':decisions}


class SemanticReviewTests(unittest.TestCase):
    def setUp(self):
        self.source=project(); self.packet=prepare_review(self.source); self.review=review_for(self.packet)

    def test_actual_recommendation_accepts_positive_but_excludes_wrong_and_unknown(self):
        result=run_reviewed_pipeline(self.source,self.packet,self.review,REPO)
        report=result['recommendation']
        self.assertIn('阿青持有铜钥匙',report['writer_prompt'])
        self.assertNotIn('完好无伤',report['writer_prompt'])
        self.assertNotIn('夜航',report['writer_prompt'])
        self.assertTrue(report['recommendations'])
        self.assertEqual(result['audit']['accepted_fact_ids'],['key','secret'])
        self.assertEqual(report['story_state']['known_fact_ids'],['key'])
        self.assertEqual(next(f for f in result['project']['facts'] if f['id']=='secret')['known_by'],['阿白'])
        self.assertEqual(result['audit']['reviewer']['kind'],'agent_review')

    def test_missing_reviews_or_knowledge_never_default_to_author_labels(self):
        empty=copy.deepcopy(self.review); empty['decisions']=[]
        result=run_reviewed_pipeline(self.source,self.packet,empty,REPO)
        self.assertEqual(result['project']['facts'],[])
        self.assertEqual(result['recommendation']['recommendations'],[])
        partial=copy.deepcopy(self.review); partial['decisions'][0]['knowledge']=[]
        result=run_reviewed_pipeline(self.source,self.packet,partial,REPO)
        self.assertEqual(result['recommendation']['story_state']['known_fact_ids'],[])
        self.assertNotIn('铜钥匙',result['recommendation']['writer_prompt'])

    def test_reported_inferred_and_uncertain_claims_cannot_become_world_facts(self):
        for kind in ('reported','inferred','uncertain'):
            with self.subTest(kind=kind):
                review=copy.deepcopy(self.review); review['decisions'][0]['epistemic_type']=kind
                output=apply_review(self.source,self.packet,review)
                self.assertNotIn('key',output['audit']['accepted_fact_ids'])
                self.assertFalse(any(t['id']=='thread' for t in output['project']['threads']))
        review=copy.deepcopy(self.review); review['decisions'][0].update(verdict='insufficient_evidence',evidence=[])
        self.assertNotIn('key',apply_review(self.source,self.packet,review)['audit']['accepted_fact_ids'])

    def test_no_input_or_asset_mutations(self):
        before=copy.deepcopy((self.source,self.packet,self.review))
        output=apply_review(self.source,self.packet,self.review)
        self.assertEqual((self.source,self.packet,self.review),before)
        output['project']['facts'][0]['text']='changed derived copy'
        self.assertEqual((self.source,self.packet,self.review),before)

    def test_cutoff_has_no_future_text_facts_or_metadata(self):
        prefix=self.source['scenes'][0]['text']
        packet=prepare_review(self.source,'s1',len(prefix))
        serialized=json.dumps(packet,ensure_ascii=False)
        self.assertNotIn('夜航',serialized)
        self.assertNotIn('secret',serialized)
        self.assertEqual(packet['scenes'][0]['text'],prefix)
        self.assertEqual(packet['cutoff'],{'scene_id':'s1','scene_order':1,'offset':len(prefix)})
        partial=prepare_review(self.source,'s1',len('阿青拿起铜钥匙。'))
        self.assertEqual([c['fact_id'] for c in partial['candidates']],['key'])
        result=apply_review(self.source,partial,review_for(partial))
        self.assertEqual(result['project']['scenes'][0]['text'],'阿青拿起铜钥匙。')
        self.assertIsNone(result['project']['threads'][0]['resolution_fact_id'])
        self.assertFalse(result['project']['threads'][0]['reveal_allowed'])

    def test_zero_cutoff_and_invalid_cutoffs(self):
        packet=prepare_review(self.source,'s1',0)
        self.assertEqual(packet['scenes'],[])
        self.assertEqual(packet['candidates'],[])
        with self.assertRaisesRegex(ValueError,'empty_history'):
            apply_review(self.source,packet,review_for(packet))
        for scene_id,offset in [('missing',None),('s1',-1),('s1',True),('s1',99999),(None,1),('s1','2')]:
            with self.subTest(scene_id=scene_id,offset=offset), self.assertRaises(ValueError):
                prepare_review(self.source,scene_id,offset)

    def test_project_and_packet_changes_invalidate_review(self):
        mutations=[lambda p:p.update(project_id='another-book'),
            lambda p:p['scenes'][0].update(text=p['scenes'][0]['text']+'改动'),
            lambda p:p['facts'][0].update(text='另一命题'),
            lambda p:p['facts'][0].update(known_by=['阿青'])]
        for change in mutations:
            altered=copy.deepcopy(self.source);change(altered)
            with self.assertRaises(ValueError):apply_review(altered,self.packet,self.review)
        for field,value in [('project_id','other'),('project_sha256','0'*64),('packet_sha256','0'*64)]:
            altered=copy.deepcopy(self.review);altered[field]=value
            with self.assertRaises(ValueError):apply_review(self.source,self.packet,altered)
        altered=copy.deepcopy(self.packet);altered['cutoff']['offset']=1
        with self.assertRaises(ValueError):apply_review(self.source,altered,self.review)
        altered=copy.deepcopy(self.packet);altered['scenes'][0]['text']+='fake'
        with self.assertRaises(ValueError):apply_review(self.source,altered,self.review)

    def test_future_or_inexact_review_evidence_rejected(self):
        packet=prepare_review(self.source,'s1',len('阿青拿起铜钥匙。'))
        base=review_for(packet)
        bad_evidence=[{'scene_id':'s2','start':0,'end':2,'quote':'阿白'},
            {'scene_id':'s1','start':0,'end':999,'quote':'阿青'},
            {'scene_id':'s1','start':True,'end':2,'quote':'阿青'},
            {'scene_id':'s1','start':0,'end':2,'quote':'假的'},
            {'scene_id':'s1','start':0,'end':2,'quote':'阿青','source_sha256':'0'*64}]
        for item in bad_evidence:
            with self.subTest(item=item),self.assertRaises(ValueError):
                review=copy.deepcopy(base);review['decisions'][0]['evidence']=[item]
                apply_review(self.source,packet,review)
        review=copy.deepcopy(base);review['decisions'][0]['evidence']=[]
        with self.assertRaises(ValueError):apply_review(self.source,packet,review)

    def test_duplicate_unknown_or_invalid_decisions_rejected(self):
        changes=[lambda r:r['decisions'].append(copy.deepcopy(r['decisions'][0])),
            lambda r:r['decisions'][0].update(fact_id='invented'),
            lambda r:r['decisions'][0].update(verdict='approved'),
            lambda r:r['decisions'][0].update(epistemic_type='probably'),
            lambda r:r['decisions'][0].update(reason=''),
            lambda r:r['decisions'][0]['knowledge'].append(copy.deepcopy(r['decisions'][0]['knowledge'][0])),
            lambda r:r['decisions'][0]['knowledge'][0].update(character_id='stranger'),
            lambda r:r['decisions'][0]['knowledge'][0].update(verdict='probably'),
            lambda r:r['reviewer'].update(kind='automatic_model')]
        for change in changes:
            review=copy.deepcopy(self.review);change(review)
            with self.subTest(change=change),self.assertRaises(ValueError):apply_review(self.source,self.packet,review)

    def test_duplicate_quote_requires_explicit_position(self):
        source=project();source['scenes'][0]['text']+='阿青拿起铜钥匙。'
        with self.assertRaisesRegex(ValueError,'ambiguous_quote'):prepare_review(source)
        source['facts'][0].update(start=0,end=len('阿青拿起铜钥匙。'))
        self.assertEqual(prepare_review(source)['candidates'][0]['start'],0)
        source['facts'][0]['end']=1
        with self.assertRaises(ValueError):prepare_review(source)

    def test_missing_required_setup_does_not_unlock_revelation(self):
        source=project();source['threads'][0]['setup_fact_ids']=['key','wrong'];source['goal']['id']='reveal_truth'
        packet=prepare_review(source);review=review_for(packet)
        result=run_reviewed_pipeline(source,packet,review,REPO)
        self.assertFalse(result['project']['threads'])
        self.assertNotIn('earned_reveal',[r['id'] for r in result['recommendation']['recommendations']])
        self.assertIn('thread',result['audit']['excluded_thread_ids'])

    def test_invalid_input_shapes(self):
        for bad in (None,[],{},'story'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):prepare_review(bad)
        for bad in (None,[],{},'review'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):apply_review(self.source,self.packet,bad)

    def test_large_candidate_set_is_fully_accounted_for(self):
        source=project(); template=source['facts'][0]
        source['facts']=[dict(copy.deepcopy(template),id=f'candidate-{i}') for i in range(10000)]
        source['threads']=[]
        packet=prepare_review(source)
        self.assertEqual(len(packet['candidates']),10000)
        review={'schema_version':1,'project_id':packet['project_id'],
            'project_sha256':packet['project_sha256'],'packet_sha256':packet['packet_sha256'],
            'reviewer':{'kind':'agent_review','name':'load-contract'},'decisions':[]}
        result=apply_review(source,packet,review)
        self.assertEqual(len(result['audit']['quarantined']),10000)
        self.assertEqual(result['audit']['accepted_fact_ids'],[])

    def test_concurrent_output_replacements_are_complete_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); paths=[]
            for i in range(8):
                source=project(); source['title']=f'并发-{i}'
                path=root/f'project-{i}.json';path.write_text(json.dumps(source,ensure_ascii=False));paths.append(path)
            target=root/'packet.json'
            def prepare_one(path):
                return main(['prepare','--project',str(path),'--output',str(target)])
            with ThreadPoolExecutor(max_workers=4) as pool:
                codes=list(pool.map(prepare_one,paths))
            self.assertEqual(codes,[0]*8)
            written=json.loads(target.read_text())
            valid=[prepare_review(json.loads(p.read_text())) for p in paths]
            self.assertIn(written,valid)
            self.assertFalse(list(root.glob('.semantic-review-*')))

    def test_cli_round_trip_uses_existing_recommender(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'story.json';source.write_text(json.dumps(self.source,ensure_ascii=False))
            packet_file=root/'packet.json';review_file=root/'review.json';review_file.write_text(json.dumps(self.review,ensure_ascii=False))
            self.assertEqual(main(['prepare','--project',str(source),'--output',str(packet_file)]),0)
            self.assertEqual(json.loads(packet_file.read_text()),self.packet)
            self.assertEqual(main(['recommend','--project',str(source),'--packet',str(packet_file),
                '--review',str(review_file),'--repo-root',str(REPO),'--output',str(root/'result.json')]),0)
            result=json.loads((root/'result.json').read_text())
            self.assertTrue(result['recommendation']['recommendations'])
            self.assertNotIn('夜航',result['recommendation']['writer_prompt'])

    def test_cli_output_cannot_overwrite_inputs_or_links(self):
        for mode in ('same','symlink','hardlink','parent_link'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();source=root/'story.json';source.write_text(json.dumps(self.source,ensure_ascii=False))
                before=source.read_bytes();target=source if mode=='same' else root/'output.json'
                if mode=='symlink':target.symlink_to(source)
                if mode=='hardlink':os.link(source,target)
                if mode=='parent_link':
                    outside=root/'outside';outside.mkdir();(root/'link').symlink_to(outside,target_is_directory=True);target=root/'link/output.json'
                self.assertEqual(main(['prepare','--project',str(source),'--output',str(target)]),1)
                self.assertEqual(source.read_bytes(),before)
                if mode=='parent_link':self.assertEqual(list(outside.iterdir()),[])

    def test_reference_repository_assets_are_protected_before_pipeline_and_emit(self):
        import semantic_review
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();reference=root/'reference';(reference/'assets').mkdir(parents=True)
            asset=reference/'assets/ai_patterns.md';asset.write_text('必须保留的知识资产。')
            source=root/'story.json';source.write_text(json.dumps(self.source,ensure_ascii=False))
            packet=root/'packet.json';packet.write_text(json.dumps(self.packet,ensure_ascii=False))
            review=root/'review.json';review.write_text(json.dumps(self.review,ensure_ascii=False))
            args=['recommend','--project',str(source),'--packet',str(packet),'--review',str(review),
                  '--repo-root',str(reference),'--output',str(asset)]
            with patch.object(semantic_review,'run_reviewed_pipeline',return_value={'ok':True}) as pipeline:
                self.assertEqual(main(args),1)
                pipeline.assert_not_called()
            self.assertEqual(asset.read_text(),'必须保留的知识资产。')
            with self.assertRaisesRegex(ValueError,'repo_output_requires_runtime_data'):
                semantic_review._emit({'ok':True},str(asset),[source,packet,review],REPO,reference)
            self.assertEqual(asset.read_text(),'必须保留的知识资产。')
            # A deliberately requested runtime result inside that same reference repo is allowed.
            target=reference/'runtime-data/result.json'
            semantic_review._emit({'ok':True},str(target),[source,packet,review],REPO,reference)
            self.assertEqual(json.loads(target.read_text()),{'ok':True})

    def test_replaced_inode_zero_links_is_not_a_hardlink(self):
        import semantic_review
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'story.json';source.write_text(json.dumps(self.source,ensure_ascii=False))
            target=root/'packet.json';target.write_text('{}')
            original_stat=Path.stat
            def changed_nlink(nlink):
                def stat(path,*args,**kwargs):
                    result=original_stat(path,*args,**kwargs)
                    if path==target:
                        values=list(result);values[3]=nlink
                        return os.stat_result(values)
                    return result
                return stat
            with patch.object(Path,'stat',autospec=True,side_effect=changed_nlink(0)):
                self.assertEqual(main(['prepare','--project',str(source),'--output',str(target)]),0)
            self.assertEqual(json.loads(target.read_text()),self.packet)
            before=target.read_bytes()
            for nlink in (2,3):
                with self.subTest(nlink=nlink),patch.object(Path,'stat',autospec=True,side_effect=changed_nlink(nlink)):
                    self.assertEqual(main(['prepare','--project',str(source),'--output',str(target)]),1)
                self.assertEqual(target.read_bytes(),before)

    def test_cli_stdout_and_error_do_not_call_external_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'story.json';path.write_text(json.dumps(self.source,ensure_ascii=False))
            with patch('sys.stdout') as stream:
                self.assertEqual(main(['prepare','--project',str(path)]),0)
                self.assertTrue(stream.write.called)
            path.write_text('invalid json')
            self.assertEqual(main(['prepare','--project',str(path)]),1)


if __name__=='__main__':unittest.main()
