"""Writer-boundary regressions; synthetic reviews test routing, not semantics."""
import copy
import json
import unittest

import test_recommendation_engine as fixtures
from recommendation_engine import validate_catalog


class EngineSecurityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EngineTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.secret = 'AUTHOR_ONLY_SECRET_XULAN_IS_KILLER'
        scene = self.fixture.project['scenes'][0]
        self.public = scene['text']
        scene['text'] += ' 作者知道：' + self.secret + '，林并不知道。'

    def writer(self, annotations=None, **review_kwargs):
        state, _ = self.fixture.state(annotations, **review_kwargs)
        session, _ = self.fixture.batch(state)
        return session['current_batch']['writer_packet']

    def test_base_fact_quote_does_not_reveal_unrelated_source_secret(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        whole_scene = self.fixture.project['scenes'][0]['text']
        annotations['facts'][0].update(quote=whole_scene, end=len(whole_scene))
        # No action or candidate is needed for this leak: base facts are always
        # included, even when the writer receives no proposal.
        annotations['registry']['actions'] = []
        writer = self.writer(annotations)
        self.assertEqual(writer['proposals'], [])
        self.assertNotIn(self.secret, json.dumps(writer, ensure_ascii=False))
        for fact in writer['facts']:
            self.assertLessEqual(set(fact), {'id', 'text', 'scene_id'})

    def test_action_evidence_quote_does_not_reveal_source_secret(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        annotations['registry']['actions'][0]['anchor']['end'] = len(
            self.fixture.project['scenes'][0]['text'])
        writer = self.writer(annotations)
        self.assertTrue(writer['proposals'])
        self.assertNotIn(self.secret, json.dumps(writer, ensure_ascii=False))
        self.assertTrue(any('绑定准确' in f['text'] for f in writer['facts']))
        for fact in writer['facts']:
            self.assertLessEqual(set(fact), {'id', 'text', 'scene_id'})

    def test_author_identifiers_are_not_disclosed_to_writer(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        markers = ['fact_secret_killer_is_xu', 'scene_secret_killer_is_xu',
                   'action_secret_killer_is_xu', 'task_secret_killer_is_xu',
                   'entity_secret_killer_is_xu']
        annotations['facts'][0]['id'] = markers[0]
        self.fixture.project['scenes'][0]['id'] = markers[1]
        annotations['facts'][0]['scene_id'] = markers[1]
        action = annotations['registry']['actions'][0]
        action.update(id=markers[2], task_id=markers[3], target_ids=[markers[4]])
        action['anchor']['scene_id'] = markers[1]
        annotations['registry']['tasks'][0]['id'] = markers[3]
        annotations['registry']['entities'][0]['id'] = markers[4]
        writer = self.writer(annotations)
        self.assertTrue(writer['proposals'])
        encoded = json.dumps(writer, ensure_ascii=False)
        for marker in markers:
            self.assertNotIn(marker, encoded)
        known_fact_ids = {fact['id'] for fact in writer['facts']}
        for proposal in writer['proposals']:
            self.assertLessEqual(set(proposal['evidence_fact_ids']), known_fact_ids)

    def test_hidden_duplicate_does_not_suppress_public_action(self):
        annotations = copy.deepcopy(self.fixture.annotations)
        hidden = copy.deepcopy(annotations['registry']['actions'][0])
        hidden.update(id='hidden_completed_action', origin='observed', status='completed')
        annotations['registry']['actions'].append(hidden)
        writer = self.writer(annotations, hidden=[
            'core_binding_hidden_completed_action',
            'core_status_hidden_completed_action'])
        self.assertTrue(writer['proposals'])
        self.assertNotIn('hidden_completed_action', json.dumps(writer, ensure_ascii=False))

    def test_template_attribute_index_conversion_and_format_specs_are_rejected(self):
        for template in ('{actor.__class__}', '{actor[0]}', '{actor!r}', '{actor:>99}'):
            with self.subTest(template=template):
                catalog = copy.deepcopy(self.fixture.catalog)
                catalog['motifs'][0]['variants'][0]['proposal_template'] = template
                with self.assertRaises(ValueError):
                    validate_catalog(catalog, self.fixture.root)


if __name__ == '__main__':
    unittest.main()
