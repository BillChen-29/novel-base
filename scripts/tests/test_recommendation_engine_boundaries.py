"""Independent adapter boundary contracts; synthetic reviews do not test semantics."""
import copy
import unittest

from recommendation_session import new_session, source_token, append_scene, replace_source
from recommendation_engine import (
    prepare_state, review_state, prepare_recommendations, review_recommendations, accept_current,
)
import test_recommendation_engine as engine_fixtures

review = engine_fixtures.review


class EngineBoundaryTests(unittest.TestCase):
    def setUp(self):
        # Compose the existing fixture without inheriting or re-running its tests.
        self.fixture = engine_fixtures.EngineTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def second_action(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        annotations['registry']['entities'].append({'id': 'note_two', 'label': '第二张纸条'})
        second = copy.deepcopy(annotations['registry']['actions'][0])
        second.update(id='read_second', target_ids=['note_two'], description='读取第二张纸条')
        annotations['registry']['actions'].append(second)
        return annotations

    def retry_annotations(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        current = annotations['registry']['actions'][0]
        parent = copy.deepcopy(current)
        parent.update(id='previous_read', origin='observed', status='completed')
        current.update(repeat_of='previous_read', retry_reason='纸条出现此前没有的补写内容')
        annotations['registry']['actions'].append(parent)
        return annotations

    def test_same_card_for_two_actions_has_distinct_proposals_and_independent_acceptance(self):
        state, _ = self.fixture.state(self.second_action())
        session, request = self.fixture.batch(state)
        proposals = session['current_batch']['proposals']
        self.assertEqual(len(request['instances']), 2)
        self.assertEqual(len(proposals), 2)
        self.assertEqual({p['card_id'] for p in proposals}, {'read'})
        self.assertEqual({p['variant_id'] for p in proposals}, {'read_start'})
        self.assertEqual({p['action_id'] for p in proposals}, {'read_note', 'read_second'})
        self.assertEqual(len({p['id'] for p in proposals}), 2)
        self.assertEqual({tuple(p['target_ids']) for p in proposals}, {('note',), ('note_two',)})
        accepted = accept_current(session, proposals[0]['id'], source_token(session),
                                  session['batch_sha256'], self.fixture.catalog, self.fixture.root)
        self.assertEqual([p['proposal']['id'] for p in accepted['plans']], [proposals[0]['id']])
        self.assertEqual(accepted['current_state'], state['current_state'])
        self.assertEqual(len(accepted['current_batch']['proposals']), 2)

    def test_two_objects_one_verb_completed_first_does_not_block_second(self):
        annotations = self.second_action()
        annotations['registry']['actions'][0].update(origin='observed', status='completed')
        state, _ = self.fixture.state(annotations)
        session, request = self.fixture.batch(state)
        self.assertEqual([p['action_id'] for p in session['current_batch']['proposals']], ['read_second'])
        self.assertIn({'action_id': 'read_note', 'reason': 'action_completed'}, request['blocked_actions'])
        self.assertEqual(state['current_state']['registry']['tasks'], annotations['registry']['tasks'])
        self.assertEqual(state['current_state']['actions']['read_second']['status'], 'proposed')

    def test_legitimate_retry_requires_reviewed_reason_and_completed_parent(self):
        annotations = self.retry_annotations()
        state, request = self.fixture.state(annotations)
        session, _ = self.fixture.batch(state)
        self.assertEqual([p['action_id'] for p in session['current_batch']['proposals']], ['read_note'])
        self.assertTrue(state['current_state']['actions']['read_note']['retry_usable'])
        retry_claim = request['action_claims']['read_note']['retry']
        for review_options in ({'unknown': [retry_claim]}, {'hidden': [retry_claim]}, {'reject': [retry_claim]}):
            with self.subTest(review_options=review_options):
                unreviewed, _ = self.fixture.state(annotations, **review_options)
                blocked, request = self.fixture.batch(unreviewed)
                self.assertEqual(blocked['current_batch']['proposals'], [])
                self.assertIn({'action_id': 'read_note', 'reason': 'retry_not_established'},
                              request['blocked_actions'])
        annotations['registry']['actions'][1]['status'] = 'in_progress'
        unfinished, _ = self.fixture.state(annotations)
        blocked, request = self.fixture.batch(unfinished)
        self.assertFalse(any(p['action_id'] == 'read_note' for p in blocked['current_batch']['proposals']))
        self.assertIn({'action_id': 'read_note', 'reason': 'retry_not_established'}, request['blocked_actions'])

    def test_retry_missing_reason_cycles_and_other_object_parent_are_rejected(self):
        cases = []
        missing = self.retry_annotations()
        del missing['registry']['actions'][0]['retry_reason']
        cases.append(missing)
        cycle = self.retry_annotations()
        cycle['registry']['actions'][1].update(repeat_of='read_note', retry_reason='相互循环')
        cases.append(cycle)
        wrong_object = self.retry_annotations()
        wrong_object['registry']['entities'].append({'id': 'other', 'label': '其他纸条'})
        wrong_object['registry']['actions'][1]['target_ids'] = ['other']
        cases.append(wrong_object)
        for annotations in cases:
            with self.subTest(annotations=annotations), self.assertRaises(ValueError):
                prepare_state(new_session(self.fixture.project), annotations)

    def test_observed_in_progress_supports_only_continue_variant(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        annotations['registry']['actions'][0].update(origin='observed', status='in_progress')
        card = self.fixture.catalog['motifs'][0]
        card['conditions'][0]['claim_template'] = '{actor}已经开始{action}且仍未完成，目标为{target}，任务为{task}。'
        continuation = copy.deepcopy(card['variants'][0])
        continuation.update(id='read_continue', title='继续读取', action_states=['in_progress'],
                            proposal_template='{actor}继续{action}，目标为{target}，任务为{task}。')
        card['variants'].append(continuation)
        state, _ = self.fixture.state(annotations)
        session, _ = self.fixture.batch(state)
        self.assertEqual(state['current_state']['actions']['read_note']['status'], 'in_progress')
        self.assertEqual([p['variant_id'] for p in session['current_batch']['proposals']], ['read_continue'])
        self.assertIn('继续', session['current_batch']['proposals'][0]['text'])

    def test_adopt_then_append_does_not_turn_proposed_action_into_observed_fact(self):
        state, _ = self.fixture.state()
        session, _ = self.fixture.batch(state)
        accepted = accept_current(session, session['current_batch']['proposals'][0]['id'],
                                  source_token(session), session['batch_sha256'],
                                  self.fixture.catalog, self.fixture.root)
        changed = append_scene(accepted, dict(self.fixture.project['scenes'][0], id='s2', order=2,
                                             text='窗外又下起了雨。'), source_token(accepted))
        request = prepare_state(changed, self.fixture.annotations)
        reviewed = review_state(changed, request, review(request['packet']))
        self.assertEqual(reviewed['current_state']['actions']['read_note']['status'], 'proposed')
        self.assertEqual(reviewed['current_state']['registry']['actions'][0]['origin'], 'proposed')
        self.assertNotIn('status', request['action_claims']['read_note'])
        self.assertEqual(reviewed['source']['facts'], [])
        self.assertEqual(reviewed['plans'], accepted['plans'])
        self.assertTrue(all(not f['id'].startswith('core_status_')
                            for f in reviewed['current_state']['usable_facts']))

    def test_reported_and_pov_hidden_base_facts_do_not_enter_retrieval_or_writer_packet(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        annotations['facts'].extend([
            dict(annotations['facts'][0], id='reported', text='传闻口令 REPORTED_SECRET 纸条'),
            dict(annotations['facts'][0], id='hidden', text='私密口令 HIDDEN_SECRET 纸条'),
        ])
        session = new_session(self.fixture.project)
        request = prepare_state(session, annotations)
        decisions = review(request['packet'], hidden=['hidden'])
        next(d for d in decisions['decisions'] if d['fact_id'] == 'reported')['epistemic_type'] = 'reported'
        state = review_state(session, request, decisions)
        batch, recommendation = self.fixture.batch(state)
        self.assertEqual(recommendation['query'], '林持有未读纸条。')
        self.assertEqual([f['id'] for f in state['current_state']['base_facts']], ['base'])
        exposed = str(batch['current_batch']['writer_packet'])
        self.assertNotIn('REPORTED_SECRET', exposed)
        self.assertNotIn('HIDDEN_SECRET', exposed)

    def test_changed_review_invalidates_existing_batch_and_rejects_its_request(self):
        state, _ = self.fixture.state()
        session, recommendation_request = self.fixture.batch(state)
        state_request = prepare_state(session, self.fixture.annotations)
        original_proposal = session['current_batch']['proposals'][0]['id']
        binding = state_request['action_claims']['read_note']['binding']
        changed = review_state(session, state_request, review(state_request['packet'], unknown=[binding]))
        self.assertIsNone(changed['current_batch'])
        self.assertNotEqual(changed['state_sha256'], state['state_sha256'])
        self.assertEqual(changed['registry_history'][-1]['registry'], state['current_state']['registry'])
        with self.assertRaises(ValueError):
            accept_current(changed, original_proposal, source_token(changed), session['batch_sha256'],
                           self.fixture.catalog, self.fixture.root)
        with self.assertRaises(ValueError):
            review_recommendations(changed, recommendation_request, {}, self.fixture.catalog, self.fixture.root)
        blocked, _ = self.fixture.batch(changed)
        self.assertEqual(blocked['current_batch']['proposals'], [])

    def test_delayed_state_review_cannot_overwrite_newer_review_on_same_source(self):
        state, _ = self.fixture.state()
        first_request = prepare_state(state, self.fixture.annotations)
        binding = first_request['action_claims']['read_note']['binding']
        newer = review_state(state, first_request, review(first_request['packet'], unknown=[binding]))
        self.assertEqual(source_token(newer), source_token(state))
        self.assertNotEqual(newer['state_sha256'], state['state_sha256'])
        self.assertEqual(newer['current_state']['actions']['read_note']['status'], 'unknown')
        with self.assertRaises(ValueError):
            review_state(newer, first_request, review(first_request['packet']))
        fresh_request = prepare_state(newer, self.fixture.annotations)
        intentional_revision = review_state(newer, fresh_request, review(fresh_request['packet']))
        self.assertEqual(intentional_revision['current_state']['actions']['read_note']['status'], 'proposed')

    def test_source_edit_and_unknown_new_review_remove_prior_completion(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        annotations['registry']['actions'][0].update(origin='observed', status='completed')
        session, _ = self.fixture.state(annotations)
        self.assertEqual(session['current_state']['actions']['read_note']['status'], 'completed')
        project = copy.deepcopy(self.fixture.project)
        project['scenes'][0]['text'] = '林把纸条放进衣袋，没有再碰它。'
        changed = replace_source(session, project, source_token(session))
        refreshed = copy.deepcopy(annotations)
        refreshed['facts'] = []
        refreshed['registry']['actions'][0]['anchor']['end'] = len(project['scenes'][0]['text'])
        request = prepare_state(changed, refreshed)
        status_claim = request['action_claims']['read_note']['status']
        reviewed = review_state(changed, request, review(request['packet'], unknown=[status_claim]))
        self.assertEqual(reviewed['current_state']['actions']['read_note']['status'], 'unknown')
        self.assertNotIn(status_claim, {f['id'] for f in reviewed['current_state']['usable_facts']})
        self.assertEqual(reviewed['registry_history'][0]['registry']['actions'][0]['status'], 'completed')
        blocked, request = self.fixture.batch(reviewed)
        self.assertEqual(blocked['current_batch']['proposals'], [])
        self.assertIn({'action_id': 'read_note', 'reason': 'action_unknown'}, request['blocked_actions'])

    def test_unknown_status_and_cross_project_recommendations_fail_closed(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        annotations['registry']['actions'][0].update(origin='observed', status='unknown')
        unknown, _ = self.fixture.state(annotations)
        blocked, request = self.fixture.batch(unknown)
        self.assertEqual(blocked['current_batch']['proposals'], [])
        self.assertIn({'action_id': 'read_note', 'reason': 'action_unknown'}, request['blocked_actions'])
        first, _ = self.fixture.state()
        first, first_request = self.fixture.batch(first)
        self.fixture.project['project_id'] = 'second-project'
        second, _ = self.fixture.state()
        second, _ = self.fixture.batch(second)
        with self.assertRaises(ValueError):
            review_recommendations(second, first_request, {}, self.fixture.catalog, self.fixture.root)
        with self.assertRaises(ValueError):
            accept_current(second, first['current_batch']['proposals'][0]['id'], source_token(first),
                           first['batch_sha256'], self.fixture.catalog, self.fixture.root)
        with self.assertRaises(ValueError):
            accept_current(second, first['current_batch']['proposals'][0]['id'], source_token(second),
                           first['batch_sha256'], self.fixture.catalog, self.fixture.root)


if __name__ == '__main__':
    unittest.main()
