"""Synthetic-vector capability/regression contracts; these are not model evals."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge_discovery import build_index, freeze_prefix
from retrieval_pilot import bm25_rank, collapse_documents, rrf_fuse
from typed_knowledge_discovery import prepare_embedding_dataset, rank_typed


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class TypedKnowledgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = {
            'assets/technique_library/a.md': '# A\nalpha copper\n## More\nalpha lock\n',
            'assets/style_library/b.md': '# B\nbeta mirror\n',
            'assets/motif_library/c.md': '# C\ngamma alpha\n',
            'assets/technique_library/_scenarios/d.md': '# D\ndelta beta\n',
            'assets/pacing/e.md': '# E\nepsilon rhythm\n',
            'assets/character_archetypes/f.md': '# F\nzeta person\n',
        }
        for name, text in self.sources.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        self.index = build_index(self.root, list(self.sources))
        self.raw = 'alpha 在雨夜看见铜钥匙。🔑 SELECT \'--'
        self.snapshot = freeze_prefix('项目一', self.raw, len(self.raw), '阿澄')
        self.analysis = {'schema_version': 1, 'snapshot_sha256': self.snapshot['snapshot_sha256'],
                         'queries': [{'text': query, 'evidence': [{'start': 0, 'end': len(self.raw),
                                                                  'quote': self.raw}]}
                                     for query in ('beta', 'epsilon')]}
        self.cases = [{'case_id': 'case-一', 'snapshot': self.snapshot, 'analysis': self.analysis}]
        self.prepared = prepare_embedding_dataset(self.index, self.cases)
        self.dataset = self.prepared['dataset']
        self.dataset_hash = digest(self.dataset)
        self.input_hash = digest({'schema_version': 1, 'dataset_sha256': self.dataset_hash,
                                  'items': self.prepared['items']})
        directions = {'A': [1, 0], 'B': [.9, .1], 'C': [.7, .3], 'D': [.3, .7],
                      'E': [0, 1], 'F': [-1, 0]}
        self.payload = {'schema_version': 1, 'complete': True, 'dimensions': 2,
                        'dataset_sha256': self.dataset_hash, 'input_sha256': self.input_hash,
                        'model_sha256': 'a' * 64, 'total_inputs': len(self.prepared['items']),
                        'vectors': {item['id']: directions[item['title']] if item['kind'] == 'document'
                                    else ([0, 1] if item['text'] in (self.raw, 'epsilon') else [1, 0])
                                    for item in self.prepared['items']}}

    def rank(self, dataset=None, payload=None, limit=3):
        return rank_typed(self.dataset if dataset is None else dataset,
                          self.payload if payload is None else payload,
                          self.dataset_hash, self.input_hash, limit)

    def test_prepare_preserves_sources_full_queries_and_content_ids(self):
        self.assertEqual(self.dataset['index'], self.index)
        self.assertEqual(self.dataset['cases'], self.cases)
        items = self.prepared['items']
        self.assertEqual(len(items), len({item['id'] for item in items}))
        self.assertIn(self.raw, [item['text'] for item in items])
        for item in items:
            expected = ('query\0' + item['text'] if item['kind'] == 'query'
                        else 'document\0' + item['title'] + '\0' + item['text'])
            self.assertEqual(item['id'], digest(expected))
        self.assertEqual(self.prepared, json.loads(json.dumps(self.prepared)))
        self.assertEqual(self.dataset['content_sha256'], digest({k: v for k, v in self.dataset.items()
                                                               if k != 'content_sha256'}))

    def test_prepare_deduplicates_embeddings_but_preserves_query_votes(self):
        cases = copy.deepcopy(self.cases)
        cases[0]['analysis']['queries'].append(copy.deepcopy(cases[0]['analysis']['queries'][0]))
        cases.append({**copy.deepcopy(cases[0]), 'case_id': 'case-二'})
        result = prepare_embedding_dataset(self.index, cases)
        self.assertEqual(result['items'], self.prepared['items'])
        self.assertEqual(len(result['dataset']['cases']), 2)
        self.assertEqual(len(result['dataset']['cases'][0]['analysis']['queries']), 3)

    def test_rank_six_methods_use_same_queries_and_full_corpus(self):
        with patch('typed_knowledge_discovery.bm25_rank', wraps=bm25_rank) as lexical:
            result = self.rank()
        self.assertEqual([c.args[0] for c in lexical.call_args_list], [self.raw, 'beta', 'epsilon'])
        chunks = [chunk for doc in self.index['documents'] for chunk in doc['chunks']]
        for call in lexical.call_args_list:
            self.assertEqual(call.args[1], chunks)
        methods = result['cases'][0]['methods']
        self.assertEqual(set(methods), {'lexical_raw', 'lexical_abstract', 'vector_raw',
                                       'vector_abstract', 'hybrid_raw', 'hybrid_abstract'})
        self.assertEqual(methods['lexical_raw']['global'][0]['title'], 'C')
        self.assertEqual(methods['vector_raw']['global'][0]['title'], 'E')
        self.assertEqual(result['model_sha256'], self.payload['model_sha256'])
        self.assertEqual(result['dimensions'], 2)

    def test_abstract_queries_and_hybrid_groups_receive_equal_rrf_votes(self):
        result = self.rank(limit=20)['cases'][0]['methods']
        chunks = [chunk for doc in self.index['documents'] for chunk in doc['chunks']]
        expected = rrf_fuse([bm25_rank(query['text'], chunks) for query in self.analysis['queries']])
        self.assertEqual([(h['source_path'], h['score']) for h in result['lexical_abstract']['global']],
                         [(h['source_path'], h['score']) for h in expected])
        for mode in ('raw', 'abstract'):
            expected_hybrid = rrf_fuse([result['lexical_' + mode]['global'],
                                       result['vector_' + mode]['global']])
            self.assertEqual([(h['source_path'], h['score']) for h in result['hybrid_' + mode]['global']],
                             [(h['source_path'], h['score']) for h in expected_hybrid])
        # Independent query vectors: beta ranks A first, epsilon ranks E first;
        # document-path tie breaking places zero-scoring F before A for epsilon.
        abstract = result['vector_abstract']['global']
        self.assertEqual([h['title'] for h in abstract], ['E', 'B', 'D', 'C', 'A', 'F'])
        self.assertEqual(abstract[0]['score'], 1 / 61 + 1 / 65)

    def test_type_filtering_happens_before_limit_without_recomputing_corpus(self):
        full = self.rank(limit=50)['cases'][0]['methods']
        limited = self.rank(limit=1)['cases'][0]['methods']
        groups = {'plot': {'motif', 'scenario'}, 'craft': {'technique', 'style'},
                  'pacing': {'pacing'}, 'character': {'character'}}
        for name, method in limited.items():
            self.assertEqual(method['global'], full[name]['global'][:1])
            for group, kinds in groups.items():
                expected = [h for h in full[name]['global'] if h['kind'] in kinds][:1]
                self.assertEqual(method['by_type'][group], expected)
        self.assertEqual(limited['vector_raw']['by_type']['character'][0]['title'], 'F')
        self.assertEqual(limited['vector_raw']['by_type']['plot'][0]['title'], 'D')

    def test_hits_have_exact_excerpt_provenance_and_unique_documents(self):
        documents = {doc['source_path']: doc for doc in self.index['documents']}
        for method in self.rank(limit=50)['cases'][0]['methods'].values():
            hits = method['global']
            self.assertEqual(len(hits), len({h['source_path'] for h in hits}))
            for hit in hits:
                doc = documents[hit['source_path']]
                self.assertEqual(hit['source_sha256'], doc['source_sha256'])
                self.assertEqual(hit['matched_excerpt'], doc['text'][hit['start']:hit['end']])
                self.assertIn(hit['matched_excerpt'], [c['text'] for c in doc['chunks']])

    def test_inputs_are_independent_and_thread_safe(self):
        original = copy.deepcopy((self.index, self.cases, self.dataset, self.payload))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.rank(), range(8)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(original, (self.index, self.cases, self.dataset, self.payload))
        self.dataset['index']['documents'][0]['text'] = 'changed'
        self.assertEqual(self.index, original[0])

    def test_prepare_rejects_invalid_case_container_ids_and_shapes(self):
        for bad in (None, [], {}, 'x', True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                prepare_embedding_dataset(self.index, bad)
        for bad in (None, '', ' ', True, 1, []):
            cases = copy.deepcopy(self.cases)
            cases[0]['case_id'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                prepare_embedding_dataset(self.index, cases)
        for cases in ([self.cases[0], self.cases[0]], [None], [{'case_id': 'x'}],
                      [{**self.cases[0], 'extra': 1}]):
            with self.assertRaises(ValueError):
                prepare_embedding_dataset(self.index, cases)

    def test_prepare_rejects_cross_project_analysis_and_corrupt_sources(self):
        other = freeze_prefix('项目二', self.raw, len(self.raw), '阿澄')
        with self.assertRaises(ValueError):
            prepare_embedding_dataset(self.index, [{**self.cases[0], 'snapshot': other}])
        for field, bad in (('index', None), ('snapshot', None), ('analysis', None)):
            cases = copy.deepcopy(self.cases)
            index = copy.deepcopy(self.index)
            if field == 'index':
                index = bad
            else:
                cases[0][field] = bad
            with self.assertRaises(ValueError):
                prepare_embedding_dataset(index, cases)
        index = copy.deepcopy(self.index)
        index['documents'][0]['text'] += 'tampered'
        with self.assertRaises(ValueError):
            prepare_embedding_dataset(index, self.cases)

    def test_unknown_and_wrong_directory_types_rejected_after_rebinding(self):
        for kind in ('unknown', 'pacing'):
            index = copy.deepcopy(self.index)
            document = next(d for d in index['documents'] if d['kind'] == 'character')
            document['kind'] = kind
            index['corpus_sha256'] = digest({k: v for k, v in index.items() if k != 'corpus_sha256'})
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'source directory'):
                prepare_embedding_dataset(index, self.cases)
            dataset = copy.deepcopy(self.dataset)
            dataset['index'] = index
            dataset['content_sha256'] = digest({k: v for k, v in dataset.items() if k != 'content_sha256'})
            with self.subTest(rank_kind=kind), self.assertRaisesRegex(ValueError, 'source directory'):
                self.rank(dataset=dataset)

    def test_rank_revalidates_content_even_when_embedding_metadata_matches(self):
        mutations = [lambda d: d.update(content_sha256='0' * 64),
                     lambda d: d['index']['documents'][0].update(text='tampered'),
                     lambda d: d['cases'][0]['snapshot'].update(project_id='other'),
                     lambda d: d['cases'][0]['analysis']['queries'][0].update(text='changed'),
                     lambda d: d.update(schema_version=True), lambda d: d.update(extra=1)]
        for mutation in mutations:
            data = copy.deepcopy(self.dataset)
            mutation(data)
            with self.assertRaises(ValueError):
                self.rank(dataset=data)

    def test_rehashed_dataset_still_revalidates_source_prefix_and_analysis(self):
        mutations = [lambda d: d['index']['documents'][0].update(text='forged'),
                     lambda d: d['cases'][0]['snapshot'].update(project_id='foreign'),
                     lambda d: d['cases'][0]['analysis'].update(snapshot_sha256='f' * 64)]
        for mutation in mutations:
            data = copy.deepcopy(self.dataset)
            mutation(data)
            data['content_sha256'] = digest({k: v for k, v in data.items() if k != 'content_sha256'})
            with self.assertRaises(ValueError):
                self.rank(dataset=data)

    def test_same_text_in_another_project_cannot_reuse_stale_bound_payload(self):
        snapshot = freeze_prefix('项目二', self.raw, len(self.raw), '阿澄')
        analysis = {**self.analysis, 'snapshot_sha256': snapshot['snapshot_sha256']}
        prepared = prepare_embedding_dataset(self.index,
                                             [{'case_id': 'case-一', 'snapshot': snapshot, 'analysis': analysis}])
        self.assertEqual(prepared['items'], self.prepared['items'])
        dataset_hash = digest(prepared['dataset'])
        input_hash = digest({'schema_version': 1, 'dataset_sha256': dataset_hash, 'items': prepared['items']})
        with self.assertRaises(ValueError):
            rank_typed(prepared['dataset'], self.payload, dataset_hash, input_hash)
        rebound = {**self.payload, 'dataset_sha256': dataset_hash, 'input_sha256': input_hash}
        actual = rank_typed(prepared['dataset'], rebound, dataset_hash, input_hash)
        self.assertEqual(actual['cases'][0]['methods'], self.rank()['cases'][0]['methods'])

    def test_rank_rejects_cross_dataset_and_input_bindings(self):
        for field in ('dataset_sha256', 'input_sha256'):
            payload = copy.deepcopy(self.payload)
            payload[field] = 'b' * 64
            with self.assertRaises(ValueError):
                self.rank(payload=payload)
        for bad in (None, '', 'z' * 64, 'A' * 64, True):
            with self.assertRaises(ValueError):
                rank_typed(self.dataset, self.payload, bad, self.input_hash)
            with self.assertRaises(ValueError):
                rank_typed(self.dataset, self.payload, self.dataset_hash, bad)

    def test_rank_rejects_invalid_schema_completion_dimensions_model_and_count(self):
        for field, bads in {'schema_version': [0, True, None], 'complete': [False, 1, None],
                            'dimensions': [True, 0, -1, 2.0, None],
                            'model_sha256': [None, '', 'x' * 64, 'A' * 64],
                            'total_inputs': [True, 0, 999, None]}.items():
            for bad in bads:
                payload = copy.deepcopy(self.payload)
                payload[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    self.rank(payload=payload)
        for bad in (None, [], True, {}, 'x'):
            with self.assertRaises(ValueError):
                rank_typed(self.dataset, bad, self.dataset_hash, self.input_hash)

    def test_rank_rejects_missing_extra_ids_and_invalid_vectors(self):
        identity = next(iter(self.payload['vectors']))
        for bad in ([0, 0], [True, 1], [float('nan'), 1], [float('inf'), 1],
                    [float('-inf'), 1], [1], [1, 2, 3], None, '12', [None, 1], ['1', 1]):
            payload = copy.deepcopy(self.payload)
            payload['vectors'][identity] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.rank(payload=payload)
        for mutation in (lambda p: p['vectors'].pop(identity),
                         lambda p: p['vectors'].update({'extra': [1, 0]}),
                         lambda p: p.update(vectors=[])):
            payload = copy.deepcopy(self.payload)
            mutation(payload)
            with self.assertRaises(ValueError):
                self.rank(payload=payload)

    def test_limit_boundaries_and_numeric_stability(self):
        for bad in (None, True, -1, 1.0, '3'):
            with self.assertRaises(ValueError):
                self.rank(limit=bad)
        for method in self.rank(limit=0)['cases'][0]['methods'].values():
            self.assertEqual(method['global'], [])
            self.assertTrue(all(not hits for hits in method['by_type'].values()))
        payload = copy.deepcopy(self.payload)
        for identity, vector in payload['vectors'].items():
            payload['vectors'][identity] = [n * 1e300 for n in vector]
        self.assertEqual([h['source_path'] for h in self.rank(payload=payload)['cases'][0]['methods']['vector_raw']['global']],
                         [h['source_path'] for h in self.rank()['cases'][0]['methods']['vector_raw']['global']])
        for identity, vector in self.payload['vectors'].items():
            payload['vectors'][identity] = [n * 1e-300 for n in vector]
        self.assertEqual([h['source_path'] for h in self.rank(payload=payload)['cases'][0]['methods']['vector_raw']['global']],
                         [h['source_path'] for h in self.rank()['cases'][0]['methods']['vector_raw']['global']])
        payload['vectors'][next(iter(payload['vectors']))] = [10 ** 1000, 1]
        with self.assertRaises(ValueError):
            self.rank(payload=payload)

    def test_long_queries_are_not_silently_truncated_and_large_case_sets_work(self):
        raw = '雨🔑' * 6000
        snapshot = freeze_prefix('long', raw, len(raw), '人')
        analysis = {'schema_version': 1, 'snapshot_sha256': snapshot['snapshot_sha256'],
                    'queries': [{'text': 'query', 'evidence': [{'start': 0, 'end': 1, 'quote': '雨'}]}]}
        result = prepare_embedding_dataset(self.index, [{'case_id': 'long', 'snapshot': snapshot,
                                                        'analysis': analysis}])
        self.assertIn(raw, [i['text'] for i in result['items']])
        cases = [{**self.cases[0], 'case_id': str(i)} for i in range(10001)]
        result = prepare_embedding_dataset(self.index, cases)
        self.assertEqual(len(result['dataset']['cases']), 10001)


if __name__ == '__main__':
    unittest.main()
