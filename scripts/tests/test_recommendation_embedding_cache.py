"""Synthetic cache capability and regression evals; no model relevance claims."""
import copy
import hashlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor

from recommendation_retrieval import encoded, prepare_embedding_bundle, rank_cards, _artifact_vectors
from recommendation_embedding_cache import empty_index, plan_embeddings, complete_embeddings, import_artifact


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def encoded_job(plan):
    bundle = {name: copy.deepcopy(plan[name]) for name in ('dataset', 'embedding_input')}
    contract = bundle['dataset']['embedding_contract']
    return {**bundle, 'embeddings': {
        'schema_version': 1, 'complete': True, 'dimensions': 768,
        'model_sha256': contract['model_sha256'], 'prefix': contract['input_format'],
        'qmd_version': contract['qmd_version'], 'runtime_version': contract['runtime_version'],
        'dataset_sha256': digest(bundle['dataset']), 'input_sha256': digest(bundle['embedding_input']),
        'total_inputs': len(bundle['embedding_input']['items']),
        'vectors': {item['id']: [3, 4.0] + [0.0] * 766 for item in bundle['embedding_input']['items']},
        'elapsed_seconds': 7, 'query_embedding_ms': {}, 'gpu_layers': 33}}


class SharedCacheTests(unittest.TestCase):
    def setUp(self):
        self.context = {'token': {'project_id': 'PRIVATE-PROJECT', 'revision': 1,
                                 'source_sha256': 'a' * 64},
                        'state_sha256': 'b' * 64, 'catalog_sha256': 'c' * 64}
        self.cards = [{'id': 'a', 'title': '甲', 'retrieval_text': '开门 🔑'},
                      {'id': 'b', 'title': '乙', 'retrieval_text': "SELECT '--"}]
        self.bundle = prepare_embedding_bundle(self.context, 'PRIVATE-QUERY', self.cards)

    def build(self, bundle=None, index=None, snapshot=None):
        bundle = self.bundle if bundle is None else bundle
        plan = plan_embeddings(bundle, index, snapshot)
        return complete_embeddings(bundle, index, snapshot,
                                   encoded_job(plan) if plan['embedding_input']['items'] else None)

    def test_cold_warm_and_raw_vectors(self):
        plan = plan_embeddings(self.bundle)
        self.assertEqual(plan['stats']['new_documents'], 2)
        self.assertEqual(plan['stats']['new_queries'], 1)
        self.assertEqual(len(plan['embedding_input']['items']), 3)
        job = encoded_job(plan)
        result = complete_embeddings(self.bundle, encoded_delta=job)
        _artifact_vectors(self.bundle, result['artifact'])
        self.assertEqual(result['artifact']['embeddings']['vectors'], job['embeddings']['vectors'])
        self.assertTrue(result['artifact']['embeddings']['assembly'])
        for key in ('elapsed_seconds', 'query_embedding_ms', 'gpu_layers'):
            self.assertNotIn(key, result['artifact']['embeddings'])
        warm = plan_embeddings(self.bundle, result['index'], result['query_snapshot'])
        self.assertEqual(warm['embedding_input']['items'], [])
        self.assertEqual(warm['stats']['reused_documents'], 2)
        self.assertEqual(warm['stats']['reused_queries'], 1)
        again = complete_embeddings(self.bundle, result['index'], result['query_snapshot'])
        self.assertEqual(result['artifact'], again['artifact'])

    def test_project_and_revision_require_only_query(self):
        old = self.build()
        for context in ({**self.context, 'token': {**self.context['token'], 'project_id': 'new'}},
                        {**self.context, 'token': {**self.context['token'], 'revision': 2}}):
            bundle = prepare_embedding_bundle(context, 'PRIVATE-QUERY', self.cards)
            plan = plan_embeddings(bundle, old['index'], old['query_snapshot'])
            self.assertEqual([i['kind'] for i in plan['embedding_input']['items']], ['query'])
            self.assertEqual(plan['stats']['reused_queries'], 0)

    def test_unscoped_or_malformed_project_context_rejected(self):
        invalid = [{}, {'token': {}}, {**self.context, 'extra': 'hidden'}]
        for key, values in [('project_id', ['', ' ', None]), ('revision', [True, 0, 1.0]),
                            ('source_sha256', ['bad', None])]:
            for value in values:
                invalid.append({**self.context, 'token': {**self.context['token'], key: value}})
        for key in ('state_sha256', 'catalog_sha256'):
            invalid.append({k: v for k, v in self.context.items() if k != key})
            invalid.append({**self.context, key: 'not-a-hash'})
        for context in invalid:
            with self.subTest(context=context), self.assertRaises(ValueError):
                plan_embeddings(prepare_embedding_bundle(context, 'same query', []))
        # A self-consistent but unscoped snapshot must not become a cache miss.
        snapshot = copy.deepcopy(self.build()['query_snapshot'])
        snapshot['context'] = {}
        canonical = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        scope = {key: snapshot[key] for key in ('embedding_contract', 'context', 'query', 'catalog_sha256')}
        snapshot['scope_sha256'] = canonical(scope)
        snapshot['snapshot_sha256'] = canonical({k: v for k, v in snapshot.items() if k != 'snapshot_sha256'})
        with self.assertRaises(ValueError): plan_embeddings(self.bundle, query_snapshot=snapshot)

    def test_catalog_edit_add_remove_and_duplicate_content(self):
        old = self.build()
        variants = [(self.cards + [{'id': 'c', 'title': '丙', 'retrieval_text': 'new'}], 1),
                    ([{**self.cards[0], 'retrieval_text': 'changed'}, self.cards[1]], 1),
                    ([self.cards[0]], 0),
                    (self.cards + [{**self.cards[0], 'id': 'duplicate'}], 0)]
        for cards, misses in variants:
            bundle = prepare_embedding_bundle(self.context, 'PRIVATE-QUERY', cards)
            plan = plan_embeddings(bundle, old['index'], old['query_snapshot'])
            self.assertEqual(plan['stats']['new_documents'], misses)
            self.assertEqual(plan['stats']['new_queries'], 1)
            result = self.build(bundle, old['index'], old['query_snapshot'])
            ranking = rank_cards(self.context, 'PRIVATE-QUERY', cards, 'vector', 50, result['artifact'])
            self.assertEqual({r['chunk_id'] for r in ranking['ranking']}, {c['id'] for c in cards})
            self.assertGreaterEqual(len(result['index']['documents']), 2)

    def test_empty_query_documents_and_no_phantom(self):
        for query, cards, count in [('', self.cards, 2), (' \n', [], 0), ('query', [], 1)]:
            bundle = prepare_embedding_bundle(self.context, query, cards)
            result = self.build(bundle)
            self.assertEqual(result['stats']['total_inputs'], count)
            self.assertEqual(result['query_snapshot']['query_entry'] is None, not query.strip())
            _artifact_vectors(bundle, result['artifact'])
            self.assertEqual(rank_cards(self.context, query, cards, 'vector', 50, result['artifact'])['ranking'], [])

    def test_shared_index_contains_only_document_content(self):
        result = self.build()
        dumped = json.dumps(result['index'])
        for private in ('PRIVATE-PROJECT', 'PRIVATE-QUERY', 'token', 'context', 'query_embedding_ms'):
            self.assertNotIn(private, dumped)
        for row in result['index']['documents'].values():
            self.assertEqual(row['item']['kind'], 'document')
            self.assertEqual(set(row['source_job']), {'dataset_sha256', 'input_sha256', 'embedding_sha256'})

    def test_poisoned_unused_rows_profile_schema_and_digest_fail_loud(self):
        result = self.build()
        minimal = prepare_embedding_bundle(self.context, '', [])
        mutations = [lambda x: x.update(schema_version=True),
                     lambda x: x.update(private_context={}),
                     lambda x: x['embedding_contract'].update(dimensions=True),
                     lambda x: x['embedding_contract'].update(model_sha256='0' * 64),
                     lambda x: next(iter(x['documents'].values()))['item'].update(text='changed'),
                     lambda x: next(iter(x['documents'].values()))['vector'].__setitem__(0, 7),
                     lambda x: next(iter(x['documents'].values()))['source_job'].update(input_sha256='0' * 64),
                     lambda x: next(iter(x['documents'].values()))['item'].update(kind='query'),
                     lambda x: next(iter(x['documents'].values())).update(dataset={})]
        for mutate in mutations:
            poisoned = copy.deepcopy(result['index']); mutate(poisoned)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                plan_embeddings(minimal, poisoned)

    def test_query_snapshot_invalid_even_when_scope_mismatches(self):
        result = self.build()
        other = prepare_embedding_bundle(self.context, 'other', [])
        for mutate in (lambda x: x.update(schema_version=True),
                       lambda x: x.update(query='tamper'),
                       lambda x: x['embedding_contract'].update(runtime_version='bad'),
                       lambda x: x['query_entry']['vector'].__setitem__(0, 99),
                       lambda x: x.update(scope_sha256='0' * 64),
                       lambda x: x.update(unexpected='secret')):
            poisoned = copy.deepcopy(result['query_snapshot']); mutate(poisoned)
            with self.assertRaises(ValueError): plan_embeddings(other, result['index'], poisoned)

    def test_delta_rejects_stale_extra_missing_and_invalid_values(self):
        plan = plan_embeddings(self.bundle)
        mutations = [lambda a: a['dataset'].update(unexpected=True),
                     lambda a: a['embedding_input']['items'].pop(),
                     lambda a: a['embeddings']['vectors'].update(extra=[1] * 768),
                     lambda a: a['embeddings']['vectors'].pop(next(iter(a['embeddings']['vectors']))),
                     lambda a: a['embeddings'].update(complete=False),
                     lambda a: a['embeddings'].update(schema_version=True),
                     lambda a: a['embeddings'].update(model_sha256='0' * 64),
                     lambda a: a['embeddings'].update(dimensions=767)]
        for value in (True, None, 'bad', float('nan'), float('inf')):
            mutations.append(lambda a, value=value: next(iter(a['embeddings']['vectors'].values())).__setitem__(0, value))
        mutations.append(lambda a: a['embeddings']['vectors'].__setitem__(next(iter(a['embeddings']['vectors'])), [0] * 768))
        for mutate in mutations:
            bad = encoded_job(plan); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                complete_embeddings(self.bundle, encoded_delta=bad)
        with self.assertRaises(ValueError): complete_embeddings(self.bundle)
        result = self.build()
        with self.assertRaises(ValueError):
            complete_embeddings(self.bundle, result['index'], result['query_snapshot'], encoded_job(plan))

    def test_legacy_import_preserves_sources_and_rejects_divergence(self):
        legacy = encoded_job(self.bundle)
        result = import_artifact(self.bundle, legacy)
        self.assertEqual(plan_embeddings(self.bundle, result['index'], result['query_snapshot'])['stats']['total_inputs'], 0)
        imported = import_artifact(self.bundle, legacy, result['index'])
        self.assertEqual(imported['index'], result['index'])
        altered = copy.deepcopy(legacy)
        doc_id = next(i['id'] for i in legacy['embedding_input']['items'] if i['kind'] == 'document')
        altered['embeddings']['vectors'][doc_id][0] = 6
        with self.assertRaises(ValueError): import_artifact(self.bundle, altered, result['index'])
        self.assertEqual(result['index']['documents'][doc_id]['source_job']['embedding_sha256'], digest(legacy['embeddings']))

    def test_inputs_immutable_map_order_deterministic_and_concurrent(self):
        result = self.build()
        before = copy.deepcopy((self.bundle, result))
        shuffled = copy.deepcopy(result['index'])
        shuffled['documents'] = dict(reversed(list(shuffled['documents'].items())))
        first = complete_embeddings(self.bundle, result['index'], result['query_snapshot'])
        second = complete_embeddings(self.bundle, shuffled, result['query_snapshot'])
        self.assertEqual(encoded(first), encoded(second))
        with ThreadPoolExecutor(max_workers=4) as pool:
            outputs = list(pool.map(lambda _: complete_embeddings(self.bundle, result['index'], result['query_snapshot']), range(8)))
        self.assertTrue(all(output == first for output in outputs))
        self.assertEqual((self.bundle, result), before)

    def test_invalid_api_inputs(self):
        for bad in (None, [], '', True, {}, {'dataset': None}):
            with self.assertRaises(ValueError): plan_embeddings(bad)
        for bad in ([], '', True):
            with self.assertRaises(ValueError): plan_embeddings(self.bundle, bad)
            with self.assertRaises(ValueError): plan_embeddings(self.bundle, query_snapshot=bad)

    def test_large_duplicate_catalog_and_special_query(self):
        cards = [{**self.cards[0], 'id': str(i)} for i in range(10001)]
        bundle = prepare_embedding_bundle(self.context, "中文\0\n'--😀", cards)
        result = self.build(bundle)
        self.assertEqual(len(result['index']['documents']), 1)
        self.assertEqual(len(result['artifact']['embeddings']['vectors']), 2)
        self.assertEqual(len(rank_cards(bundle['dataset']['context'], bundle['dataset']['query'], cards, 'vector', 50, result['artifact'])['ranking']), 50)


class EngineCacheIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_recommendation_engine as contracts
        self.contracts = contracts
        contracts.EngineTests.setUp(self)

    def test_assembled_artifact_preserves_review_and_writer_isolation(self):
        from recommendation_engine import (prepare_retrieval_embeddings, prepare_recommendations,
            review_recommendations)
        from recommendation_session import append_scene, source_token
        session, _ = self.contracts.EngineTests.state(self)
        bundle = prepare_retrieval_embeddings(session, self.catalog, self.root)
        plan = plan_embeddings(bundle)
        completed = complete_embeddings(bundle, encoded_delta=encoded_job(plan))
        request = prepare_recommendations(session, self.catalog, self.root,
            retrieval_method='vector', embedding_artifact=completed['artifact'])
        reviews = {instance['id']: self.contracts.review(instance['prepared']['packet'])
                   for instance in request['instances']}
        ready = review_recommendations(session, request, reviews, self.catalog, self.root,
                                       embedding_artifact=completed['artifact'])
        writer = ready['current_batch']['writer_packet']
        self.assertEqual(set(writer), {'facts', 'proposals', 'instruction'})
        for private in ('vectors', 'source_jobs', 'assembly', 'ranking', 'retrieval_provenance'):
            self.assertNotIn(private, str(writer))
        changed = append_scene(ready, dict(self.project['scenes'][0], id='s2', order=2,
                                          text='林读完纸条。'), source_token(ready))
        with self.assertRaises(ValueError):
            review_recommendations(changed, request, reviews, self.catalog, self.root,
                                   embedding_artifact=completed['artifact'])
        changed_artifact = copy.deepcopy(completed['artifact'])
        query_id = next(item['id'] for item in bundle['embedding_input']['items'] if item['kind'] == 'query')
        changed_artifact['embeddings']['vectors'][query_id] = [0., 1.] + [0.] * 766
        with self.assertRaises(ValueError):
            review_recommendations(session, request, reviews, self.catalog, self.root,
                                   embedding_artifact=changed_artifact)


if __name__ == '__main__':
    unittest.main()
