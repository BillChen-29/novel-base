"""Synthetic-vector contract evals; these do not measure model relevance."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recommendation_retrieval import encoded, prepare_embedding_bundle, rank_cards
from retrieval_pilot import bm25_rank


MODEL = 'b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63'


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def vector(x, y=0):
    return [x, y] + [0.0] * 766


class RetrievalContracts(unittest.TestCase):
    def setUp(self):
        self.context = {'token': {'project_id': 'project-一', 'revision': 3,
                                  'source_sha256': 'a' * 64},
                        'state_sha256': 'b' * 64, 'catalog_sha256': 'c' * 64}
        self.query = 'alpha'
        self.cards = [{'id': 'a', 'title': 'A', 'retrieval_text': 'alpha alpha'},
                      {'id': 'b', 'title': 'B', 'retrieval_text': 'alpha beta'},
                      {'id': 'c', 'title': 'C', 'retrieval_text': 'gamma gamma'}]

    def artifact(self, context=None, query=None, cards=None, directions=None):
        bundle = prepare_embedding_bundle(self.context if context is None else context,
                                          self.query if query is None else query,
                                          self.cards if cards is None else cards)
        directions = directions or {'A': vector(0, 1), 'B': vector(3, 4), 'C': vector(8)}
        payload = {'schema_version': 1, 'complete': True, 'dimensions': 768,
                   'dataset_sha256': sha(encoded(bundle['dataset'])),
                   'input_sha256': sha(encoded(bundle['embedding_input'])),
                   'model_sha256': MODEL, 'prefix': 'qmd-format-functions-v1',
                   'qmd_version': '2.1.0', 'runtime_version': '3.18.1',
                   'total_inputs': len(bundle['embedding_input']['items']),
                   'vectors': {item['id']: (vector(5) if item['kind'] == 'query'
                                           else directions[item['title']])
                               for item in bundle['embedding_input']['items']}}
        return {**bundle, 'embeddings': payload}

    def rank(self, **kwargs):
        return rank_cards(self.context, self.query, self.cards, **kwargs)

    def test_encoding_exact_utf8_indent_newline_and_rejects_nonfinite(self):
        self.assertEqual(encoded({'文字': '🔑'}), b'{\n  "\xe6\x96\x87\xe5\xad\x97": "\xf0\x9f\x94\x91"\n}\n')
        with self.assertRaises(ValueError):
            encoded({'bad': float('nan')})

    def test_bundle_binds_context_query_projection_and_fixed_model(self):
        query = '风雨\n🔑 SELECT \'--\x00' * 100
        cards = copy.deepcopy(self.cards)
        cards[0]['private_notes'] = 'not an embedding input'
        before = copy.deepcopy((self.context, cards))
        bundle = prepare_embedding_bundle(self.context, query, cards)
        self.assertEqual(set(bundle), {'dataset', 'embedding_input'})
        dataset, inputs = bundle['dataset'], bundle['embedding_input']
        self.assertEqual(dataset['context'], self.context)
        self.assertEqual(dataset['query'], query)
        self.assertEqual(dataset['cards'], self.cards)
        self.assertEqual(dataset['embedding_contract'], {'model_sha256': MODEL, 'dimensions': 768,
                                                        'input_format': 'qmd-format-functions-v1',
                                                        'qmd_version': '2.1.0', 'runtime_version': '3.18.1'})
        self.assertEqual(inputs['dataset_sha256'], sha(encoded(dataset)))
        self.assertEqual((self.context, cards), before)
        for item in inputs['items']:
            seed = ('query\0' + item['text'] if item['kind'] == 'query'
                    else 'document\0' + item['title'] + '\0' + item['text'])
            self.assertEqual(item['id'], sha(seed))
        self.assertIn(query, [item['text'] for item in inputs['items']])
        dataset['context']['token']['revision'] += 1
        self.assertEqual(self.context, before[0])

    def test_card_order_is_canonical_and_identical_embeddings_are_deduplicated(self):
        duplicate = {**self.cards[0], 'id': 'd'}
        cards = self.cards + [duplicate]
        bundle = prepare_embedding_bundle(self.context, self.query, cards)
        self.assertEqual(bundle, prepare_embedding_bundle(self.context, self.query, list(reversed(cards))))
        self.assertEqual(len(bundle['embedding_input']['items']), 4)
        result = rank_cards(self.context, self.query, cards, 'vector', 50,
                            self.artifact(cards=cards))
        self.assertEqual(len(result['ranking']), 4)
        self.assertEqual([h['source_path'] for h in result['ranking']][-2:], ['a', 'd'])

    def test_bm25_reuses_existing_behavior_and_never_backfills_nonmatches(self):
        chunks = [{'source_path': c['id'], 'chunk_id': c['id'], 'title': c['title'],
                   'text': c['retrieval_text']} for c in self.cards]
        with patch('recommendation_retrieval.bm25_rank', wraps=bm25_rank) as lexical:
            result = self.rank(top_k=50)
        self.assertEqual(result, {'ranking': bm25_rank(self.query, chunks), 'provenance': {}})
        lexical.assert_called_once_with(self.query, chunks)
        self.assertEqual([h['source_path'] for h in result['ranking']], ['a', 'b'])
        self.assertEqual(rank_cards(self.context, 'absent', self.cards)['ranking'], [])

    def test_vector_normalization_ranking_and_hash_only_provenance(self):
        artifact = self.artifact()
        before = copy.deepcopy(artifact)
        result = self.rank(method='vector', top_k=50, embedding_artifact=artifact)
        self.assertEqual([h['source_path'] for h in result['ranking']], ['c', 'b', 'a'])
        self.assertEqual([h['score'] for h in result['ranking']], [1.0, .6, 0.0])
        for row in result['ranking']:
            self.assertEqual(set(row), {'source_path', 'chunk_id', 'score'})
            self.assertEqual(row['source_path'], row['chunk_id'])
            self.assertIs(type(row['score']), float)
            self.assertTrue(math.isfinite(row['score']))
        self.assertEqual(result['provenance'], {'method': 'vector',
                         'embedding_sha256': sha(encoded(artifact['embeddings'])),
                         'dataset_sha256': artifact['embeddings']['dataset_sha256'],
                         'input_sha256': artifact['embeddings']['input_sha256'],
                         'model_sha256': MODEL, 'dimensions': 768})
        self.assertEqual(artifact, before)

    def test_hybrid_uses_full_rankings_before_budget_and_strips_internal_fields(self):
        result = self.rank(method='hybrid', top_k=2, embedding_artifact=self.artifact())
        # Lexical a,b; vector c,b,a. The third vector vote makes a beat b.
        self.assertEqual([h['source_path'] for h in result['ranking']], ['a', 'b'])
        self.assertAlmostEqual(result['ranking'][0]['score'], 1 / 61 + 1 / 63)
        self.assertAlmostEqual(result['ranking'][1]['score'], 2 / 62)
        self.assertEqual(result['provenance']['rrf_k'], 60)
        self.assertEqual(result['provenance']['method'], 'hybrid')
        self.assertTrue(all(set(h) == {'source_path', 'chunk_id', 'score'} for h in result['ranking']))

    def test_negative_cosines_and_ties_are_ranked_without_admission_threshold(self):
        artifact = self.artifact(directions={title: vector(-1) for title in 'ABC'})
        result = rank_cards(self.context, self.query, list(reversed(self.cards)), 'vector', 50, artifact)
        self.assertEqual([h['source_path'] for h in result['ranking']], ['a', 'b', 'c'])
        self.assertTrue(all(h['score'] == -1.0 for h in result['ranking']))

    def test_every_context_binding_and_card_query_change_invalidates_cache(self):
        artifact = self.artifact()
        contexts = []
        for key in ('project_id', 'revision', 'source_sha256'):
            context = copy.deepcopy(self.context)
            context['token'][key] = 4 if key == 'revision' else 'changed'
            contexts.append(context)
        for key in ('state_sha256', 'catalog_sha256'):
            context = copy.deepcopy(self.context)
            context[key] = 'd' * 64
            contexts.append(context)
        for context in contexts:
            with self.subTest(context=context), self.assertRaises(ValueError):
                rank_cards(context, self.query, self.cards, 'vector', 2, artifact)
        for query, cards in [('beta', self.cards), (self.query, self.cards[:-1]),
                             (self.query, [{**self.cards[0], 'title': 'changed'}] + self.cards[1:]),
                             (self.query, [{**self.cards[0], 'retrieval_text': 'changed'}] + self.cards[1:])]:
            with self.subTest(query=query, cards=cards), self.assertRaises(ValueError):
                rank_cards(self.context, query, cards, 'hybrid', 2, artifact)

    def test_artifact_envelope_input_and_dataset_mutations_rejected(self):
        artifact = self.artifact()
        mutations = [None, [], {}, {**artifact, 'extra': 1}]
        for key in artifact:
            mutations.append({k: v for k, v in artifact.items() if k != key})
        for key in ('dataset', 'embedding_input'):
            bad = copy.deepcopy(artifact)
            bad[key]['schema_version'] = True
            mutations.append(bad)
        bad = copy.deepcopy(artifact)
        bad['embedding_input']['items'][0]['text'] += ' changed'
        mutations.append(bad)
        for bad in mutations:
            with self.subTest(artifact=type(bad)), self.assertRaises(ValueError):
                self.rank(method='vector', embedding_artifact=bad)

    def test_wrong_payload_metadata_rejected_including_bool_dimensions(self):
        values = {'schema_version': [None, True, 2], 'complete': [False, 1],
                  'dataset_sha256': ['0' * 64], 'input_sha256': ['0' * 64],
                  'model_sha256': ['0' * 64, None], 'dimensions': [True, 0, 2, 768.0],
                  'prefix': [None, 'other'], 'qmd_version': [None, '0'],
                  'runtime_version': [None, '0'],
                  'total_inputs': [True, 0, 4.0], 'vectors': [None, [], {}]}
        for field, options in values.items():
            for value in options:
                artifact = self.artifact()
                artifact['embeddings'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.rank(method='vector', embedding_artifact=artifact)

    def test_exact_vector_id_set_and_bad_values_rejected_even_when_top_k_zero(self):
        bad_vectors = [[], vector(0), vector(True), vector(float('nan')),
                       vector(float('inf')), vector('1'), vector(None), vector(10 ** 10000),
                       [1.0] * 767, [1.0] * 769, 'not a vector']
        for bad in bad_vectors:
            artifact = self.artifact()
            identity = next(iter(artifact['embeddings']['vectors']))
            artifact['embeddings']['vectors'][identity] = bad
            with self.subTest(bad_type=type(bad)), self.assertRaises(ValueError):
                self.rank(method='vector', top_k=0, embedding_artifact=artifact)
        for extra in (False, True):
            artifact = self.artifact()
            vectors = artifact['embeddings']['vectors']
            if extra:
                vectors['f' * 64] = vector(1)
            else:
                vectors.pop(next(iter(vectors)))
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.rank(method='hybrid', embedding_artifact=artifact)

    def test_extreme_finite_vectors_normalize_without_overflow_or_underflow(self):
        for scale in (1e308, 1e-308):
            artifact = self.artifact(directions={title: vector(scale, scale) for title in 'ABC'})
            result = self.rank(method='vector', embedding_artifact=artifact)
            self.assertAlmostEqual(result['ranking'][0]['score'], 1 / math.sqrt(2))

    def test_empty_queries_need_no_artifact_but_validate_artifacts_if_provided(self):
        for query in ('', ' \n\t'):
            for method in ('bm25', 'vector', 'hybrid'):
                result = rank_cards(self.context, query, self.cards, method)
                self.assertEqual(result, {'ranking': [], 'provenance': {}})
                artifact = self.artifact(query=query)
                result = rank_cards(self.context, query, self.cards, method, 2, artifact)
                self.assertEqual(result['ranking'], [])
                artifact['embeddings']['complete'] = False
                with self.assertRaises(ValueError):
                    rank_cards(self.context, query, self.cards, method, 2, artifact)

    def test_empty_cards_and_zero_budget_are_safe_without_skipping_validation(self):
        self.assertEqual(rank_cards(self.context, self.query, [])['ranking'], [])
        for method in ('vector', 'hybrid'):
            for cards in ([], self.cards):
                with self.assertRaises(ValueError):
                    rank_cards(self.context, self.query, cards, method, 0)
            artifact = self.artifact(cards=[])
            self.assertEqual(rank_cards(self.context, self.query, [], method, 0, artifact)['ranking'], [])
        self.assertEqual(self.rank(top_k=0)['ranking'], [])
        self.assertEqual(self.rank(method='vector', top_k=0, embedding_artifact=self.artifact())['ranking'], [])
        with self.assertRaises(ValueError):
            self.rank(embedding_artifact={})

    def test_invalid_public_inputs_rejected(self):
        for method in (None, '', 'semantic', [], True):
            with self.subTest(method=method), self.assertRaises(ValueError):
                self.rank(method=method)
        for top_k in (None, True, -1, 51, 1.0, '2'):
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                self.rank(top_k=top_k)
        for query in (None, 1, [], {}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                rank_cards(self.context, query, self.cards)
        for context, cards in [(None, self.cards), ([], self.cards), (self.context, None),
                               (self.context, {}), (self.context, [None]),
                               (self.context, self.cards + [self.cards[0]])]:
            with self.subTest(context=context, cards=cards), self.assertRaises(ValueError):
                prepare_embedding_bundle(context, self.query, cards)
        for key in ('id', 'title', 'retrieval_text'):
            for value in (None, '', 1):
                cards = [{**self.cards[0], key: value}]
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    prepare_embedding_bundle(self.context, self.query, cards)

    def test_large_lexical_pool_limits_results_without_backfill(self):
        cards = [{'id': f'c{i:05}', 'title': 'Card', 'retrieval_text': 'alpha' if i < 60 else 'beta'}
                 for i in range(10001)]
        result = rank_cards(self.context, self.query, cards, top_k=50)
        self.assertEqual([h['source_path'] for h in result['ranking']], [f'c{i:05}' for i in range(50)])

    def test_parallel_calls_are_deterministic_and_do_not_mutate_shared_artifact(self):
        artifact = self.artifact()
        before = encoded(artifact)
        def call(_):
            return self.rank(method='hybrid', embedding_artifact=artifact)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(call, range(12)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(encoded(artifact), before)


if __name__ == '__main__':
    unittest.main()
