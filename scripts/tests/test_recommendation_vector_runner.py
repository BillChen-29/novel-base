"""Runner contracts use synthetic reviews/vectors, never semantic accuracy labels."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_recommendation_engine as fixtures
from recommendation_retrieval import DIMENSIONS, INPUT_FORMAT, MODEL_SHA256, QMD_VERSION, RUNTIME_VERSION

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('recommendation_vector_runner',
    ROOT / 'experiments/recommendation-vector/run_experiment.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        source = fixtures.EngineTests()
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.root = source.root.resolve()
        self.catalog = source.catalog
        first = {'case_id': 'case_1', 'episode_id': 'episode', 'source': source.project,
                 'new_scene': source.project['scenes'][0], 'annotations': source.annotations,
                 'accept_action': 'read_note'}
        second = copy.deepcopy(first)
        scene = dict(first['new_scene'], id='s2', order=2, text='林仍拿着纸条，尚未读取。')
        second.update(case_id='case_2', new_scene=scene)
        second['source']['scenes'].append(scene)
        self.fixtures = {'schema_version': 1, 'cases': [first, second]}
        sessions, reviews = {}, {}
        for row in self.fixtures['cases']:
            session = runner.advance(sessions, row)
            request = runner.prepare_state(session, row['annotations'])
            reviews[row['case_id']] = fixtures.review(request['packet'])
            sessions[row['episode_id']] = runner.review_state(session, request, reviews[row['case_id']])
        self.reviews = {'reviews': reviews}
        self.run_dir = self.root / 'runtime-data/run'

    def prepare(self, output=None, cases=None, reviews=None):
        return runner.prepare_run(cases or self.fixtures, reviews or self.reviews,
                                  self.catalog, self.root, output or self.run_dir)

    def candidate_reviews(self, method='bm25'):
        result = runner.run(self.run_dir, method)
        return {'reviews': {row['case_id']: {x['id']: fixtures.review(x['prepared']['packet'])
            for x in row['request']['instances']} for row in result['cases']}}

    def add_vectors(self):
        for row in self.fixtures['cases']:
            directory = self.run_dir / row['case_id']
            inputs = runner.read(directory / 'embedding-input.json')
            vectors = {x['id']: [1.0] + [0.0] * (DIMENSIONS - 1) for x in inputs['items']}
            payload = {'schema_version': 1, 'complete': True, 'dimensions': DIMENSIONS,
                'dataset_sha256': hashlib.sha256((directory / 'dataset.json').read_bytes()).hexdigest(),
                'input_sha256': hashlib.sha256((directory / 'embedding-input.json').read_bytes()).hexdigest(),
                'model_sha256': MODEL_SHA256, 'prefix': INPUT_FORMAT,
                'qmd_version': QMD_VERSION, 'runtime_version': RUNTIME_VERSION,
                'total_inputs': len(vectors), 'vectors': vectors}
            runner.write_new(directory / 'embeddings.json', payload)

    def test_prepare_exact_bytes_and_independent_snapshots(self):
        result = self.prepare()
        self.assertEqual(len(result['cases']), 2)
        for row in self.fixtures['cases']:
            directory = self.run_dir / row['case_id']
            data = (directory / 'dataset.json').read_bytes()
            self.assertEqual(data, runner.encoded(runner.read(directory / 'dataset.json')))
            self.assertEqual(runner.read(directory / 'embedding-input.json')['dataset_sha256'],
                             hashlib.sha256(data).hexdigest())
        self.fixtures['cases'][0]['source']['title'] = 'mutated original'
        self.assertEqual(len(runner.run(self.run_dir, 'bm25')['cases']), 2)

    def test_all_validation_precedes_output_creation(self):
        invalid = copy.deepcopy(self.fixtures)
        invalid['cases'][1]['source']['title'] = 'invalid append'
        with self.assertRaises(ValueError):
            self.prepare(cases=invalid)
        self.assertFalse(self.run_dir.exists())
        invalid = copy.deepcopy(self.fixtures)
        del invalid['cases'][1]['accept_action']
        with self.assertRaises(ValueError):
            self.prepare(cases=invalid)
        self.assertFalse(self.run_dir.exists())
        invalid_reviews = copy.deepcopy(self.reviews)
        invalid_reviews['reviews']['case_2']['packet_sha256'] = 'stale'
        with self.assertRaises(ValueError):
            self.prepare(reviews=invalid_reviews)
        self.assertFalse(self.run_dir.exists())

    def test_invalid_duplicate_and_traversal_case_ids(self):
        for cid in ('case_1', '../escape', 'UPPER', 'a' * 81, ''):
            invalid = copy.deepcopy(self.fixtures)
            invalid['cases'][1]['case_id'] = cid
            with self.assertRaises(ValueError):
                self.prepare(cases=invalid)
            self.assertFalse(self.run_dir.exists())

    def test_fresh_directory_and_exclusive_file_creation(self):
        self.prepare()
        for destination in (self.run_dir, self.root / 'runtime-data', self.root / 'elsewhere',
                            self.root / 'runtime-data/../escape'):
            with self.assertRaises(ValueError):
                runner.fresh_dir(destination, self.root)
        with self.assertRaises(FileExistsError):
            runner.write_new(self.run_dir / 'catalog.json', {})
        target = self.root / 'runtime-data/concurrent'
        def claim(_):
            try:
                runner.fresh_dir(target, self.root)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(claim, range(2))), [False, True])

    def test_symlink_output_ancestor_and_runtime_root_rejected(self):
        (self.root / 'runtime-data').mkdir()
        (self.root / 'runtime-data/link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.prepare(output=self.root / 'runtime-data/link/escape')
        (self.root / 'root-link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            runner.fresh_dir(self.root / 'root-link/runtime-data/escape', self.root / 'root-link')
        (self.root / 'runtime-data/link').unlink()
        (self.root / 'runtime-data').rmdir()
        (self.root / 'runtime-data').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.prepare()

    def test_missing_vectors_never_fall_back(self):
        self.prepare()
        self.assertEqual(len(runner.run(self.run_dir, 'bm25')['cases']), 2)
        for method in ('vector', 'hybrid'):
            with self.assertRaises(OSError):
                runner.run(self.run_dir, method)

    def test_stale_snapshot_artifact_and_model_rejected(self):
        self.prepare()
        self.add_vectors()
        path = self.run_dir / 'case_1/embeddings.json'
        original = runner.read(path)
        for field in ('model_sha256', 'input_sha256', 'dataset_sha256'):
            changed = dict(original, **{field: 'stale'})
            path.write_bytes(runner.encoded(changed))
            with self.assertRaises(ValueError):
                runner.run(self.run_dir, 'vector')
        path.write_bytes(runner.encoded(original))
        dataset = self.run_dir / 'case_1/dataset.json'
        original_dataset = runner.read(dataset)
        dataset.write_bytes(runner.encoded(dict(original_dataset, query='stale query')))
        with self.assertRaisesRegex(ValueError, 'dataset_mismatch'):
            runner.run(self.run_dir, 'vector')
        dataset.write_bytes(runner.encoded(original_dataset))
        catalog = self.run_dir / 'catalog.json'
        catalog.write_bytes(runner.encoded({}))
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            runner.run(self.run_dir, 'bm25')

    def test_replay_accept_append_protocol_and_read_only(self):
        self.prepare()
        self.add_vectors()
        before = {p.relative_to(self.run_dir): p.read_bytes() for p in self.run_dir.rglob('*.json')}
        states = []
        for method in ('bm25', 'vector', 'hybrid'):
            replay = runner.run(self.run_dir, method, candidate_reviews=self.candidate_reviews(method))
            states.append([r['state_sha256'] for r in replay['results']])
            self.assertEqual([r['plan_count'] for r in replay['results']], [1, 2])
            self.assertTrue(all(r['acceptance_preserved_facts'] for r in replay['results']))
            self.assertTrue(replay['results'][1]['old_revision_acceptance_rejected'])
            self.assertEqual(replay['sessions']['episode']['revision'], 2)
        self.assertTrue(all(s == states[0] for s in states))
        self.assertEqual(before, {p.relative_to(self.run_dir): p.read_bytes() for p in self.run_dir.rglob('*.json')})

    def test_candidate_review_case_and_instance_coverage(self):
        self.prepare()
        reviews = self.candidate_reviews()
        reviews['reviews']['extra'] = {}
        with self.assertRaisesRegex(ValueError, 'coverage'):
            runner.run(self.run_dir, 'bm25', candidate_reviews=reviews)
        del reviews['reviews']['extra']
        reviews['reviews']['case_1'] = {}
        with self.assertRaisesRegex(ValueError, 'coverage'):
            runner.run(self.run_dir, 'bm25', candidate_reviews=reviews)


if __name__ == '__main__':
    unittest.main()
