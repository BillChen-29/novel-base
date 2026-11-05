"""Synthetic contracts for source-bound stage-card replay, not model accuracy."""
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
spec = importlib.util.spec_from_file_location('stage_card_pilot', ROOT / 'experiments/stage-card-pilot/run_experiment.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class StageCardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        source = '# Source\n信息通过载体传递，读取之后再决定行动。'
        path = self.root / 'assets/motif_library/source.md'
        path.parent.mkdir(parents=True)
        path.write_text(source, encoding='utf-8')
        self.catalog = {'schema_version': 1, 'status': 'experimental_operationalization', 'motifs': []}
        for i in range(3):
            self.catalog['motifs'].append({
                'id': f'card_{i}', 'title': f'Card {i}', 'knowledge_kind': 'situation',
                'basis': 'authored_test', 'retrieval_text': f'RETRIEVAL_ONLY_{i} alpha beta',
                'source': {'path': 'assets/motif_library/source.md', 'sha256': hashlib.sha256(source.encode()).hexdigest(),
                           'evidence': [{'start': 0, 'end': len(source), 'quote': source}]},
                'roles': {'actor': 'character', 'focus': 'object'},
                'conditions': [{'id': name, 'kind': 'world_state', 'claim_template': '{actor} ' + name + ' {focus}'}
                               for name in ['held', 'unread', 'understood', 'pending']],
                'entry_conditions': [], 'stage_mode': 'alternatives',
                'stages': [{'id': 'unread', 'title': 'Unread', 'requires': ['held', 'unread'], 'chronological': []},
                           {'id': 'understood', 'title': 'Understood', 'requires': ['understood'], 'chronological': []}],
                'variants': [{'id': f'card_{i}_read', 'title': 'Read', 'from_stage': 'unread', 'requires': [], 'proposal': 'Read the existing carrier.'},
                             {'id': f'card_{i}_use', 'title': 'Use', 'from_stage': 'understood', 'requires': ['pending'], 'proposal': 'Use known contents in the pending task.'}],
                'operationalization_note': 'Synthetic protocol test.'})
        story = "阿澄拿着信。仍未打开。她继续看着纸页。🔑 'SELECT'"
        self.project = {'schema_version': 1, 'project_id': 'PRIVATE_PROJECT', 'title': 'PRIVATE_TITLE',
                        'pov_character': '阿澄', 'characters': ['阿澄'],
                        'goal': {'id': 'recover_and_investigate', 'description': 'PRIVATE_GOAL'},
                        'scenes': [{'id': 's1', 'order': 1, 'function': 'current', 'tension': 2,
                                    'present_characters': ['阿澄'], 'text': story}],
                        'facts': [{'id': 'base_1', 'text': 'PRIVATE_STATE 阿澄有一封未读的信。',
                                   'scene_id': 's1', 'quote': story[:6], 'known_by': ['阿澄']}], 'threads': []}
        self.fixtures = {'cases': [{'case_id': 'case-01', 'project': self.project,
                                    'bindings': {'actor': '阿澄', 'focus': 'PRIVATE_FOCUS'}}]}
        self.prepared = runner.prepare_cases(self.fixtures, self.catalog, self.root)
        self.reviews = {'reviews': []}
        for case in self.prepared['cases']:
            packet = case['packet']
            ref = {'scene_id': 's1', 'start': 0, 'end': 6, 'quote': story[:6]}
            decisions = []
            for candidate in packet['candidates']:
                status = 'supported' if candidate['fact_id'] == 'base_1' else 'insufficient_evidence'
                decisions.append({'fact_id': candidate['fact_id'], 'verdict': status, 'reason': 'PRIVATE_REASON',
                                  'epistemic_type': 'established' if status == 'supported' else 'uncertain',
                                  'evidence': [ref] if status == 'supported' else [],
                                  'knowledge': [{'character_id': '阿澄', 'verdict': status, 'reason': 'PRIVATE_KNOWLEDGE',
                                                 'evidence': [ref] if status == 'supported' else []}]})
            self.reviews['reviews'].append({'case_id': case['case_id'], 'review': {
                'schema_version': 1, 'project_id': packet['project_id'], 'project_sha256': packet['project_sha256'],
                'packet_sha256': packet['packet_sha256'], 'reviewer': {'kind': 'agent_review', 'name': 'test'},
                'decisions': decisions}})

    def condition(self, card, name, verdict='supported', pov='supported'):
        case = self.prepared['cases'][0]
        instance = next(x for x in case['project']['motif_annotations']['instances'] if x['motif_id'] == card)
        fact_id = instance['condition_facts'][name]
        decision = next(d for d in self.reviews['reviews'][0]['review']['decisions'] if d['fact_id'] == fact_id)
        quote = self.project['scenes'][0]['text'][:6]
        ref = {'scene_id': 's1', 'start': 0, 'end': 6, 'quote': quote}
        decision.update(verdict=verdict, epistemic_type='uncertain' if verdict == 'insufficient_evidence' else 'established',
                        evidence=[] if verdict == 'insufficient_evidence' else [ref],
                        knowledge=[{'character_id': '阿澄', 'verdict': pov, 'reason': 'PRIVATE_KNOWLEDGE',
                                    'evidence': [] if pov == 'insufficient_evidence' else [ref]}])
        return decision

    def inputs(self):
        return runner.prepare_embedding_inputs(self.prepared, self.reviews, self.catalog, self.root)

    def run_dir(self):
        bundle = self.inputs()
        directory = self.root / ('run-' + str(len(list(self.root.glob('run-*')))))
        directory.mkdir()
        runner.write_new(directory / 'dataset.json', bundle['dataset'])
        runner.write_new(directory / 'embedding-input.json', bundle['embedding_input'])
        items = bundle['embedding_input']['items']
        vectors = {item['id']: ([1, 0] if item['kind'] == 'document' and item['title'] == 'Card 0'
                                or item['kind'] == 'query' and item['text'].startswith('PRIVATE_STATE') else [0, 1])
                   for item in items}
        payload = {'schema_version': 1, 'model_sha256': runner.MODEL_SHA256, 'complete': True,
                   'dataset_sha256': runner.file_sha(directory / 'dataset.json'),
                   'input_sha256': runner.file_sha(directory / 'embedding-input.json'),
                   'total_inputs': len(items), 'dimensions': 2, 'vectors': vectors}
        runner.write_new(directory / 'embeddings.json', payload)
        return directory

    def evaluate(self, directory=None):
        return runner.evaluate_run(self.prepared, self.reviews, self.catalog, self.root, directory or self.run_dir())

    def test_prepare_shared_cards_and_source_bindings_without_mutation(self):
        original = copy.deepcopy((self.fixtures, self.catalog))
        self.assertEqual(len(self.prepared['cases']), 1)
        case = self.prepared['cases'][0]
        self.assertEqual(len(case['packet']['candidates']), 13)
        self.assertEqual(case['base_fact_ids'], ['base_1'])
        self.assertEqual({i['id'] for i in case['project']['motif_annotations']['instances']}, {'card_0', 'card_1', 'card_2'})
        self.assertEqual((self.fixtures, self.catalog), original)
        changed = copy.deepcopy(self.catalog)
        changed['motifs'][0]['source']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            runner.prepare_cases(self.fixtures, changed, self.root)

    def test_pending_unknown_or_false_withholds_but_supported_allows(self):
        self.condition('card_0', 'understood')
        for verdict in ('insufficient_evidence', 'contradicted', 'supported'):
            self.condition('card_0', 'pending', verdict)
            result = self.evaluate()
            ids = result['summary']['cases'][0]['pool_ready_variant_ids']
            self.assertEqual(ids, ['card_0_use'] if verdict == 'supported' else [])

    def test_read_then_use_does_not_repeat_completed_first_read(self):
        self.condition('card_0', 'held')
        self.condition('card_0', 'unread')
        first = self.evaluate()
        self.assertEqual(first['summary']['cases'][0]['pool_ready_variant_ids'], ['card_0_read'])
        self.condition('card_0', 'unread', 'contradicted')
        self.condition('card_0', 'understood')
        self.condition('card_0', 'pending')
        second = self.evaluate()
        self.assertEqual(second['summary']['cases'][0]['pool_ready_variant_ids'], ['card_0_use'])
        for route in second['cases'][0]['methods'].values():
            self.assertNotIn('card_0_read', [p['id'] for p in route['writer_packet']['proposals']])

    def test_state_queries_use_only_reviewed_pov_base_facts(self):
        self.condition('card_0', 'held')
        self.condition('card_0', 'unread')
        bundle = self.inputs()
        queries = bundle['dataset']['queries'][0]
        self.assertEqual(queries['state'], 'PRIVATE_STATE 阿澄有一封未读的信。')
        self.assertEqual(queries['raw'], self.project['scenes'][0]['text'])
        self.assertNotIn('held', queries['state'])
        self.assertNotIn('RETRIEVAL_ONLY', queries['state'])
        self.reviews['reviews'][0]['review']['decisions'][0]['knowledge'][0].update(verdict='insufficient_evidence', evidence=[])
        bundle = self.inputs()
        self.assertEqual(bundle['dataset']['queries'][0]['state'], '')
        result = self.evaluate()
        for name in ('bm25_state', 'vector_state'):
            self.assertEqual(result['cases'][0]['methods'][name]['ranked_card_ids'], [])
            self.assertEqual(result['cases'][0]['methods'][name]['writer_packet']['proposals'], [])

    def test_missed_positive_cannot_leak_from_full_pool_into_method(self):
        self.condition('card_0', 'held')
        self.condition('card_0', 'unread')
        result = self.evaluate()
        case = result['cases'][0]
        self.assertEqual(case['methods']['vector_raw']['ranked_card_ids'], ['card_1', 'card_2'])
        self.assertEqual(case['methods']['vector_raw']['writer_packet']['proposals'], [])
        self.assertEqual([p['id'] for p in case['methods']['vector_state']['writer_packet']['proposals']], ['card_0_read'])
        self.assertFalse(case['methods']['vector_state']['memory_write_allowed'])
        self.assertEqual(result['summary']['cases'][0]['methods']['vector_raw']['ready_card_recall'], 0)
        self.assertEqual(result['summary']['cases'][0]['methods']['vector_state']['ready_card_recall'], 1)

    def test_no_positive_null_recall_and_summary_contains_no_private_text(self):
        result = self.evaluate()
        for method in result['summary']['cases'][0]['methods'].values():
            self.assertIsNone(method['ready_card_recall'])
        summary = json.dumps(result['summary'], ensure_ascii=False)
        for secret in ['PRIVATE', '阿澄', 'RETRIEVAL_ONLY', 'SELECT', str(self.root)]:
            self.assertNotIn(secret, summary)

    def test_full_fact_and_knowledge_coverage_required(self):
        original = copy.deepcopy(self.reviews)
        self.reviews['reviews'][0]['review']['decisions'].pop()
        with self.assertRaisesRegex(ValueError, 'coverage'):
            self.inputs()
        self.reviews = copy.deepcopy(original)
        self.reviews['reviews'][0]['review']['decisions'][0]['knowledge'] = []
        with self.assertRaisesRegex(ValueError, 'coverage'):
            self.inputs()
        self.reviews = copy.deepcopy(original)
        self.reviews['reviews'][0]['review']['decisions'][0]['evidence'][0]['end'] = 999
        with self.assertRaises(ValueError):
            self.inputs()

    def test_same_prefix_other_project_rejects_old_review(self):
        fixtures = copy.deepcopy(self.fixtures)
        fixtures['cases'][0]['project']['project_id'] = 'OTHER_PROJECT'
        prepared = runner.prepare_cases(fixtures, self.catalog, self.root)
        with self.assertRaisesRegex(ValueError, 'review_binding'):
            runner.prepare_embedding_inputs(prepared, self.reviews, self.catalog, self.root)

    def test_prepared_tampering_and_bad_containers_rejected(self):
        prepared = copy.deepcopy(self.prepared)
        prepared['cases'][0]['base_fact_ids'].append('probe_0001')
        with self.assertRaises(ValueError):
            runner.prepare_embedding_inputs(prepared, self.reviews, self.catalog, self.root)
        for fixtures in (None, {}, {'cases': []}, {'cases': [None]}):
            with self.subTest(fixtures=fixtures), self.assertRaises(ValueError):
                runner.prepare_cases(fixtures, self.catalog, self.root)
        for field, value in [('case_id', '../secret'), ('bindings', None), ('project', None)]:
            fixtures = copy.deepcopy(self.fixtures)
            fixtures['cases'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                runner.prepare_cases(fixtures, self.catalog, self.root)

    def test_vector_and_exact_input_validation(self):
        for mutation in ('model', 'incomplete', 'zero', 'boolean', 'missing'):
            directory = self.run_dir()
            payload = runner.read(directory / 'embeddings.json')
            identity = next(iter(payload['vectors']))
            if mutation == 'model': payload['model_sha256'] = '0' * 64
            elif mutation == 'incomplete': payload['complete'] = False
            elif mutation == 'zero': payload['vectors'][identity] = [0, 0]
            elif mutation == 'boolean': payload['vectors'][identity] = [True, 1]
            else: payload['vectors'].pop(identity)
            (directory / 'embeddings.json').write_bytes(runner.encoded(payload))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.evaluate(directory)
        directory = self.run_dir()
        inputs = runner.read(directory / 'embedding-input.json')
        inputs['items'][0]['text'] += 'tamper'
        (directory / 'embedding-input.json').write_bytes(runner.encoded(inputs))
        with self.assertRaisesRegex(ValueError, 'input'):
            self.evaluate(directory)

    def test_fresh_runtime_output_only_and_exclusive_file_writes(self):
        with patch.object(runner, 'REPO', self.root):
            with self.assertRaises(ValueError): runner.fresh_dir(self.root / 'other')
            out = runner.fresh_dir(self.root / 'runtime-data/new')
            with self.assertRaises(ValueError): runner.fresh_dir(out)
            link = self.root / 'runtime-data/link'
            link.symlink_to(out, target_is_directory=True)
            with self.assertRaises(ValueError): runner.fresh_dir(link / 'escape')
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(runner.write_new, out / 'one.json', {'ok': True}) for _ in range(2)]
                self.assertEqual(sum(f.exception() is None for f in futures), 1)
            self.assertEqual(runner.read(out / 'one.json'), {'ok': True})

    def test_physical_target_cannot_bypass_linked_runtime_root(self):
        repo = self.root / 'linked-repo'
        outside = self.root / 'outside'
        repo.mkdir()
        outside.mkdir()
        (repo / 'runtime-data').symlink_to(outside, target_is_directory=True)
        with patch.object(runner, 'REPO', repo):
            with self.assertRaisesRegex(ValueError, 'runtime_symlink'):
                runner.fresh_dir(outside / 'new')
        self.assertFalse((outside / 'new').exists())

    def test_cli_prepare_inputs_evaluate_roundtrip(self):
        fixture_path, catalog_path, review_path = [self.root / name for name in ('fixtures.json', 'catalog.json', 'reviews.json')]
        for path, value in ((fixture_path, self.fixtures), (catalog_path, self.catalog), (review_path, self.reviews)):
            runner.write_new(path, value)
        runtime = self.root / 'runtime-data'
        shared = ['--catalog', str(catalog_path), '--repo-root', str(self.root)]
        with patch.object(runner, 'REPO', self.root), redirect_stdout(io.StringIO()):
            runner.main(['prepare', '--fixtures', str(fixture_path), '--output', str(runtime / 'prepared'), *shared])
            prepared_path = runtime / 'prepared/prepared.json'
            self.assertEqual(runner.read(prepared_path), self.prepared)
            runner.main(['inputs', '--prepared', str(prepared_path), '--reviews', str(review_path),
                         '--output', str(runtime / 'vectors'), *shared])
            synthetic = self.run_dir()
            self.assertEqual(runner.read(synthetic / 'embedding-input.json'), runner.read(runtime / 'vectors/embedding-input.json'))
            runner.write_new(runtime / 'vectors/embeddings.json', runner.read(synthetic / 'embeddings.json'))
            runner.main(['evaluate', '--prepared', str(prepared_path), '--reviews', str(review_path),
                         '--run-dir', str(runtime / 'vectors'), '--output', str(runtime / 'results'), *shared])
            summary = runner.read(runtime / 'results/summary.json')
            self.assertEqual(summary['case_count'], 1)
            self.assertEqual(summary['top_k'], 2)
            self.assertEqual(runner.read(runtime / 'results/results.json')['summary'], summary)

    def test_metadata_identifiers_uniqueness_and_nonfinite_json_rejected(self):
        for field, bad in [('id', '../PRIVATE'), ('retrieval_text', ''), ('basis', None), ('roles', {})]:
            catalog = copy.deepcopy(self.catalog)
            catalog['motifs'][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                runner.prepare_cases(self.fixtures, catalog, self.root)
        catalog = copy.deepcopy(self.catalog)
        catalog['motifs'][1]['variants'][0]['id'] = catalog['motifs'][0]['variants'][0]['id']
        with self.assertRaisesRegex(ValueError, 'duplicate_variant'):
            runner.prepare_cases(self.fixtures, catalog, self.root)
        fixtures = {'cases': [self.fixtures['cases'][0], copy.deepcopy(self.fixtures['cases'][0])]}
        with self.assertRaisesRegex(ValueError, 'duplicate_case'):
            runner.prepare_cases(fixtures, self.catalog, self.root)
        p = self.root / 'bad.json'
        p.write_text('{"bad": NaN}')
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            runner.read(p)


if __name__ == '__main__':
    unittest.main()
