"""Publication and path boundaries for the source-review experiment."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('semantic_experiment',REPO/'experiments/semantic-review/run_experiment.py')
experiment=importlib.util.module_from_spec(spec);spec.loader.exec_module(experiment)


class SemanticExperimentTests(unittest.TestCase):
    def test_public_export_omits_unvalidated_metadata_at_every_level(self):
        extra={'unexpected_full_context':'PRIVATE_CONTEXT_CANARY'}
        evidence={'scene_id':'s1','start':0,'end':2,'quote':'原文',**extra}
        knowledge={'character_id':'甲','verdict':'supported','reason':'明确观察','evidence':[evidence],**extra}
        decision={'fact_id':'f1','verdict':'supported','epistemic_type':'established','reason':'直接记述',
                  'evidence':[evidence],'knowledge':[knowledge],**extra}
        review={'schema_version':1,'project_id':'p','project_sha256':'a'*64,'packet_sha256':'b'*64,
                'reviewer':{'kind':'agent_review','name':'test',**extra},'decisions':[decision],**extra}
        before=copy.deepcopy(review);published=experiment.public_review(review)
        self.assertNotIn('PRIVATE_CONTEXT_CANARY',str(published))
        self.assertEqual(published['decisions'][0]['evidence'][0]['quote'],'原文')
        self.assertEqual(published['decisions'][0]['knowledge'][0]['character_id'],'甲')
        self.assertEqual(published['packet_sha256'],review['packet_sha256'])
        self.assertEqual(review,before)

    def test_output_cannot_overwrite_inputs_or_escape_runtime_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'source.txt';source.write_text('原书')
            for target in (source,root/'new',REPO/'experiments/escape'):
                with self.subTest(target=target),self.assertRaises(ValueError):
                    experiment.fresh_output(target)
            self.assertEqual(source.read_text(),'原书')
            self.assertFalse((root/'new').exists())


if __name__=='__main__':unittest.main()
