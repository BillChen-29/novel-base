import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from knowledge_discovery import build_index, freeze_prefix
from semantic_review import _digest

spec = importlib.util.spec_from_file_location('discovery_experiment', ROOT / 'experiments/candidate-discovery/run_experiment.py')
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


class DiscoveryExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.path = 'assets/motif_library/test.md'
        asset = self.root / self.path
        asset.parent.mkdir(parents=True)
        asset.write_text('# 信息传递\n读完信后，角色才知道信中内容。\n', encoding='utf-8')
        prefix = '林读完了信。信上写着松果。'
        self.snapshot = freeze_prefix('public-case', prefix, len(prefix), '林')
        self.index = build_index(self.root, [self.path])
        document = self.index['documents'][0]
        analysis = {'schema_version': 1, 'snapshot_sha256': self.snapshot['snapshot_sha256'],
                    'queries': [{'text': '读完信后知道内容', 'evidence': [self.ref(self.snapshot['text'], '林读完了信。')]}]}
        manifest = {'documents': [{'path': self.path, 'sha256': document['source_sha256']}]}
        self.discovered = experiment.discover_cases({'cases': [{'case_id': 'public-case', 'snapshot': self.snapshot}]},
                                                    {'cases': [{'case_id': 'public-case', 'analysis': analysis}]},
                                                    manifest, self.root)
        self.packet = self.discovered['cases'][0]['review_packet']
        source_ref = self.ref(document['text'], '读完信后，角色才知道信中内容。')
        story_ref = self.ref(self.snapshot['text'], '林读完了信。')
        self.review = {'schema_version': 1, 'packet_sha256': self.packet['packet_sha256'],
                       'reviewer': {'kind': 'agent_review', 'name': 'synthetic-test'}, 'decisions': [{
                           'source_path': self.path, 'reason': 'TEST_PRIVATE_REASON', 'operation': '根据已读内容规划行动',
                           'knowledge_evidence': [source_ref],
                           'conditions': [{'claim': '林已读信', 'verdict': 'supported', 'epistemic_type': 'established',
                                           'story_evidence': [story_ref], 'knowledge_evidence': [source_ref]}],
                           'pov': {'verdict': 'supported', 'reason': '林亲自阅读', 'evidence': [story_ref]}}]}

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def ref(source, quote):
        start = source.index(quote)
        return {'start': start, 'end': start + len(quote), 'quote': quote}

    def result(self):
        return experiment.apply_candidate_review(self.packet, self.review)

    def test_supported_known_condition_yields_proposal_without_mutation(self):
        before = copy.deepcopy((self.packet, self.review))
        result = self.result()
        self.assertEqual(result['audit'][0]['status'], 'eligible')
        self.assertEqual(result['proposals'][0]['state'], 'proposed_not_history')
        self.assertEqual(result['audit'][0]['assessment_scope'], 'local_operation')
        self.assertEqual(result['audit'][0]['motif_completion'], 'not_assessed')
        self.assertEqual(before, (self.packet, self.review))

    def test_unknown_and_missing_review_abstain(self):
        self.review['decisions'][0]['conditions'][0]['verdict'] = 'insufficient_evidence'
        self.assertEqual(self.result()['proposals'], [])
        self.review['decisions'] = []
        self.assertEqual(self.result()['audit'][0]['reason'], 'missing_review')
        self.assertEqual(self.result()['proposals'], [])

    def test_reported_condition_not_established(self):
        self.review['decisions'][0]['conditions'][0]['epistemic_type'] = 'reported'
        self.assertEqual(self.result()['audit'][0]['status'], 'needs_evidence')

    def test_unknown_pov_cannot_use_world_fact(self):
        self.review['decisions'][0]['pov']['verdict'] = 'insufficient_evidence'
        self.assertEqual(self.result()['proposals'], [])

    def test_contradiction_blocks(self):
        self.review['decisions'][0]['conditions'][0]['verdict'] = 'contradicted'
        self.assertEqual(self.result()['audit'][0]['status'], 'blocked')

    def test_null_reviews_are_clean_validation_errors(self):
        with self.assertRaises(ValueError):
            experiment.apply_candidate_review(self.packet, None)
        self.review['reviewer'] = None
        with self.assertRaises(ValueError):
            self.result()

    def test_changed_prefix_and_stale_review_rejected(self):
        self.packet['snapshot']['text'] += '密封后文'
        with self.assertRaises(ValueError):
            self.result()

    def test_bad_evidence_rejected(self):
        for ref_key in ('story_evidence', 'knowledge_evidence'):
            with self.subTest(ref_key=ref_key):
                changed = copy.deepcopy(self.review)
                changed['decisions'][0]['conditions'][0][ref_key][0]['end'] += 1000
                with self.assertRaises(ValueError):
                    experiment.apply_candidate_review(self.packet, changed)

    def test_self_consistent_hash_cannot_override_cutoff_contract(self):
        self.packet['snapshot']['cutoff_offset'] = 1
        self.packet['snapshot']['snapshot_sha256'] = _digest({k: v for k, v in self.packet['snapshot'].items() if k != 'snapshot_sha256'})
        self.packet['packet_sha256'] = _digest({k: v for k, v in self.packet.items() if k != 'packet_sha256'})
        self.review['packet_sha256'] = self.packet['packet_sha256']
        with self.assertRaises(ValueError): self.result()

    def test_self_consistent_packet_rejects_private_or_traversing_paths(self):
        for path in ('/Users/private/book.txt', 'assets/../book.md', 'assets\\book.md'):
            with self.subTest(path=path):
                packet, review = copy.deepcopy(self.packet), copy.deepcopy(self.review)
                packet['documents'][0]['source_path'] = path
                packet['packet_sha256'] = _digest({k: v for k, v in packet.items() if k != 'packet_sha256'})
                review['packet_sha256'] = packet['packet_sha256']
                review['decisions'][0]['source_path'] = path
                with self.assertRaises(ValueError): experiment.apply_candidate_review(packet, review)

    def test_supported_condition_requires_exact_story_quote(self):
        self.review['decisions'][0]['conditions'][0]['story_evidence'][0]['quote'] = 'NOT_IN_SOURCE'
        with self.assertRaises(ValueError):
            self.result()

    def test_duplicate_and_extra_documents_rejected(self):
        self.review['decisions'].append(copy.deepcopy(self.review['decisions'][0]))
        with self.assertRaises(ValueError):
            self.result()
        self.review['decisions'].pop()
        self.review['decisions'][0]['source_path'] = 'assets/motif_library/other.md'
        with self.assertRaises(ValueError):
            self.result()

    def test_ranking_cannot_change_after_review(self):
        self.discovered['cases'][0]['discovery']['methods']['raw_prefix'] = []
        with self.assertRaisesRegex(ValueError, 'ranking_changed'):
            experiment.evaluate_cases(self.discovered, {'cases': [{'case_id': 'public-case', 'review': self.review}]})

    def test_null_imported_packet_is_clean_validation_error(self):
        self.discovered['cases'][0]['review_packet'] = None
        with self.assertRaisesRegex(ValueError, 'invalid_packet'):
            experiment.evaluate_cases(self.discovered, {'cases': [{'case_id': 'public-case', 'review': self.review}]})

    def test_full_knowledge_document_and_public_projection(self):
        self.assertEqual(self.packet['documents'][0]['text'], self.index['documents'][0]['text'])
        results = experiment.evaluate_cases(self.discovered, {'cases': [{'case_id': 'public-case', 'review': self.review}]})
        summary = json.dumps(experiment.public_summary(results), ensure_ascii=False)
        for private in ('TEST_PRIVATE_REASON', '松果', '林读完了信', '根据已读内容规划行动', self.temp.name):
            self.assertNotIn(private, summary)

    def test_frozen_corpus_change_rejected(self):
        asset = self.root / self.path
        asset.write_text(asset.read_text() + '改变规则')
        with self.assertRaisesRegex(ValueError, 'frozen_corpus_changed'):
            experiment.discover_cases({'cases': [{'case_id': 'public-case', 'snapshot': self.snapshot}]},
                                      {'cases': [{'case_id': 'public-case', 'analysis': None}]},
                                      {'documents': [{'path': self.path, 'sha256': self.index['documents'][0]['source_sha256']}]}, self.root)

    def test_fresh_output_blocks_existing_and_symlink(self):
        old_repo = experiment.REPO
        experiment.REPO = self.root
        try:
            valid = self.root / 'runtime-data' / 'new'
            experiment.fresh_dir(valid)
            with self.assertRaises(ValueError): experiment.fresh_dir(valid)
            with self.assertRaises(ValueError): experiment.fresh_dir(self.root / 'assets' / 'other')
            (self.root / 'runtime-data' / 'link').symlink_to(self.root, target_is_directory=True)
            with self.assertRaises(ValueError): experiment.fresh_dir(self.root / 'runtime-data' / 'link' / 'outside')
        finally:
            experiment.REPO = old_repo

    def test_bm25_scores_are_reproducible_across_python_hash_seeds(self):
        code = (
            'import sys,json;sys.path.insert(0,' + repr(str(ROOT / 'scripts')) + ');'
            'from retrieval_pilot import bm25_rank;'
            'terms=["word"+str(i) for i in range(60)];'
            'chunks=[{"chunk_id":str(j),"source_path":"assets/"+str(j)+".md",'
            '"text":" ".join(t for i,t in enumerate(terms) for n in range((i*7+j*3)%(j+4)))} for j in range(9)];'
            'print(json.dumps(bm25_rank(" ".join(terms),chunks),sort_keys=True))'
        )
        outputs = [subprocess.check_output([sys.executable, '-c', code],
                   env=dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE='1'), text=True)
                   for seed in ('1', '2', '3')]
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])


if __name__ == '__main__':
    unittest.main()
