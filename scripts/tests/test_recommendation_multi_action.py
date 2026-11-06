"""Synthetic contracts for a shared budget across distinct reviewed action IDs."""
import copy
import unittest

import test_recommendation_engine as contracts
from recommendation_engine import (accept_current, prepare_recommendations,
                                   prepare_retrieval_embeddings, review_recommendations)
from recommendation_session import source_token
from retrieval_pilot import bm25_rank
from test_recommendation_vector import artifact


class MultiActionTests(unittest.TestCase):
    setUp = contracts.EngineTests.setUp
    state = contracts.EngineTests.state

    def card(self, name, *operations):
        card = copy.deepcopy(self.catalog['motifs'][0])
        card['id'] = name
        card['variants'][0]['operations'] = list(operations)
        return card

    def two_actions(self):
        annotations = copy.deepcopy(self.annotations)
        actions = annotations['registry']['actions']
        actions.append(dict(actions[0], id='check_note', operation='check'))
        return annotations

    def prepare(self, state, policy='action_coverage', **kwargs):
        return prepare_recommendations(state, self.catalog, self.root,
                                       candidate_policy=policy, **kwargs)

    def test_displaces_redundant_hit_beyond_rank_50_for_all_methods(self):
        state, _ = self.state(self.two_actions())
        cards = [self.card(f'r_{i:02}', 'read') for i in range(51)]
        cards.append(self.card('z_check', 'check'))
        self.catalog['motifs'] = cards
        bundle = prepare_retrieval_embeddings(state, self.catalog, self.root)
        cache = artifact(bundle)
        lexical = bm25_rank(bundle['dataset']['query'], [
            dict(source_path=c['id'], chunk_id=c['id'], title=c['title'], text=c['retrieval_text'])
            for c in cards])
        self.assertEqual(lexical[-1]['source_path'], 'z_check')
        expected_scores = {'bm25': lexical[-1]['score'], 'vector': 1., 'hybrid': 2 / (60 + 52)}
        for method, score in expected_scores.items():
            with self.subTest(method=method):
                options = dict(top_k=2, retrieval_method=method, embedding_artifact=cache)
                prior = self.prepare(state, 'action_compatible', **options)
                request = self.prepare(state, **options)
                self.assertEqual([h['source_path'] for h in prior['ranking']], ['r_00', 'r_01'])
                self.assertEqual(request['ranking'], [prior['ranking'][0],
                    dict(source_path='z_check', chunk_id='z_check', score=score)])
                self.assertEqual(request.get('retrieval_provenance'), prior.get('retrieval_provenance'))
                self.assertEqual(request['compatible_card_ids'], prior['compatible_card_ids'])
                self.assertEqual(request['covered_action_ids'], ['check_note', 'read_note'])

    def test_multi_action_card_wins_then_fill_restores_rank_before_review(self):
        annotations = self.two_actions()
        self.catalog['motifs'] = [self.card('a_read', 'read'), self.card('b_check', 'check'),
                                  self.card('c_shared', 'read', 'check'),
                                  self.card('d_shared', 'read', 'check')]
        for reverse in (False, True):
            if reverse:
                annotations['registry']['actions'].reverse()
            state, _ = self.state(annotations)
            shared_only = self.prepare(state, top_k=1)
            self.assertEqual([h['source_path'] for h in shared_only['ranking']], ['c_shared'])
            request = self.prepare(state, top_k=2)
            self.assertEqual([h['source_path'] for h in request['ranking']], ['a_read', 'c_shared'])
            self.assertEqual([i['card_id'] for i in request['instances'] if i['action_id'] == 'read_note'],
                             ['a_read', 'c_shared'])
            self.assertEqual(len(request['instances']), 3)

    def test_distinct_action_ids_with_same_operation_outweigh_one_other_action(self):
        annotations = self.two_actions()
        registry = annotations['registry']
        registry['entities'].append(dict(id='receipt', label='单据'))
        registry['actions'].append(dict(registry['actions'][0], id='read_receipt', target_ids=['receipt']))
        state, _ = self.state(annotations)
        self.catalog['motifs'] = [self.card('a_check', 'check'), self.card('b_read', 'read')]
        request = self.prepare(state, top_k=1)
        self.assertEqual([h['source_path'] for h in request['ranking']], ['b_read'])
        self.assertEqual(request['covered_action_ids'], ['read_note', 'read_receipt'])

    def test_second_slot_counts_only_new_actions_after_partial_overlap(self):
        annotations = self.two_actions()
        actions = annotations['registry']['actions']
        for operation in ('use', 'respond', 'investigate'):
            actions.append(dict(actions[0], id=operation + '_note', operation=operation))
        state, _ = self.state(annotations)
        overlap = self.card('b_overlap', 'read', 'check', 'respond')
        overlap['variants'].append(dict(overlap['variants'][0], id='duplicate_match'))
        self.catalog['motifs'] = [self.card('a_first', 'read', 'check', 'use'), overlap,
                                  self.card('c_new', 'respond', 'investigate')]
        request = self.prepare(state, top_k=2)
        self.assertEqual([h['source_path'] for h in request['ranking']], ['a_first', 'c_new'])
        self.assertEqual(request['covered_action_ids'], sorted(a['id'] for a in actions))

    def test_blocked_actions_and_crossed_variant_do_not_gain_coverage(self):
        annotations = self.two_actions()
        self.project['characters'].append('陈')
        registry = annotations['registry']
        registry['characters'].append({'id': 'chen', 'label': '陈'})
        read, check = registry['actions']
        check.update(origin='observed', status='in_progress')
        registry['actions'].extend([dict(read, id='other_actor', actor_id='chen', operation='use'),
                                    dict(read, id='done', origin='observed', status='completed',
                                         operation='respond')])
        state, _ = self.state(annotations)
        wrong = self.card('b_ineligible', 'check', 'use', 'respond')
        wrong['variants'].append(dict(wrong['variants'][0], id='cross', operations=['use'],
                                      action_states=['in_progress']))
        self.catalog['motifs'] = [self.card('a_read', 'read'), wrong]
        request = self.prepare(state)
        self.assertEqual(request['compatible_card_ids'], ['a_read'])
        self.assertEqual(request['covered_action_ids'], ['read_note'])
        self.assertEqual({b['action_id'] for b in request['blocked_actions']}, {'done', 'other_actor'})

    def test_zero_one_and_equally_covered_actions_keep_original_hits_and_scores(self):
        self.catalog['motifs'] = [self.card(name, 'read', 'check') for name in ('b', 'a', 'c')]
        for count in (0, 1, 2):
            annotations = self.two_actions()
            del annotations['registry']['actions'][count:]
            state, _ = self.state(annotations)
            cache = artifact(prepare_retrieval_embeddings(state, self.catalog, self.root))
            for method in ('bm25', 'vector', 'hybrid'):
                with self.subTest(count=count, method=method):
                    options = dict(retrieval_method=method, top_k=2, embedding_artifact=cache)
                    prior = self.prepare(state, 'action_compatible', **options)
                    request = self.prepare(state, **options)
                    for key in ('ranking', 'instances', 'compatible_card_ids'):
                        self.assertEqual(request[key], prior[key])

    def test_no_lexical_hit_means_no_reservation_and_empty_query_returns_no_hits(self):
        state, _ = self.state(self.two_actions())
        absent = self.card('a_no_hit', 'read', 'check')
        absent.update(title='xyz', retrieval_text='xyz')
        self.catalog['motifs'] = [absent, self.card('b_read', 'read')]
        request = self.prepare(state)
        self.assertEqual(request['compatible_card_ids'], ['a_no_hit', 'b_read'])
        self.assertEqual([h['source_path'] for h in request['ranking']], ['b_read'])
        self.assertEqual(request['covered_action_ids'], ['read_note'])
        annotations = self.two_actions()
        annotations['facts'] = []
        state, _ = self.state(annotations)
        for method in ('bm25', 'vector', 'hybrid'):
            request = self.prepare(state, retrieval_method=method)
            self.assertEqual((request['ranking'], request['covered_action_ids']), ([], []))

    def test_even_zero_budget_and_zero_actions_validate_the_whole_artifact(self):
        annotations = self.two_actions()
        annotations['registry']['actions'] = []
        state, _ = self.state(annotations)
        cache = artifact(prepare_retrieval_embeddings(state, self.catalog, self.root))
        cache['embeddings']['vectors'].pop(next(iter(cache['embeddings']['vectors'])))
        for method in ('bm25', 'vector', 'hybrid'):
            for budget in (0, 2):
                with self.subTest(method=method, budget=budget), self.assertRaises(ValueError):
                    self.prepare(state, retrieval_method=method, embedding_artifact=cache, top_k=budget)
        for method in ('vector', 'hybrid'):
            with self.assertRaisesRegex(ValueError, 'embedding_artifact_required'):
                self.prepare(state, retrieval_method=method, top_k=0)

    def test_policy_binding_semantic_review_and_author_only_metadata(self):
        annotations = self.two_actions()
        state, _ = self.state(annotations)
        self.catalog['motifs'] = [self.card('private_card', 'read', 'check')]
        request = self.prepare(state)
        priors = [self.prepare(state, p) for p in ('global', 'action_compatible')]
        self.assertTrue(all(prior['instances'] == request['instances'] for prior in priors))
        for prior in priors:
            self.assertNotIn('covered_action_ids', prior)
        self.assertNotIn('candidate_policy', priors[0])
        reviews = {}
        for instance in request['instances']:
            packet = instance['prepared']['packet']
            unknown = [c['fact_id'] for c in packet['candidates']] if instance['action_id'] == 'read_note' else []
            reviews[instance['id']] = contracts.review(packet, unknown=unknown)
        def review(request):
            return review_recommendations(state, request, reviews, self.catalog, self.root)
        ready = review(request)
        batch = ready['current_batch']
        self.assertEqual([p['action_id'] for p in batch['proposals']], ['check_note'])
        audit = batch['author_audit']
        self.assertEqual(audit['candidate_policy'], 'action_coverage')
        self.assertEqual(audit['compatible_card_ids'], ['private_card'])
        self.assertEqual(audit['covered_action_ids'], ['check_note', 'read_note'])
        for value in ('covered_action_ids', 'compatible_card_ids', 'candidate_policy', 'private_card',
                      'read_note', 'check_note', 'action_coverage', 'ranking'):
            self.assertNotIn(value, str(batch['writer_packet']))
        accepted = accept_current(ready, batch['proposals'][0]['id'], source_token(ready),
                                  ready['batch_sha256'], self.catalog, self.root)
        self.assertEqual(accepted['source'], state['source'])
        self.assertEqual(accepted['current_state'], state['current_state'])
        for prior in priors:
            old_batch = review(prior)['current_batch']
            self.assertNotIn('covered_action_ids', old_batch['author_audit'])
            self.assertNotEqual(old_batch['request_sha256'], batch['request_sha256'])
            self.assertNotEqual(old_batch['proposals'][0]['id'], batch['proposals'][0]['id'])
        for change in ({'candidate_policy':'action_compatible'}, {'covered_action_ids': []},
                       {'compatible_card_ids': []}, {'ranking': []}, {'instances': request['instances'][:1]}):
            with self.subTest(change=list(change)), self.assertRaisesRegex(ValueError, 'request_changed_or_stale'):
                review({**request, **change})
        for prior in priors:
            with self.assertRaisesRegex(ValueError, 'request_changed_or_stale'):
                review({**prior, 'candidate_policy':'action_coverage'})
        with self.assertRaisesRegex(ValueError, 'instance_review_coverage'):
            review_recommendations(state, request, {}, self.catalog, self.root)


if __name__ == '__main__':
    unittest.main()
