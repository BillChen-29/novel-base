"""Runner contracts use synthetic review decisions and local test vectors."""
import copy
import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from runpy import run_path
import unittest

import test_recommendation_engine as engine_fixtures
import test_recommendation_vector_runner as vector_fixtures


ROOT = Path(__file__).resolve().parents[2]
budget = run_path(str(ROOT / 'experiments/recommendation-action-budget/run_experiment.py'))

# Captured from the unmodified vector runner using its two-revision test run.
GLOBAL_HASHES = {
    'bm25': ('b544065205ee2ea39d25317107f7658c6bcc8e7e9ea3b7a7e5a2e73119f35d86',
             '355f287f10ff1595a4ba833acb626c050922e732a810a96394089197313cf690'),
    'vector': ('35f108a989083b4ca694f0200e84b7aaa627477d95b34a165ec1dd72a8b952e9',
               'b0a7dc5f618f13e6e34bd0179c73d712d7f9345c658809dd16c1633aaed5df13'),
    'hybrid': ('22355c94e19ca8112653411224949d03dc846f6e866ae15076a3d54626c15d0d',
               '3688304cb4af43918647f7855fba86d2702827c28b74e44d84eb64e837c8edea'),
}


class ActionBudgetRunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = vector_fixtures.RunnerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare()
        self.fixture.add_vectors()

    def cli(self, mode, method, policy, reviews_path=None):
        args = [mode, '--run-dir', str(self.fixture.run_dir), '--method', method,
                '--candidate-policy', policy]
        if reviews_path is not None:
            args.extend(['--candidate-reviews', str(reviews_path)])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(budget['main'](args), 0)
        return output.getvalue().encode('utf-8')

    def reviews_for(self, candidates):
        return {'reviews': {
            row['case_id']: {item['id']: engine_fixtures.review(item['prepared']['packet'])
                             for item in row['request']['instances']}
            for row in candidates['cases']}}

    def test_global_cli_retains_original_candidate_and_replay_bytes(self):
        path = self.fixture.root / 'imported-reviews.json'
        for method, (candidate_hash, replay_hash) in GLOBAL_HASHES.items():
            with self.subTest(method=method):
                candidates = self.cli('candidates', method, 'global')
                self.assertEqual(hashlib.sha256(candidates).hexdigest(), candidate_hash)
                path.write_text(json.dumps(self.reviews_for(json.loads(candidates))), encoding='utf-8')
                replay = self.cli('replay', method, 'global', path)
                self.assertEqual(hashlib.sha256(replay).hexdigest(), replay_hash)

    def test_replay_rejects_null_reviews_without_emitting_candidates(self):
        path = self.fixture.root / 'null-reviews.json'
        path.write_text('null', encoding='utf-8')
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = budget['main'](['replay', '--run-dir', str(self.fixture.run_dir),
                '--method', 'bm25', '--candidate-policy', 'action_compatible',
                '--candidate-reviews', str(path)])
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(json.loads(error.getvalue())['error'], 'candidate_review_coverage')

    def test_compatible_replay_checks_acceptance_old_revision_and_read_only(self):
        directory = self.fixture.run_dir
        def snapshot():
            return {p.relative_to(directory): p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        before = snapshot()
        for method in GLOBAL_HASHES:
            with self.subTest(method=method):
                candidates = json.loads(self.cli('candidates', method, 'action_compatible'))
                reviews = self.reviews_for(candidates)
                path = self.fixture.root / 'imported-reviews.json'
                path.write_text(json.dumps(reviews), encoding='utf-8')
                result = json.loads(self.cli('replay', method, 'action_compatible', path))
                self.assertEqual(candidates['candidate_policy'], 'action_compatible')
                self.assertEqual(result['candidate_policy'], 'action_compatible')
                self.assertEqual([r['compatible_card_ids'] for r in result['results']], [['read'], ['read']])
                self.assertEqual(result['metrics'], {'cases': 2, 'accepted': 2, 'acceptance_preserved_facts': True,
                                 'cross_revision_checks': 1, 'cross_revision_rejected': 1})
                self.assertEqual([r['plan_count'] for r in result['results']], [1, 2])
                self.assertEqual([r['old_revision_acceptance_rejected'] for r in result['results']], [None, True])
        self.assertEqual(snapshot(), before)

    def test_replay_requires_exact_case_and_instance_coverage(self):
        run = budget['run']
        directory = self.fixture.run_dir
        kwargs = {'candidate_policy': 'action_compatible'}
        candidates = run(directory, 'bm25', **kwargs)
        reviews = self.reviews_for(candidates)
        for level, key, error in [('case', 'case_1', 'candidate_review_coverage'),
                                  ('instance', next(iter(reviews['reviews']['case_1'])), 'instance_review_coverage')]:
            for extra in (False, True):
                with self.subTest(level=level, extra=extra):
                    changed = copy.deepcopy(reviews)
                    target = changed['reviews'] if level == 'case' else changed['reviews']['case_1']
                    if extra:
                        target['unrequested'] = target[key]
                    else:
                        del target[key]
                    with self.assertRaisesRegex(ValueError, error):
                        run(directory, 'bm25', candidate_reviews=changed, **kwargs)


if __name__ == '__main__':
    unittest.main()
