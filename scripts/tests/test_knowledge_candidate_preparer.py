"""Generated review questions remain untrusted until independently reviewed."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from knowledge_candidate_preparer import prepare_candidates, main
from motif_matcher import match_motifs


class CandidatePreparerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);(self.root/'assets').mkdir()
        source='核对疑点，不预先宣布答案。'
        (self.root/'assets/test.md').write_text(source)
        self.catalog={'schema_version':1,'status':'experimental_operationalization','motifs':[{
          'id':'observe','title':'核对疑点','knowledge_kind':'technique',
          'source':{'path':'assets/test.md','sha256':hashlib.sha256(source.encode()).hexdigest(),
                    'evidence':[{'start':0,'end':len(source),'quote':source}]},
          'roles':{'observer':'character','object':'object'},
          'conditions':[{'id':'observed','kind':'content','claim_template':'{observer}看到了{object}。'},
                        {'id':'answered','kind':'world_state','claim_template':'{observer}已确认{object}的用途。'}],
          'entry_conditions':['observed'],
          'stages':[{'id':'question','title':'等待核对','requires':['observed'],'chronological':[]}],
          'variants':[{'id':'observe_more','title':'核对已见物件','from_stage':'question','requires':[],
                       'proposal':'围绕已观察到的物件继续核对，不预设答案。'}]}]}
        self.project={'schema_version':1,'project_id':'one','title':'黑伞 🔑','pov_character':'阿澄',
          'characters':['阿澄','老陆'],'goal':{'id':'recover_and_investigate','description':'调查'},
          'scenes':[{'id':'s1','order':1,'function':'investigation','tension':2,
                     'present_characters':['阿澄'],'text':'阿澄看到了黑伞。她还不知道用途。🔑'}],
          'facts':[{'id':'probe_0001','text':'阿澄看到了黑伞。','scene_id':'s1','quote':'阿澄看到了黑伞。','known_by':['阿澄']}],
          'threads':[]}
        self.instances=[{'id':'candidate1','motif_id':'observe','bindings':{'observer':'阿澄','object':'黑伞'},
                         'anchors':{'observed':{'scene_id':'s1','start':0,'end':len('阿澄看到了黑伞。')}}}]

    def prepare(self, **kwargs):
        return prepare_candidates(kwargs.get('project',self.project),kwargs.get('catalog',self.catalog),
                                  kwargs.get('instances',self.instances),self.root)

    def mock_review(self, packet, support=False):
        decisions=[]
        for c in packet['candidates']:
            supported=support and c['text']=='阿澄看到了黑伞。'
            ev={k:c[k] for k in ('scene_id','start','end','quote')}
            decisions.append({'fact_id':c['fact_id'],'verdict':'supported' if supported else 'insufficient_evidence',
               'epistemic_type':'established' if supported else 'uncertain','reason':'软件测试模拟判断。',
               'evidence':[ev] if supported else [],'knowledge':[
                 {'character_id':who,'verdict':'supported' if supported and who=='阿澄' else 'insufficient_evidence',
                  'reason':'模拟角色范围。','evidence':[ev] if supported and who=='阿澄' else []}
                 for who in c['claimed_known_by']]})
        return {'schema_version':1,**{k:packet[k] for k in ('project_id','project_sha256','packet_sha256')},
                'reviewer':{'kind':'agent_review','name':'test-mock'},'decisions':decisions}

    def test_exact_claim_generated_with_context_only_label(self):
        result=self.prepare();derived=result['project'];packet=result['packet']
        mapping=derived['motif_annotations']['instances'][0]['condition_facts']
        self.assertEqual(set(mapping),{'observed'})
        self.assertNotEqual(mapping['observed'],'probe_0001')
        generated=next(c for c in packet['candidates'] if c['fact_id']==mapping['observed'])
        self.assertEqual(generated['text'],'阿澄看到了黑伞。')
        self.assertEqual(generated['quote'],'阿澄看到了黑伞。')
        self.assertEqual(generated['claimed_epistemic_status'],'unreviewed_condition_probe')
        self.assertEqual(generated['claimed_known_by'],['阿澄','老陆'])

    def test_no_anchor_leaves_unknown_without_fabricated_fact(self):
        self.instances[0]['anchors']={}
        result=self.prepare()
        self.assertEqual(result['project']['facts'],self.project['facts'])
        output=match_motifs(result['project'],result['packet'],self.mock_review(result['packet'],True),self.catalog,self.root)
        self.assertEqual(output['writer_packet']['proposals'],[])
        self.assertEqual(output['author_audit'][0]['unknown_condition_ids'],['observed','answered'])
        self.assertEqual(output['author_audit'][0]['conditions'][0]['question'],'阿澄看到了黑伞。')
        self.assertIsNone(output['author_audit'][0]['conditions'][0]['claim'])

    def test_context_position_does_not_grant_entailment(self):
        self.instances[0]['anchors']['answered']={'scene_id':'s1','start':0,'end':len('阿澄看到了黑伞。')}
        result=self.prepare()
        output=match_motifs(result['project'],result['packet'],self.mock_review(result['packet']),self.catalog,self.root)
        self.assertEqual(output['writer_packet'],{'facts':[],'proposals':[]})
        reviewed=match_motifs(result['project'],result['packet'],self.mock_review(result['packet'],True),self.catalog,self.root)
        self.assertEqual(reviewed['writer_packet']['proposals'][0]['knowledge_kind'],'technique')
        self.assertNotIn('已确认',reviewed['writer_prompt'])
        self.assertEqual(reviewed['author_audit'][0]['supported_condition_ids'],['observed'])
        self.assertEqual(reviewed['author_audit'][0]['unknown_condition_ids'],['answered'])

    def test_inputs_unchanged_and_replay_deterministic(self):
        before=copy.deepcopy((self.project,self.catalog,self.instances))
        first=self.prepare();second=self.prepare()
        self.assertEqual(first,second)
        self.assertEqual(before,(self.project,self.catalog,self.instances))
        first['project']['facts'].clear()
        self.assertEqual(len(self.project['facts']),1)

    def test_project_changes_invalidate_imported_review(self):
        result=self.prepare();review=self.mock_review(result['packet'],True)
        other=copy.deepcopy(self.project);other['project_id']='two'
        fresh=self.prepare(project=other)
        with self.assertRaisesRegex(ValueError,'binding_mismatch'):
            match_motifs(fresh['project'],fresh['packet'],review,self.catalog,self.root)

    def test_existing_annotations_are_not_overwritten(self):
        self.project['motif_annotations']={}
        with self.assertRaisesRegex(ValueError,'existing_motif_annotations'):self.prepare()

    def test_anchor_boundaries_and_unicode(self):
        for start,end in [(True,2),(0,False),(-1,2),(2,2),(0,999),('0',2)]:
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):
                items=copy.deepcopy(self.instances);items[0]['anchors']['observed'].update(start=start,end=end)
                self.prepare(instances=items)
        text=self.project['scenes'][0]['text']
        self.instances[0]['anchors']['observed'].update(start=len(text)-1,end=len(text))
        result=self.prepare()
        self.assertEqual(result['packet']['candidates'][-1]['quote'],'🔑')

    def test_malformed_inputs_fail_closed(self):
        changes=[lambda x:x[0].update(id=' '),lambda x:x.append(copy.deepcopy(x[0])),
          lambda x:x[0].update(motif_id='missing'),lambda x:x[0]['bindings'].update(observer='未知人物'),
          lambda x:x[0]['bindings'].update(object=''),lambda x:x[0]['bindings'].update(extra='x'),
          lambda x:x[0].update(anchors=[]),lambda x:x[0]['anchors'].update(bad={'scene_id':'s1','start':0,'end':1}),
          lambda x:x[0]['anchors']['observed'].update(scene_id='future'),lambda x:x[0]['anchors'].update(observed=None),
          lambda x:x[0].update(bindings=None),lambda x:x[0].update(id=True)]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):
                items=copy.deepcopy(self.instances);change(items);self.prepare(instances=items)
        for bad in (None,{},'x',[None]):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.prepare(instances=bad)
        with self.assertRaises(ValueError):self.prepare(project=None)

    def test_empty_candidates_and_source_validation(self):
        output=self.prepare(instances=[])
        self.assertEqual(output['project']['motif_annotations']['instances'],[])
        self.assertEqual(output['project']['facts'],self.project['facts'])
        self.catalog['motifs'][0]['source']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'source_hash'):self.prepare()

    def test_catalog_kind_and_template_rejected(self):
        for kind in (None,[],{},'case',True):
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                cat=copy.deepcopy(self.catalog);cat['motifs'][0]['knowledge_kind']=kind;self.prepare(catalog=cat)
        cat=copy.deepcopy(self.catalog);cat['motifs'][0]['conditions'][0]['claim_template']='{observer.__class__}'
        with self.assertRaisesRegex(ValueError,'template_role'):self.prepare(catalog=cat)

    def test_cli_stdout_and_errors(self):
        args=[]
        for name,value in [('project',self.project),('catalog',self.catalog),('instances',self.instances)]:
            p=self.root/(name+'.json');p.write_text(json.dumps(value,ensure_ascii=False))
            args+=['--'+name,str(p)]
        args+=['--repo-root',str(self.root)]
        out=io.StringIO()
        with redirect_stdout(out):self.assertEqual(main(args),0)
        self.assertEqual(json.loads(out.getvalue())['project']['project_id'],'one')
        (self.root/'instances.json').write_text('{bad')
        with redirect_stderr(io.StringIO()):self.assertEqual(main(args),1)


if __name__=='__main__':unittest.main()
