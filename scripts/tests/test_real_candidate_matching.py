"""Software contracts and replay of saved AI judgments, not accuracy metrics."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'experiments/real-candidate-matching'
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(DATA))
spec=importlib.util.spec_from_file_location('real_candidate_experiment',DATA/'run_experiment.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class RealCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=runner.read(DATA/'catalog.json')
        cls.prepared={'cases':runner.public_prepared(cls.catalog)}
        cls.reviews=runner.read(DATA/'reviews-public.json')
        cls.results=runner.evaluate_cases(cls.prepared,cls.reviews,cls.catalog)

    def test_same_candidate_set_competes_without_collapsing_types(self):
        first,second=self.results
        expected={c['id'] for c in self.catalog['motifs']}
        for c in self.results:
            self.assertEqual({a['motif_id'] for a in c['result']['author_audit']},expected)
            self.assertTrue(all(c['checks'].values()))
        self.assertEqual({p['knowledge_kind'] for p in first['result']['writer_packet']['proposals']},{'motif','technique'})
        self.assertEqual({p['knowledge_kind'] for p in second['result']['writer_packet']['proposals']},{'motif','situation'})
        self.assertNotIn('suspense_inquiry_continue',{p['id'] for p in second['result']['writer_packet']['proposals']})

    def test_actual_answer_accompanies_confirmation_condition(self):
        writer=self.results[1]['result']['writer_packet']
        facts={f['id']:f['text'] for f in writer['facts']}
        self.assertIn('f003',facts)
        self.assertIn('仓管故意纵火',facts['f003'])
        self.assertTrue(any(f.startswith('probe_') for f in facts))

    def test_missing_evidence_not_promoted_to_magic_or_missing_truth_risk(self):
        for c in self.results:
            magic=next(a for a in c['result']['author_audit'] if a['motif_id']=='homeopathic_magic')
            self.assertEqual(magic['entry_status'],'needs_evidence')
            self.assertEqual(set(magic['unknown_condition_ids']),{'surrogate','belief'})
        truth=next(a for a in self.results[1]['result']['author_audit'] if a['motif_id']=='truth_pursuit')
        self.assertEqual(truth['supported_condition_ids'],['investigating'])
        self.assertEqual(truth['unknown_condition_ids'],['obstructed'])

    def test_public_projection_excludes_all_freeform_private_payloads(self):
        results=copy.deepcopy(self.results)
        secret='PRIVATE_NOVEL_SENTINEL_独有正文'
        for c in results:
            c['title']=secret;c['pov_character']=secret;c['prefix']=[{'text':secret}]
            c['review']['decisions'][0]['reason']=secret
            c['result']['author_audit'][0]['conditions'][0]['question']=secret
            c['result']['writer_packet']['facts'][0]['text']=secret
            c['result']['writer_packet']['proposals'][0]['proposal']=secret
        self.assertNotIn(secret,json.dumps(runner.summary(results,'2026-10-26'),ensure_ascii=False))

    def test_mutated_public_sample_and_missing_review_rejected(self):
        p=copy.deepcopy(self.prepared);p['cases'][0]['project']['title']='mutated'
        with self.assertRaisesRegex(ValueError,'Public sample differs'):
            runner.evaluate_cases(p,self.reviews,self.catalog)
        r=copy.deepcopy(self.reviews);r['reviews'].pop()
        with self.assertRaisesRegex(ValueError,'Missing or extra'):
            runner.evaluate_cases(self.prepared,r,self.catalog)
        r=copy.deepcopy(self.reviews);r['reviews'].append(copy.deepcopy(r['reviews'][0]))
        with self.assertRaisesRegex(ValueError,'Unknown or duplicate'):
            runner.evaluate_cases(self.prepared,r,self.catalog)

    def test_source_inputs_are_unchanged(self):
        before=copy.deepcopy((self.prepared,self.reviews,self.catalog))
        runner.evaluate_cases(self.prepared,self.reviews,self.catalog)
        self.assertEqual(before,(self.prepared,self.reviews,self.catalog))

    def test_html_escapes_prefix_and_questions(self):
        results=copy.deepcopy(self.results)
        payload='<script>alert(1)</script><img src=x onerror="alert(2)">'
        results[0]['prefix'][0]['text']=payload
        results[0]['result']['author_audit'][0]['conditions'][0]['question']=payload
        page=runner.render(results,runner.summary(results,'2026-10-26'))
        self.assertNotIn('<script>',page);self.assertNotIn('<img ',page)
        self.assertIn('&lt;script&gt;',page)

    def test_runtime_output_must_be_fresh_and_no_parent_links(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as folder:
            root=Path(folder);(root/'runtime-data').mkdir()
            with patch.object(runner,'REPO',root):
                good=root/'runtime-data'/'new';self.assertEqual(runner.fresh_dir(good),good)
                with self.assertRaises(ValueError):runner.fresh_dir(good)
                with self.assertRaises(ValueError):runner.fresh_dir(root/'outside')
                link=root/'runtime-data'/'link';link.symlink_to(root,target_is_directory=True)
                with self.assertRaises(ValueError):runner.fresh_dir(link/'escaped')
                self.assertFalse((root/'escaped').exists())

if __name__=='__main__':unittest.main()
