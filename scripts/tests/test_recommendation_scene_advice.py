"""Author-side pacing advice over reviewed, accepted action sessions."""
import copy
from pathlib import Path
import unittest

import narrative_prototype
import test_recommendation_engine as contracts
from recommendation_engine import accept_current
from recommendation_scene_advice import prepare_scene_advice
from recommendation_session import append_scene, install_batch, source_token

ASSETS_ROOT = Path(narrative_prototype.__file__).resolve().parents[1]


class SceneAdviceTests(unittest.TestCase):
    setUp = contracts.EngineTests.setUp
    state = contracts.EngineTests.state
    batch = contracts.EngineTests.batch

    def session(self):
        self.project['goal']['description'] = '原目标中的作者秘密'
        self.project['scenes'][0]['tension'] = 5
        second = dict(self.project['scenes'][0], id='s2', order=2,
                      text='林辨认出纸条是收据。作者独知的秘密在桥底。', tension=5)
        self.project['scenes'].append(second)
        fact = self.annotations['facts'][0]
        for ident, text in [('answer', '林辨认出纸条是收据。'), ('hidden', '作者独知的秘密在桥底。')]:
            self.annotations['facts'].append(dict(fact, id=ident, text=text, quote=second['text'],
                                                  scene_id='s2', start=0, end=len(second['text'])))
        session, _ = self.state(hidden=['hidden'])
        ready, _ = self.batch(session)
        proposal_id = ready['current_batch']['proposals'][0]['id']
        accepted = accept_current(ready, proposal_id, source_token(ready), ready['batch_sha256'],
                                  self.catalog, self.root)
        return ready, accepted, proposal_id

    def thread(self, **kwargs):
        return [dict(dict(id='t', description='作者私有线索描述', status='open',
                          setup_fact_ids=['base'], resolution_fact_id='answer',
                          reveal_allowed=True), **kwargs)]

    def advice(self, session, proposal_id, **options):
        options = dict(dict(goal_id='recover_and_investigate', expected_token=source_token(session),
                            expected_batch_sha256=session['batch_sha256']), **options)
        return prepare_scene_advice(session, proposal_id, ASSETS_ROOT, **options)

    def test_acceptance_current_source_and_batch_are_required(self):
        ready, accepted, proposal_id = self.session()
        with self.assertRaisesRegex(ValueError, 'not_accepted'):
            self.advice(ready, proposal_id)
        old_token = source_token(accepted)
        for token in (dict(old_token, project_id='other'), dict(old_token, revision=True)):
            with self.assertRaises(ValueError):
                self.advice(accepted, proposal_id, expected_token=token)
        with self.assertRaises(ValueError):
            self.advice(accepted, proposal_id, expected_batch_sha256='f' * 64)
        with self.assertRaises(ValueError):
            self.advice(accepted, 'foreign_proposal')
        # An accepted intention for a previous batch does not authorize the same
        # proposal ID in a newly installed batch for this very source revision.
        replacement = copy.deepcopy(ready['current_batch'])
        replacement['author_audit']['review_note'] = 'rechecked'
        reissued = install_batch(accepted, replacement, old_token)
        with self.assertRaisesRegex(ValueError, 'not_accepted'):
            self.advice(reissued, proposal_id)
        updated = append_scene(accepted, dict(self.project['scenes'][-1], id='s3', order=3),
                               old_token)
        with self.assertRaises(ValueError):
            self.advice(updated, proposal_id, expected_token=old_token)
        with self.assertRaises(ValueError):
            self.advice(updated, proposal_id)
        self.assertEqual(len(updated['plans']), 1)

    def test_only_reviewed_facts_and_source_backed_author_advice_leave_the_adapter(self):
        _, accepted, proposal_id = self.session()
        original = copy.deepcopy(accepted)
        recover = self.advice(accepted, proposal_id, threads=self.thread())
        pressure = self.advice(accepted, proposal_id, goal_id='raise_pressure', threads=self.thread())
        self.assertEqual(recover['strategies'][0]['id'], 'aftermath_clue')
        self.assertEqual(pressure['strategies'][0]['id'], 'escalate_pressure')
        self.assertEqual([scene['tension'] for scene in recover['rhythm']], [5, 5])
        for field in ('token', 'state_sha256', 'batch_sha256', 'proposal_id', 'action_id', 'known_fact_ids'):
            self.assertEqual(pressure[field], recover[field])
        self.assertEqual(recover['proposal_id'], proposal_id)
        self.assertEqual(set(recover['known_fact_ids']), {'answer', 'base'})
        for strategy in recover['strategies']:
            self.assertLessEqual(set(strategy['evidence_fact_ids']), {'answer', 'base'})
            self.assertTrue(strategy['source_refs'])
            for ref in strategy['source_refs']:
                self.assertTrue((ASSETS_ROOT / ref['path']).is_file())
                self.assertEqual(len(ref['sha256']), 64)
        for private in ('作者独知的秘密', '作者私有线索描述', '原目标中的作者秘密', 'core_binding',
                        'writer_prompt', 'context_packet', 'beats', 'accepted_intent', 'creative_proposal'):
            self.assertNotIn(private, str(recover))
        self.assertEqual(accepted, original)

    def test_thread_inputs_are_open_annotations_of_reviewed_base_facts_only(self):
        _, accepted, proposal_id = self.session()
        for change in ({'status': 'resolved'}, {'setup_fact_ids': []}, {'setup_fact_ids': ['missing']},
                       {'setup_fact_ids': ['core_binding_read_note']}, {'resolution_fact_id': 'hidden'},
                       {'extra': 'private'}, {'reveal_allowed': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.advice(accepted, proposal_id, threads=self.thread(**change))
        with self.assertRaises(ValueError):
            self.advice(accepted, proposal_id, goal_id='custom_secret')
        without = self.advice(accepted, proposal_id)
        self.assertEqual(without['strategies'], [])

    def test_reveal_advice_obeys_author_permission_and_order_of_reviewed_evidence(self):
        _, accepted, proposal_id = self.session()
        for change, allowed in (({}, True), ({'reveal_allowed': False}, False),
                                ({'resolution_fact_id': None}, False),
                                ({'setup_fact_ids': ['answer'], 'resolution_fact_id': 'base'}, False)):
            with self.subTest(change=change):
                result = self.advice(accepted, proposal_id, goal_id='reveal_truth',
                                     threads=self.thread(**change))
                ids = [s['id'] for s in result['strategies']]
                self.assertEqual('earned_reveal' in ids, allowed)
                if allowed:
                    self.assertEqual(ids[0], 'earned_reveal')


if __name__ == '__main__':
    unittest.main()
