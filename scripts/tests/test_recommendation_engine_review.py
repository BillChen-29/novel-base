"""Adversarial adapter contracts; decisions are synthetic, not semantic scores."""
import copy
import unittest

import test_recommendation_engine as contracts
from recommendation_engine import (prepare_state, review_state, prepare_recommendations,
                                   review_recommendations)
from recommendation_session import new_session, append_scene, source_token


class AdversarialEngineTests(unittest.TestCase):
    setUp = contracts.EngineTests.setUp
    state = contracts.EngineTests.state
    batch = contracts.EngineTests.batch

    def test_completed_identity_cannot_be_reset_to_unobserved_proposal(self):
        annotations = copy.deepcopy(self.annotations)
        annotations['registry']['actions'][0].update(origin='observed', status='completed')
        session, _ = self.state(annotations)
        reset = copy.deepcopy(annotations)
        reset['registry']['actions'][0].update(origin='proposed', status='proposed')
        with self.assertRaisesRegex(ValueError, 'observed_action_cannot_become_proposal'):
            prepare_state(session, reset)
        newer = append_scene(session, dict(self.project['scenes'][0], id='s2', order=2),
                             source_token(session))
        with self.assertRaisesRegex(ValueError, 'observed_action_cannot_become_proposal'):
            prepare_state(newer, reset)

    def test_stale_pending_state_review_cannot_overwrite_newer_review(self):
        session = new_session(self.project)
        pending = prepare_state(session, self.annotations)
        current = review_state(session, pending, contracts.review(
            pending['packet'], hidden=['core_binding_read_note']))
        with self.assertRaisesRegex(ValueError, 'state_request_changed_or_stale'):
            review_state(current, pending, contracts.review(pending['packet']))

    def test_same_card_preserves_two_different_action_instances(self):
        annotations = copy.deepcopy(self.annotations)
        annotations['registry']['entities'].append({'id': 'receipt', 'label': '单据'})
        second = copy.deepcopy(annotations['registry']['actions'][0])
        second.update(id='read_receipt', target_ids=['receipt'], description='读取单据')
        annotations['registry']['actions'].append(second)
        session, _ = self.state(annotations)
        ready, request = self.batch(session)
        proposals = ready['current_batch']['proposals']
        self.assertEqual(len(request['instances']), 2)
        self.assertEqual({p['action_id'] for p in proposals}, {'read_note', 'read_receipt'})
        self.assertEqual(len({p['id'] for p in proposals}), 2)
        facts = {f['id']: f for f in ready['current_batch']['writer_packet']['facts']}
        self.assertEqual(len(facts), len(ready['current_batch']['writer_packet']['facts']))
        writer_proposals = ready['current_batch']['writer_packet']['proposals']
        self.assertEqual({p['id'] for p in writer_proposals}, {p['id'] for p in proposals})
        for proposal in writer_proposals:
            self.assertTrue(set(proposal['evidence_fact_ids']) <= set(facts))
        evidence_sets = [set(p['evidence_fact_ids']) for p in writer_proposals]
        self.assertTrue(all(evidence_sets))
        writer_ids = ready['current_batch']['author_audit']['writer_fact_ids']
        distinct_proofs = {writer_ids[fid] for fid in session['current_state']['distinct_targets'].values()}
        self.assertTrue(distinct_proofs)
        self.assertEqual(evidence_sets[0] & evidence_sets[1], distinct_proofs)
        instance_by_action = {i['action_id']: i['id'] for i in request['instances']}
        for proposal in proposals:
            condition_proofs = {fid for fid in proposal['evidence_fact_ids']
                                if fid.startswith(instance_by_action[proposal['action_id']] + ':')}
            self.assertTrue(condition_proofs)
            writer_proposal = next(p for p in writer_proposals if p['id'] == proposal['id'])
            self.assertTrue({writer_ids[fid] for fid in condition_proofs}
                            <= set(writer_proposal['evidence_fact_ids']))
        self.assertFalse(set(facts) & set(writer_ids))
        for ident in facts:
            self.assertRegex(ident, r'^fact_[0-9a-f]{64}$')

    def test_complete_reviews_remain_in_detached_author_audit(self):
        session = new_session(self.project)
        request = prepare_state(session, self.annotations)
        state_review = contracts.review(request['packet'])
        state_review['decisions'][0]['reason'] = 'AUTHOR_STATE_DIAGNOSTIC'
        reviewed = review_state(session, request, state_review)
        self.assertEqual(reviewed['current_state']['author_audit']['imported_review'], state_review)
        state_review['decisions'][0]['reason'] = 'changed after install'
        self.assertEqual(reviewed['current_state']['author_audit']['imported_review']['decisions'][0]['reason'],
                         'AUTHOR_STATE_DIAGNOSTIC')
        candidates = prepare_recommendations(reviewed, self.catalog, self.root)
        reviews = {i['id']: contracts.review(i['prepared']['packet']) for i in candidates['instances']}
        for review in reviews.values():
            review['decisions'][0]['reason'] = 'AUTHOR_CONDITION_DIAGNOSTIC'
        ready = review_recommendations(reviewed, candidates, reviews, self.catalog, self.root)
        for audit in ready['current_batch']['author_audit']['matches']:
            self.assertEqual(audit['imported_review'], reviews[audit['instance_id']])
            self.assertEqual(set(audit['fact_claims']),
                             {d['fact_id'] for d in audit['imported_review']['decisions']})
            reviews[audit['instance_id']]['decisions'][0]['reason'] = 'changed after install'
            self.assertEqual(audit['imported_review']['decisions'][0]['reason'], 'AUTHOR_CONDITION_DIAGNOSTIC')
        writer = str(ready['current_batch']['writer_packet'])
        self.assertNotIn('AUTHOR_STATE_DIAGNOSTIC', writer)
        self.assertNotIn('AUTHOR_CONDITION_DIAGNOSTIC', writer)

    def test_retry_needs_terminal_parent_and_reviewed_new_basis(self):
        annotations = copy.deepcopy(self.annotations)
        retry = annotations['registry']['actions'][0]
        parent = copy.deepcopy(retry)
        parent.update(id='earlier_read', origin='observed', status='completed')
        retry.update(repeat_of='earlier_read', retry_reason='新出现的墨迹需要重新读取')
        annotations['registry']['actions'].append(parent)
        session, request = self.state(annotations)
        ready, _ = self.batch(session)
        self.assertEqual([p['action_id'] for p in ready['current_batch']['proposals']], ['read_note'])
        retry_claim = request['action_claims']['read_note']['retry']
        unknown, _ = self.state(annotations, unknown=[retry_claim])
        self.assertFalse(self.batch(unknown)[0]['current_batch']['proposals'])
        parent['status'] = 'in_progress'
        active, _ = self.state(annotations)
        self.assertFalse(self.batch(active)[0]['current_batch']['proposals'])

    def test_registry_history_prevents_rebinding_and_removal(self):
        session, _ = self.state()
        newer = append_scene(session, dict(self.project['scenes'][0], id='s2', order=2),
                             source_token(session))
        rebound = copy.deepcopy(self.annotations)
        rebound['registry']['entities'][0]['label'] = '另外的纸条'
        with self.assertRaisesRegex(ValueError, 'registry_identity_rebound'):
            prepare_state(newer, rebound)
        removed = copy.deepcopy(self.annotations)
        removed['registry']['actions'].clear()
        with self.assertRaisesRegex(ValueError, 'registry_identity_removed'):
            prepare_state(newer, removed)

    def test_supported_condition_without_pov_knowledge_cannot_recommend(self):
        session, _ = self.state()
        request = prepare_recommendations(session, self.catalog, self.root)
        reviews = {instance['id']: contracts.review(instance['prepared']['packet'], hidden=[
            candidate['fact_id'] for candidate in instance['prepared']['packet']['candidates']])
            for instance in request['instances']}
        ready = review_recommendations(session, request, reviews, self.catalog, self.root)
        self.assertFalse(ready['current_batch']['proposals'])

    def paired_target_annotations(self, label='那张纸条'):
        annotations = copy.deepcopy(self.annotations)
        previous = copy.deepcopy(annotations['registry']['actions'][0])
        previous.update(id='previous_read', origin='observed', status='completed')
        annotations['registry']['actions'].append(previous)
        annotations['registry']['entities'].append({'id': 'other_note', 'label': label})
        annotations['registry']['actions'][0].update(target_ids=['other_note'], description='读取' + label)
        return annotations

    def test_alias_ids_need_supported_pov_distinction_from_completed_target(self):
        annotations = self.paired_target_annotations()
        session = new_session(self.project)
        request = prepare_state(session, annotations)
        self.assertEqual(len(request['distinct_target_claims']), 1)
        distinct = next(iter(request['distinct_target_claims'].values()))
        for verdict in ('unknown', 'reject', 'hidden'):
            with self.subTest(verdict=verdict):
                state = review_state(session, request, contracts.review(
                    request['packet'], **{verdict: [distinct]}))
                ready, recommendation = self.batch(state)
                self.assertEqual(state['current_state']['distinct_targets'], {})
                self.assertEqual(ready['current_batch']['proposals'], [])
                self.assertIn({'action_id': 'read_note', 'reason': 'target_identity_unresolved'},
                              recommendation['blocked_actions'])

    def test_reviewed_distinct_object_can_proceed_after_other_object_completed(self):
        annotations = self.paired_target_annotations(label='第二张纸条')
        session, request = self.state(annotations)
        self.assertEqual(session['current_state']['distinct_targets'], request['distinct_target_claims'])
        ready, _ = self.batch(session)
        self.assertEqual([p['action_id'] for p in ready['current_batch']['proposals']], ['read_note'])

    def test_hidden_peer_does_not_require_disclosing_target_distinction(self):
        annotations = self.paired_target_annotations(label='第二张纸条')
        annotations['registry']['entities'][0]['label'] = '暗室里的纸条'
        annotations['registry']['actions'][1]['description'] = '读取暗室里的纸条'
        session = new_session(self.project)
        request = prepare_state(session, annotations)
        hidden = list(request['action_claims']['previous_read'].values())
        distinct = list(request['distinct_target_claims'].values())
        state = review_state(session, request, contracts.review(
            request['packet'], hidden=hidden, unknown=distinct))
        ready, _ = self.batch(state)
        self.assertEqual(state['current_state']['distinct_targets'], {})
        self.assertEqual([p['action_id'] for p in ready['current_batch']['proposals']], ['read_note'])
        self.assertNotIn('暗室里的纸条', str(ready['current_batch']['writer_packet']))

    def test_target_subset_or_superset_cannot_bypass_completed_operation(self):
        for current_targets, previous_targets in ((['other_note'], ['note', 'other_note']),
                                                  (['note', 'other_note'], ['note'])):
            with self.subTest(current=current_targets, previous=previous_targets):
                annotations = self.paired_target_annotations(label='第二张纸条')
                annotations['registry']['actions'][0]['target_ids'] = current_targets
                annotations['registry']['actions'][1]['target_ids'] = previous_targets
                state, _ = self.state(annotations)
                self.assertTrue(state['current_state']['distinct_targets'])
                ready, request = self.batch(state)
                self.assertEqual(ready['current_batch']['proposals'], [])
                self.assertIn({'action_id': 'read_note', 'reason': 'overlapping_operation_completed'},
                              request['blocked_actions'])

    def new_check_annotations(self, source_text):
        self.project['scenes'][0]['text'] = source_text
        annotations = copy.deepcopy(self.annotations)
        annotations['facts'][0].update(text=source_text, quote=source_text, end=len(source_text))
        action = annotations['registry']['actions'][0]
        action.update(id='check_note', operation='check', description='核对纸条上的编号')
        action['anchor']['end'] = len(source_text)
        card = self.catalog['motifs'][0]
        card.update(title='当前核对', retrieval_text='纸条 线索 核对 编号 未解决')
        card['conditions'][0].update(id='available', claim_template=
            '{actor}仍可接触并核对{target}，任务{task}的问题尚未解决，行动是{action}。')
        card['stages'][0]['requires'] = ['available']
        card['variants'][0]['operations'] = ['check']
        return annotations

    def test_new_proposal_requires_review_of_prior_execution(self):
        annotations = self.new_check_annotations('林已经核对完纸条上的编号，仍没解决问题。纸条还在桌上，可以再次核对。')
        session = new_session(self.project)
        request = prepare_state(session, annotations)
        fresh = request['action_claims']['check_note']['fresh']
        for verdict in ('reject', 'unknown', 'hidden'):
            with self.subTest(verdict=verdict):
                state = review_state(session, request, contracts.review(
                    request['packet'], **{verdict: [fresh]}))
                self.assertTrue(state['current_state']['actions']['check_note']['binding_usable'])
                self.assertEqual(state['current_state']['actions']['check_note']['status'], 'unknown')
                ready, _ = self.batch(state)
                self.assertEqual(ready['current_batch']['proposals'], [])

    def test_fresh_proposal_does_not_require_an_existing_plan(self):
        annotations = self.new_check_annotations('林手中有纸条，编号未曾与账本核对。纸条和账本都在桌上，问题仍未解决。')
        state, request = self.state(annotations)
        self.assertIn('fresh', request['action_claims']['check_note'])
        self.assertNotIn('status', request['action_claims']['check_note'])
        self.assertEqual(state['current_state']['actions']['check_note']['status'], 'proposed')
        ready, _ = self.batch(state)
        self.assertEqual([p['action_id'] for p in ready['current_batch']['proposals']], ['check_note'])


if __name__ == '__main__':
    unittest.main()
