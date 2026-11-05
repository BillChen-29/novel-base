"""Replay behavior for actual saved AI annotations; not a model-accuracy test."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('motif_experiment',ROOT/'experiments/motif-applicability/run_experiment.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
DATA=ROOT/'experiments/motif-applicability'


class MotifExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures=json.loads((DATA/'fixtures.json').read_text())
        cls.catalog=json.loads((DATA/'catalog.json').read_text())
        cls.reviews=json.loads((DATA/'reviews.json').read_text())
        cls.report=runner.evaluate(cls.fixtures,cls.catalog,cls.reviews,ROOT,'2026-10-26')
        cls.cases={c['case_id']:c['result'] for c in cls.report['cases']}

    def test_password_content_and_carrier_have_separate_knowledge(self):
        before={a['fact_id']:a for a in self.cases['password-before']['atom_view']}
        after={a['fact_id']:a for a in self.cases['password-after']['atom_view']}
        self.assertNotEqual(before['f01']['knowledge']['阿弥'],'true')
        self.assertEqual(after['f01']['knowledge']['阿弥'],'true')
        self.assertNotEqual(after['f02']['knowledge']['阿弥'],'true')
        self.assertEqual(self.cases['password-after']['writer_packet']['proposals'],[])
        self.assertTrue(all(m['entry_status']=='blocked' for m in self.cases['password-after']['author_audit']))

    def test_carrier_delivery_does_not_skip_decoding_and_tools_need_known_use(self):
        def proposals(case):return {p['id'] for p in self.cases[case]['writer_packet']['proposals']}
        self.assertEqual(proposals('woven-encoded'),{'deliver_record'})
        self.assertEqual(proposals('woven-delivered'),{'ask_decoder'})
        self.assertEqual(proposals('woven-key'),{'ask_decoder'})
        self.assertEqual(proposals('woven-key-informed'),{'ask_decoder','compare_key'})
        self.assertEqual(proposals('woven-decoded'),{'respond_to_record'})
        self.assertEqual(self.cases['woven-delivered']['author_audit'][0]['current_stage'],'delivered')

    def test_future_cost_not_required_to_continue_early_motif(self):
        early=self.cases['forbidden-seeking']
        later=self.cases['forbidden-acquired']
        self.assertEqual(early['author_audit'][0]['current_stage'],'seeking')
        self.assertEqual(later['author_audit'][0]['current_stage'],'acquired')
        self.assertEqual({p['id'] for p in later['writer_packet']['proposals']},{'face_possible_cost'})
        self.assertNotIn('f04',{f['id'] for f in later['writer_packet']['facts']})

    def test_replay_workflow_checks_and_input_immutability(self):
        original=copy.deepcopy((self.fixtures,self.catalog,self.reviews))
        runner.evaluate(self.fixtures,self.catalog,self.reviews,ROOT,'2026-10-26')
        self.assertEqual(original,(self.fixtures,self.catalog,self.reviews))
        self.assertEqual(self.report['summary']['cases'],9)
        self.assertEqual(self.report['summary']['workflow_passed'],self.report['summary']['workflow_total'])

    def test_duplicate_case_or_missing_review_refused(self):
        fixtures=copy.deepcopy(self.fixtures)
        fixtures['cases'].append(copy.deepcopy(fixtures['cases'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            runner.evaluate(fixtures,self.catalog,self.reviews,ROOT,'2026-10-26')
        reviews=copy.deepcopy(self.reviews);reviews['reviews'].pop()
        with self.assertRaisesRegex(ValueError,'review_case_set'):
            runner.evaluate(self.fixtures,self.catalog,reviews,ROOT,'2026-10-26')

    def test_report_escapes_story_and_generated_text(self):
        report=copy.deepcopy(self.report)
        payload='<img src=x onerror="alert(1)"><script>alert(2)</script>'
        report['cases'][0]['title']=payload
        report['cases'][0]['prefix'][0]['text']=payload
        report['cases'][0]['result']['atom_view'][0]['text']=payload
        rendered=runner.render_html(report)
        self.assertNotIn('<script>',rendered)
        self.assertNotIn('<img ',rendered)
        self.assertIn('&lt;script&gt;',rendered)

    def test_output_cannot_overwrite_inputs_or_share_html_path(self):
        original=(DATA/'fixtures.json').read_bytes()
        self.assertEqual(runner.main(['--run-date','2026-10-26','--output',str(DATA/'fixtures.json')]),1)
        self.assertEqual(original,(DATA/'fixtures.json').read_bytes())
        with tempfile.TemporaryDirectory() as folder:
            output=str(Path(folder)/'same')
            self.assertEqual(runner.main(['--run-date','2026-10-26','--output',output,'--html',output]),1)
            self.assertFalse(Path(output).exists())


if __name__=='__main__':unittest.main()
