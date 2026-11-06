"""Synthetic contracts for action-compatible candidate budgets."""
import copy
import unittest

import test_recommendation_engine as contracts
from test_recommendation_vector import artifact
from recommendation_engine import (
    prepare_recommendations, prepare_retrieval_embeddings, review_recommendations,
)
from recommendation_retrieval import encoded, rank_cards
from retrieval_pilot import bm25_rank


class ActionBudgetTests(unittest.TestCase):
    setUp = contracts.EngineTests.setUp
    state = contracts.EngineTests.state

    def card(self, card_id, operation, status='proposed'):
        card = copy.deepcopy(self.catalog['motifs'][0])
        card['id'] = card_id
        card['variants'][0].update(operations=[operation], action_states=[status])
        return card

    def prepare(self, state, **kwargs):
        return prepare_recommendations(state, self.catalog, self.root,
                                       candidate_policy='action_compatible', **kwargs)

    def test_full_catalog_scores_before_budget_even_beyond_fiftieth_card(self):
        cards = [self.card(f'a_{idx:02}', 'check') for idx in range(51)]
        cards.append(self.card('z_read', 'read'))
        self.catalog['motifs'] = cards
        state, _ = self.state()
        bundle = prepare_retrieval_embeddings(state, self.catalog, self.root)
        cache = artifact(bundle)
        chunks = [dict(source_path=c['id'], chunk_id=c['id'], title=c['title'],
                       text=c['retrieval_text']) for c in cards]
        lexical = bm25_rank(bundle['dataset']['query'], chunks)
        self.assertEqual(lexical[-1]['source_path'], 'z_read')
        # Tied input texts/vectors place the eligible card 52nd in both full rankings.
        scores = {'bm25': lexical[-1]['score'], 'vector': 1., 'hybrid': 2 / (60 + 52)}
        for method, score in scores.items():
            with self.subTest(method=method):
                options = {'retrieval_method': method, 'embedding_artifact': cache, 'top_k': 1}
                baseline = prepare_recommendations(state, self.catalog, self.root, **options)
                self.assertFalse(baseline['instances'])
                request = self.prepare(state, **options)
                self.assertEqual(request['compatible_card_ids'], ['z_read'])
                self.assertEqual(request['ranking'], [dict(source_path='z_read', chunk_id='z_read',
                                                            score=score)])
                self.assertEqual([i['card_id'] for i in request['instances']], ['z_read'])
                self.assertEqual(request['query'], baseline['query'])
                self.assertEqual(request.get('retrieval_provenance'), baseline.get('retrieval_provenance'))
        self.assertEqual(self.prepare(state, top_k=1)['ranking'], [lexical[-1]])

    def test_one_budget_covers_union_and_shared_card_instantiates_both_actions(self):
        annotations = copy.deepcopy(self.annotations)
        actions = annotations['registry']['actions']
        actions.append(dict(actions[0], id='check_note', operation='check'))
        state, _ = self.state(annotations)
        shared = self.card('a_shared', 'read')
        shared['variants'][0]['operations'].append('check')
        self.catalog['motifs'] = [shared, self.card('b_read', 'read'), self.card('c_check', 'check')]
        request = self.prepare(state, top_k=1)
        self.assertEqual(request['compatible_card_ids'], ['a_shared', 'b_read', 'c_check'])
        self.assertEqual([r['source_path'] for r in request['ranking']], ['a_shared'])
        self.assertEqual([(i['card_id'], i['action_id']) for i in request['instances']],
                         [('a_shared', 'read_note'), ('a_shared', 'check_note')])
        self.catalog['motifs'] = self.catalog['motifs'][1:]
        self.assertEqual([i['action_id'] for i in self.prepare(state, top_k=1)['instances']],
                         ['read_note'])

    def test_variant_must_match_operation_and_current_status_together(self):
        annotations = copy.deepcopy(self.annotations)
        annotations['registry']['actions'][0].update(origin='observed', status='in_progress')
        state, _ = self.state(annotations)
        crossed = self.card('a_crossed', 'read', 'proposed')
        crossed['variants'].append(dict(crossed['variants'][0], id='other',
                                        operations=['check'], action_states=['in_progress']))
        self.catalog['motifs'] = [crossed, self.card('b_match', 'read', 'in_progress')]
        request = self.prepare(state)
        self.assertEqual(request['compatible_card_ids'], ['b_match'])
        self.assertEqual([i['card_id'] for i in request['instances']], ['b_match'])
        unreviewed, _ = self.state(annotations, unknown=['core_status_read_note'])
        request = self.prepare(unreviewed)
        self.assertEqual(request['compatible_card_ids'], [])
        self.assertEqual(request['blocked_actions'], [{'action_id': 'read_note', 'reason': 'action_unknown'}])

    def test_blocked_peers_and_other_pov_never_reserve_a_slot(self):
        self.project['characters'].append('陈')
        annotations = copy.deepcopy(self.annotations)
        registry = annotations['registry']
        registry['characters'].append({'id': 'chen', 'label': '陈'})
        action = registry['actions'][0]
        registry['actions'].extend([
            dict(action, id='already_read', origin='observed', status='completed'),
            dict(action, id='hidden_check', actor_id='chen', operation='check'),
            dict(action, id='unknown_use', operation='use'),
        ])
        state, _ = self.state(annotations, hidden=['core_binding_unknown_use'])
        self.catalog['motifs'] = [self.card('a', 'read'), self.card('b', 'check'), self.card('c', 'use')]
        request = self.prepare(state)
        self.assertEqual(request['blocked_actions'], [
            {'action_id': 'read_note', 'reason': 'same_operation_completed'},
            {'action_id': 'already_read', 'reason': 'action_completed'},
            {'action_id': 'hidden_check', 'reason': 'actor_not_current_pov'},
            {'action_id': 'unknown_use', 'reason': 'binding_not_pov_established'},
        ])
        self.assertEqual((request['compatible_card_ids'], request['ranking'], request['instances']),
                         ([], [], []))

    def test_bm25_does_not_fill_absent_hits_and_empty_query_is_still_empty(self):
        self.catalog['motifs'][0].update(title='xyz', retrieval_text='abc')
        state, _ = self.state()
        request = self.prepare(state)
        self.assertEqual(request['compatible_card_ids'], ['read'])
        self.assertEqual(request['ranking'], [])
        ann = copy.deepcopy(self.annotations)
        ann['facts'] = []
        state, _ = self.state(ann)
        for method in ('bm25', 'vector', 'hybrid'):
            request = self.prepare(state, retrieval_method=method)
            self.assertEqual((request['query'], request['ranking'], request['instances']), ('', [], []))

    def test_validate_complete_artifact_with_zero_budget_and_no_available_actions(self):
        annotations = copy.deepcopy(self.annotations)
        annotations['registry']['actions'] = []
        state, _ = self.state(annotations)
        bundle = prepare_retrieval_embeddings(state, self.catalog, self.root)
        cache = artifact(bundle)
        del cache['embeddings']['vectors'][bundle['embedding_input']['items'][0]['id']]
        for method in ('bm25', 'vector', 'hybrid'):
            for top_k in (0, 2):
                with self.subTest(method=method, top_k=top_k), self.assertRaises(ValueError):
                    self.prepare(state, retrieval_method=method, top_k=top_k, embedding_artifact=cache)
        for method in ('vector', 'hybrid'):
            with self.assertRaisesRegex(ValueError, 'embedding_artifact_required'):
                self.prepare(state, retrieval_method=method, top_k=0)

    def test_ranker_rejects_malformed_card_id_filters_even_for_empty_query(self):
        cards = self.catalog['motifs']
        for malformed in ('read_extra', ['read'], {1}):
            with self.subTest(malformed=malformed), self.assertRaisesRegex(ValueError, 'invalid_eligible_card_ids'):
                rank_cards({}, '', cards, method='vector', eligible_card_ids=malformed)
        self.assertEqual(rank_cards({}, '纸条', cards, eligible_card_ids=frozenset({'read'}))['ranking'],
                         rank_cards({}, '纸条', cards)['ranking'])

    def test_policy_identity_review_binding_default_parity_and_writer_boundary(self):
        state, _ = self.state()
        baseline = prepare_recommendations(state, self.catalog, self.root)
        explicit = prepare_recommendations(state, self.catalog, self.root, candidate_policy='global')
        self.assertEqual(encoded(explicit), encoded(baseline))
        self.assertNotIn('candidate_policy', baseline)
        opted_in = self.prepare(state)
        self.assertEqual(opted_in['ranking'], baseline['ranking'])
        self.assertEqual(opted_in['candidate_policy'], 'action_compatible')
        reviews = {i['id']: contracts.review(i['prepared']['packet']) for i in opted_in['instances']}
        def review_request(request):
            return review_recommendations(state, request, reviews, self.catalog, self.root)['current_batch']
        old_batch, batch = review_request(baseline), review_request(opted_in)
        self.assertNotIn('candidate_policy', old_batch['author_audit'])
        self.assertEqual(batch['author_audit']['candidate_policy'], 'action_compatible')
        self.assertEqual(batch['author_audit']['compatible_card_ids'], ['read'])
        self.assertNotEqual(batch['request_sha256'], old_batch['request_sha256'])
        self.assertNotEqual(batch['proposals'][0]['id'], old_batch['proposals'][0]['id'])
        self.assertNotIn('candidate_policy', str(batch['writer_packet']))
        self.assertNotIn('compatible_card_ids', str(batch['writer_packet']))
        for change in ({'candidate_policy': 'global'}, {'compatible_card_ids': []}):
            with self.assertRaisesRegex(ValueError, 'request_changed_or_stale'):
                review_request({**opted_in, **change})
        missing = dict(opted_in)
        del missing['candidate_policy']
        with self.assertRaisesRegex(ValueError, 'request_changed_or_stale'):
            review_request(missing)
        for invalid in ('other', None, 1, []):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'invalid_candidate_policy'):
                prepare_recommendations(state, self.catalog, self.root, candidate_policy=invalid)
            with self.assertRaisesRegex(ValueError, 'invalid_candidate_policy'):
                review_request({**opted_in, 'candidate_policy': invalid})

    def test_admitted_vector_hit_still_needs_semantic_review_and_preserves_pov_boundary(self):
        secret = '幕后藏在码头的钥匙'
        self.project['scenes'][0]['text'] += secret
        self.catalog['motifs'][0]['id'] = 'private_catalog_id'
        state, _ = self.state()
        cache = artifact(prepare_retrieval_embeddings(state, self.catalog, self.root))
        request = self.prepare(state, retrieval_method='vector', embedding_artifact=cache)
        instance, = request['instances']
        packet = instance['prepared']['packet']
        unknown = [c['fact_id'] for c in packet['candidates']]
        reviews = {instance['id']: contracts.review(packet, unknown=unknown)}
        batch = review_recommendations(state, request, reviews, self.catalog, self.root,
                                       embedding_artifact=cache)['current_batch']
        self.assertFalse(batch['proposals'])
        self.assertIn(secret, str(batch['author_audit']['matches']))
        for private in (secret, 'private_catalog_id', 'compatible_card_ids', 'candidate_policy',
                        'retrieval_provenance', 'blocked_actions', 'ranking'):
            self.assertNotIn(private, str(batch['writer_packet']))


if __name__ == '__main__':
    unittest.main()
