"""Synthetic replay and evidence contracts; not semantic/model-quality scores."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('typed_vector_experiment', ROOT / 'experiments/typed-vector-discovery/run_experiment.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from knowledge_discovery import freeze_prefix


class TypedExperimentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.docs = {'assets/motif_library/a.md': '# A\nalpha 被禁止，仍然阅读。',
                     'assets/technique_library/_scenarios/b.md': '# B\nbeta 得到信息。',
                     'assets/technique_library/c.md': '# C\ngamma 句式。'}
        for path, content in self.docs.items():
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
        self.manifest = {'schema_version': 1, 'documents': [
            {'path': path, 'sha256': hashlib.sha256(content.encode()).hexdigest(),
             'title': content.splitlines()[0][2:], 'kind': ('motif' if '/motif_' in path else 'scenario' if '/_scenarios/' in path else 'technique')}
            for path, content in sorted(self.docs.items())]}
        story = 'PRIVATE_PREFIX 阿澄阅读了信。🔑'
        snapshot = freeze_prefix('PRIVATE_PROJECT', story, len(story), 'PRIVATE_POV')
        self.cases = [{'case_id': 'case-01', 'snapshot': snapshot, 'analysis': {
            'schema_version': 1, 'snapshot_sha256': snapshot['snapshot_sha256'],
            'queries': [{'text': 'PRIVATE_QUERY alpha beta', 'evidence': [{'start': 0, 'end': len(story), 'quote': story}]}]}}]
        self.run = self.root / 'runtime-data/run'
        with patch.object(runner, 'REPO', self.root):
            runner.prepare_run(self.cases, self.root, self.manifest, self.run)
        dataset = runner.read(self.run / 'dataset.json')
        inputs = runner.read(self.run / 'embedding-input.json')
        embeddings = {'schema_version': 1, 'complete': True, 'dimensions': 2,
                      'dataset_sha256': runner.file_sha(self.run / 'dataset.json'),
                      'input_sha256': runner.file_sha(self.run / 'embedding-input.json'),
                      'model_sha256': runner.MODEL_SHA256,
                      'total_inputs': len(inputs['items']),
                      'vectors': {item['id']: [1.0, .5] for item in inputs['items']}}
        runner.write_new(self.run / 'embeddings.json', embeddings)
        self.packets = runner.read(self.run / 'review-input.json')
        self.reviews = {'cases': []}
        for case in self.packets['cases']:
            packet = case['packet']
            decisions = []
            for document in packet['documents']:
                decisions.append({'source_path': document['source_path'], 'match_level': 'insufficient_evidence',
                    'matched_structure': 'PRIVATE_RELATION', 'reason': 'PRIVATE_REASON',
                    'story_evidence': [], 'knowledge_evidence': [{'start': 0, 'end': 3, 'quote': document['text'][:3]}],
                    'missing_conditions': ['PRIVATE_MISSING'],
                    'pov': {'verdict': 'insufficient_evidence', 'reason': 'PRIVATE_POV_REASON', 'evidence': []},
                    'next_transition': None})
            self.reviews['cases'].append({'case_id': case['case_id'], 'review': {
                'schema_version': 1, 'packet_sha256': packet['packet_sha256'],
                'reviewer': {'kind': 'agent_review', 'name': 'PRIVATE_REVIEWER'}, 'decisions': decisions}})

    def evaluate(self, reviews=None):
        return runner.evaluate_run(self.run, self.reviews if reviews is None else reviews, self.root, self.manifest)

    def positive(self, level='current_structure', plan='PRIVATE_PLAN'):
        decision = self.reviews['cases'][0]['review']['decisions'][0]
        story = self.cases[0]['snapshot']['text']
        ref = {'start': 0, 'end': len(story), 'quote': story}
        decision.update(match_level=level, story_evidence=[ref], next_transition=plan,
                        missing_conditions=[] if level == 'current_structure' else ['missing wider mechanism'])
        decision['pov'] = {'verdict': 'supported', 'reason': 'direct perception', 'evidence': [ref]}
        return decision

    def overwrite(self, name, value):
        (self.run / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def test_prepare_reconstructs_packet_and_embedding_envelope(self):
        dataset = runner.read(self.run / 'dataset.json')
        self.assertEqual(runner.make_review_input(dataset), self.packets)
        self.assertEqual(len(self.packets['cases'][0]['packet']['documents']), 2)
        inputs = runner.read(self.run / 'embedding-input.json')
        self.assertEqual(inputs['dataset_sha256'], runner.file_sha(self.run / 'dataset.json'))
        self.assertIn(self.cases[0]['snapshot']['text'], [x['text'] for x in inputs['items']])

    def test_zero_positive_is_unknown_recall_not_zero_and_all_methods_evaluated(self):
        result = self.evaluate()
        case = result['summary']['cases'][0]
        self.assertEqual(case['positive_count'], 0)
        self.assertEqual(len(case['methods']), 6)
        for method in case['methods'].values():
            self.assertIsNone(method['plot']['recall'])
            self.assertEqual(method['plot']['unknown_count'], method['plot']['reviewed_plot_count'])
            self.assertEqual(method['plot']['contradicted_count'], 0)
        self.assertEqual(case['methods']['vector_raw']['global']['unassessed_count'], 1)
        self.assertEqual(case['methods']['vector_raw']['plot']['unknown_count'], 2)

    def test_fit_and_ready_proposal_are_separate_and_summary_has_no_private_strings(self):
        self.positive(plan=None)
        result = self.evaluate()
        case = result['summary']['cases'][0]
        self.assertEqual((case['positive_count'], case['proposal_ready_count']), (1, 0))
        for method in case['methods'].values():
            self.assertEqual(method['plot']['current_structure_hits'], 1)
            self.assertEqual(method['plot']['recall'], 1)
            self.assertEqual(method['plot']['proposal_ready_hits'], 0)
        summary = json.dumps(result['summary'], ensure_ascii=False)
        self.assertNotIn('PRIVATE_', summary)
        self.assertNotIn(str(self.root), summary)
        self.assertNotIn('quote', summary)

    def test_fragment_and_pov_gate_are_preserved(self):
        decision = self.positive('specific_fragment')
        result = self.evaluate()
        self.assertEqual(result['summary']['cases'][0]['methods']['vector_raw']['plot']['specific_fragment_hits'], 1)
        self.assertEqual(result['summary']['cases'][0]['proposal_ready_count'], 1)
        decision['pov']['verdict'] = 'insufficient_evidence'
        decision['next_transition'] = None
        result = self.evaluate()
        self.assertEqual(result['summary']['cases'][0]['positive_count'], 0)
        self.assertEqual(result['summary']['cases'][0]['methods']['vector_raw']['plot']['pov_unusable_count'], 1)

    def test_contradiction_stays_distinct_from_unknown_and_is_not_a_proposal(self):
        decision = self.positive(plan=None)
        decision['match_level'] = 'contradicted'
        result = self.evaluate()
        summary = result['summary']['cases'][0]
        self.assertEqual(summary['positive_count'], 0)
        self.assertEqual(summary['methods']['vector_raw']['plot']['contradicted_count'], 1)
        self.assertEqual(summary['methods']['vector_raw']['plot']['unknown_count'], 1)
        self.assertEqual(result['assessed_pool_proposals']['case-01'], [])

    def test_retrieved_proposals_cannot_leak_positive_full_pool_omissions(self):
        self.positive(plan='PRIVATE_PLAN')
        initial = self.evaluate()
        positive_path = self.reviews['cases'][0]['review']['decisions'][0]['source_path']
        rankings = copy.deepcopy(initial['rankings'])
        for method in rankings['cases'][0]['methods'].values():
            method['global'] = [hit for hit in method['global'] if hit['source_path'] != positive_path]
            method['by_type']['plot'] = [hit for hit in method['by_type']['plot'] if hit['source_path'] != positive_path]
        with patch.object(runner, 'rank_typed', return_value=rankings):
            result = self.evaluate()
        self.assertEqual(len(result['assessed_pool_proposals']['case-01']), 1)
        for method in result['retrieved_proposals_by_method']['case-01'].values():
            self.assertEqual(method, {'global': [], 'plot': []})
        for method in initial['retrieved_proposals_by_method']['case-01'].values():
            for proposals in method.values():
                for proposal in proposals:
                    self.assertEqual(proposal['source_path'], positive_path)
                    self.assertFalse(proposal['memory_write_allowed'])

    def test_cli_prepare_and_evaluate_roundtrip(self):
        cases_path, manifest_path, reviews_path = [self.root / name for name in ('cases.json', 'manifest.json', 'reviews.json')]
        for path, value in ((cases_path, {'cases': self.cases}), (manifest_path, self.manifest), (reviews_path, self.reviews)):
            runner.write_new(path, value)
        new_run, results = self.root / 'runtime-data/cli-run', self.root / 'runtime-data/cli-results'
        common = ['--repo-root', str(self.root), '--manifest', str(manifest_path)]
        with patch.object(runner, 'REPO', self.root), redirect_stdout(io.StringIO()):
            runner.main(['prepare', '--cases', str(cases_path), '--output', str(new_run)] + common)
            runner.write_new(new_run / 'embeddings.json', runner.read(self.run / 'embeddings.json'))
            runner.main(['evaluate', '--run-dir', str(new_run), '--reviews', str(reviews_path), '--output', str(results)] + common)
        self.assertEqual(runner.read(results / 'summary.json'), self.evaluate()['summary'])
        self.assertEqual(runner.read(results / 'results.json')['summary'], runner.read(results / 'summary.json'))

    def test_complete_unique_coverage_and_packet_binding_are_required(self):
        mutations = [lambda r: r['cases'][0]['review']['decisions'].pop(),
                     lambda r: r['cases'][0]['review']['decisions'].append(r['cases'][0]['review']['decisions'][0]),
                     lambda r: r['cases'].append(r['cases'][0]),
                     lambda r: r['cases'][0]['review'].update(packet_sha256='0' * 64)]
        for mutation in mutations:
            reviews = copy.deepcopy(self.reviews)
            mutation(reviews)
            with self.assertRaises(ValueError):
                self.evaluate(reviews)

    def test_exact_evidence_offsets_and_positive_conditions_enforced(self):
        self.positive('specific_fragment')
        mutations = [lambda d: d['story_evidence'][0].update(start=True),
                     lambda d: d['story_evidence'][0].update(end=9999),
                     lambda d: d['knowledge_evidence'][0].update(quote='not source'),
                     lambda d: d.update(story_evidence=[]),
                     lambda d: d.update(missing_conditions=[]),
                     lambda d: d['pov'].update(evidence=[]),
                     lambda d: d.update(match_level='insufficient_evidence')]
        for mutation in mutations:
            reviews = copy.deepcopy(self.reviews)
            mutation(reviews['cases'][0]['review']['decisions'][0])
            with self.assertRaises(ValueError):
                self.evaluate(reviews)

    def test_invalid_review_types_shapes_and_empty_text_fail_cleanly(self):
        for reviews in (None, [], {}, {'cases': []}, {'cases': [None]}):
            with self.subTest(reviews=reviews), self.assertRaises(ValueError):
                runner.evaluate_run(self.run, reviews, self.root, self.manifest)
        for field, value in [('source_path', []), ('match_level', None), ('reason', ''),
                             ('missing_conditions', 'x'), ('pov', None), ('next_transition', False)]:
            reviews = copy.deepcopy(self.reviews)
            reviews['cases'][0]['review']['decisions'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.evaluate(reviews)

    def test_changed_input_even_with_updated_embedding_hash_is_rejected(self):
        inputs = runner.read(self.run / 'embedding-input.json')
        inputs['items'][0]['text'] += 'tamper'
        self.overwrite('embedding-input.json', inputs)
        payload = runner.read(self.run / 'embeddings.json')
        payload['input_sha256'] = runner.file_sha(self.run / 'embedding-input.json')
        self.overwrite('embeddings.json', payload)
        with self.assertRaisesRegex(ValueError, 'embedding_input'):
            self.evaluate()

    def test_wrong_model_or_changed_review_packet_is_rejected(self):
        payload = runner.read(self.run / 'embeddings.json')
        original = copy.deepcopy(payload)
        payload['model_sha256'] = '0' * 64
        self.overwrite('embeddings.json', payload)
        with self.assertRaisesRegex(ValueError, 'model'):
            self.evaluate()
        self.overwrite('embeddings.json', original)
        packet = copy.deepcopy(self.packets)
        packet['cases'][0]['packet']['protocol']['scope'] = 'tamper'
        self.overwrite('review-input.json', packet)
        with self.assertRaisesRegex(ValueError, 'review_input'):
            self.evaluate()

    def test_changed_corpus_and_nonanonymous_case_id_are_rejected(self):
        source = self.root / next(iter(self.docs))
        source.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'corpus'):
            self.evaluate()
        cases = copy.deepcopy(self.cases)
        cases[0]['case_id'] = 'PRIVATE_PERSON'
        with self.assertRaises(ValueError):
            runner.prepare_run(cases, self.root, self.manifest, self.root / 'runtime-data/fail')

    def test_fresh_output_rejects_existing_outside_symlink_and_concurrent_claims(self):
        with patch.object(runner, 'REPO', self.root):
            for target in (self.run, self.root / 'elsewhere', self.root / 'runtime-data'):
                with self.assertRaises(ValueError):
                    runner.fresh_dir(target)
            link = self.root / 'runtime-data/link'
            link.symlink_to(self.root, target_is_directory=True)
            with self.assertRaises(ValueError):
                runner.fresh_dir(link / 'escape')
            target = self.root / 'runtime-data/parallel'
            def claim(_):
                try:
                    runner.fresh_dir(target)
                    return True
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(claim, range(2))), [False, True])
        with self.assertRaises(FileExistsError):
            runner.write_new(self.run / 'dataset.json', {})


if __name__ == '__main__':
    unittest.main()
