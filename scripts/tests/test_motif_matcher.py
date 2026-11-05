"""Behavior tests of explicit motif conditions, not model-quality evaluations."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from semantic_review import prepare_review, _digest
from motif_matcher import match_motifs, main


class MotifMatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'assets' / 'motif.md'
        self.source.parent.mkdir()
        text = '记录信息，送到对方手中，再由对方理解。\n'
        self.source.write_text(text, encoding='utf-8')
        self.catalog = {'schema_version': 1, 'status': 'experimental_operationalization', 'motifs': [{
            'id': 'message', 'title': '媒介传递', 'source': {'path': 'assets/motif.md',
                'sha256': hashlib.sha256(text.encode()).hexdigest(),
                'evidence': [{'start': 0, 'end': len(text)-1, 'quote': text[:-1]}]},
            'roles': {'receiver': 'character', 'carrier': 'object'},
            'conditions': [
                {'id': 'content', 'claim_template': '暗号是松果。', 'kind': 'content'},
                {'id': 'carrier', 'claim_template': '{carrier}上写着暗号。', 'kind': 'carrier'},
                {'id': 'received', 'claim_template': '{receiver}收到{carrier}。', 'kind': 'acquisition_event'},
                {'id': 'decoded', 'claim_template': '{receiver}读懂{carrier}。', 'kind': 'acquisition_event'}],
            'entry_conditions': ['received'],
            'stages': [
                {'id': 'delivered', 'title': '已送达', 'requires': ['received'], 'chronological': ['received']},
                {'id': 'understood', 'title': '已理解', 'requires': ['received', 'decoded'],
                 'chronological': ['received', 'decoded']}],
            'variants': [
                {'id': 'read', 'title': '解读载体', 'from_stage': 'delivered', 'requires': [],
                 'proposal': '检查手头载体，尝试理解其中的信息。'},
                {'id': 'act', 'title': '依据内容行动', 'from_stage': 'understood', 'requires': ['content'],
                 'proposal': '选择一个由已知内容支持的行动。'}]}]}
        self.project = {'schema_version': 1, 'project_id': 'atomic-test', 'title': '暗号 🔑',
            'pov_character': '阿弥', 'characters': ['阿岚', '阿弥'],
            'goal': {'id': 'recover_and_investigate', 'description': '核对收到的信息。'},
            'scenes': [
                {'id': 's1', 'order': 1, 'function': 'setup', 'tension': 2,
                 'present_characters': ['阿岚', '阿弥'],
                 'text': '暗号是松果。红信上写着暗号。阿弥收到红信。'},
                {'id': 's2', 'order': 2, 'function': 'revelation', 'tension': 2,
                 'present_characters': ['阿弥'], 'text': '阿弥读懂红信。'}],
            'facts': [
                {'id': 'content', 'text': '暗号是松果。', 'scene_id': 's1', 'quote': '暗号是松果。', 'known_by': ['阿岚', '阿弥']},
                {'id': 'carrier', 'text': '红信上写着暗号。', 'scene_id': 's1', 'quote': '红信上写着暗号。', 'known_by': ['阿岚', '阿弥']},
                {'id': 'received', 'text': '阿弥收到红信。', 'scene_id': 's1', 'quote': '阿弥收到红信。', 'known_by': ['阿弥']},
                {'id': 'decoded', 'text': '阿弥读懂红信。', 'scene_id': 's2', 'quote': '阿弥读懂红信。', 'known_by': ['阿弥']}],
            'threads': [],
            'motif_annotations': {'catalog_sha256': _digest(self.catalog),
                'atoms': [{'fact_id': c['id'], 'kind': c['kind']} for c in self.catalog['motifs'][0]['conditions']],
                'instances': [{'id': 'm1', 'motif_id': 'message',
                    'bindings': {'receiver': '阿弥', 'carrier': '红信'},
                    'condition_facts': {x: x for x in ['content', 'carrier', 'received', 'decoded']}}]}}
        self.packet = prepare_review(self.project)
        self.review = self.make_review(self.packet)

    def make_review(self, packet):
        decisions = []
        for c in packet['candidates']:
            ev = {k: c[k] for k in ('scene_id', 'start', 'end', 'quote')}
            decision = {'fact_id': c['fact_id'], 'verdict': 'supported', 'epistemic_type': 'established',
                'reason': '软件测试输入，不是模型评测。', 'evidence': [ev],
                'knowledge': [{'character_id': char, 'verdict': 'supported', 'reason': '模拟知情判断。',
                               'evidence': [ev]} for char in c['claimed_known_by']]}
            if c['fact_id'] in ('received', 'decoded'):
                decision['event_anchor'] = dict(ev, relation='occurs_here')
            decisions.append(decision)
        return {'schema_version': 1, **{k: packet[k] for k in ('project_id', 'project_sha256', 'packet_sha256')},
            'reviewer': {'kind': 'agent_review', 'name': 'test-mock'}, 'decisions': decisions,
            'chronology_review': {'verdict': 'supported', 'relation': 'forward_occurrence',
                'scene_ids': [s['id'] for s in packet['scenes']], 'reason': '模拟顺叙审核。'}}

    def run_match(self, packet=None, review=None):
        return match_motifs(self.project, packet or self.packet, review or self.review, self.catalog, self.root)

    def refresh(self, cutoff=None):
        self.project['motif_annotations']['catalog_sha256'] = _digest(self.catalog)
        self.packet = prepare_review(self.project, cutoff)
        self.review = self.make_review(self.packet)

    def test_complete_progress_and_safe_writer_packet(self):
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['current_stage'], 'understood')
        self.assertEqual([v['id'] for v in result['pov_view']['variants']], ['act'])
        self.assertEqual({f['id'] for f in result['writer_packet']['facts']}, {'content', 'received', 'decoded'})
        self.assertIn(json.dumps(result['writer_packet'], ensure_ascii=False, indent=2), result['writer_prompt'])
        self.assertNotIn('软件测试输入', result['writer_prompt'])

    def test_knowledge_kind_is_explicit_in_audit_and_writer(self):
        for kind in ('motif','technique','situation'):
            self.catalog['motifs'][0]['knowledge_kind']=kind;self.refresh()
            result=self.run_match()
            self.assertEqual(result['author_audit'][0]['knowledge_kind'],kind)
            self.assertEqual(result['writer_packet']['proposals'][0]['knowledge_kind'],kind)
        del self.catalog['motifs'][0]['knowledge_kind'];self.refresh()
        self.assertEqual(self.run_match()['writer_packet']['proposals'][0]['knowledge_kind'],'motif')

    def test_invalid_knowledge_kind_is_rejected(self):
        for kind in (None,False,[],{},'case'):
            self.catalog['motifs'][0]['knowledge_kind']=kind;self.refresh()
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.run_match()

    def test_partial_condition_questions_remain_author_only(self):
        del self.project['motif_annotations']['instances'][0]['condition_facts']['decoded']
        self.refresh()
        self.review['decisions'][1].update(verdict='contradicted')
        result=self.run_match();audit=result['author_audit'][0]
        self.assertEqual(audit['supported_condition_ids'],['content','received'])
        self.assertEqual(audit['contradicted_condition_ids'],['carrier'])
        self.assertEqual(audit['unknown_condition_ids'],['decoded'])
        question=next(c for c in audit['conditions'] if c['id']=='decoded')
        self.assertEqual(question['question'],'阿弥读懂红信。')
        self.assertIsNone(question['claim'])
        self.assertNotIn('读懂红信',result['writer_prompt'])

    def test_alternative_stages_offer_every_supported_branch_without_list_priority(self):
        motif = self.catalog['motifs'][0]
        motif['stage_mode'] = 'alternatives'
        self.refresh()
        result = self.run_match()
        audit = result['author_audit'][0]
        self.assertIsNone(audit['current_stage'])
        self.assertEqual(audit['supported_stage_ids'], ['delivered', 'understood'])
        self.assertEqual(audit['applicability_status'], 'eligible')
        self.assertEqual([v['id'] for v in result['writer_packet']['proposals']], ['read', 'act'])
        self.assertEqual([v['stage'] for v in result['writer_packet']['proposals']], ['delivered', 'understood'])
        self.assertNotIn('supported_stage_ids', result['writer_prompt'])
        motif['stages'].reverse()
        self.refresh()
        reversed_result = self.run_match()
        self.assertEqual(reversed_result['writer_packet'], result['writer_packet'])
        self.assertIsNone(reversed_result['author_audit'][0]['current_stage'])

    def test_applicability_aggregates_branches_instead_of_entry_conditions(self):
        motif = self.catalog['motifs'][0]
        motif['stage_mode'] = 'alternatives'
        motif['stages'][0].update(requires=['carrier'], chronological=[])
        motif['stages'][1].update(requires=['decoded'], chronological=[])
        for verdict, expected in [('insufficient_evidence', 'needs_evidence'), ('contradicted', 'blocked')]:
            with self.subTest(verdict=verdict):
                self.refresh()
                for index in (1, 3):
                    self.review['decisions'][index].pop('event_anchor', None)
                    self.review['decisions'][index]['verdict'] = verdict
                result = self.run_match()
                audit = result['author_audit'][0]
                self.assertEqual(audit['entry_status'], 'eligible')
                self.assertEqual(audit['applicability_status'], expected)
                self.assertEqual(audit['supported_stage_ids'], [])
                self.assertEqual(result['writer_packet']['proposals'], [])
        # One uncertain branch keeps the aggregate uncertain, even if another is blocked.
        self.review['decisions'][3]['verdict'] = 'insufficient_evidence'
        self.assertEqual(self.run_match()['author_audit'][0]['applicability_status'], 'needs_evidence')
        # Alternatives still inherit the shared entry requirements.
        self.refresh()
        self.review['decisions'][2].pop('event_anchor')
        self.review['decisions'][2]['verdict'] = 'contradicted'
        result = self.run_match()
        self.assertEqual([s['status'] for s in result['author_audit'][0]['stages']], ['blocked', 'blocked'])
        self.assertEqual(result['writer_packet']['proposals'], [])

    def test_other_alternative_uncertainty_and_hidden_progress_do_not_suppress_branch(self):
        self.catalog['motifs'][0]['stage_mode'] = 'alternatives'
        self.refresh('s1')
        prefix = self.run_match()['writer_packet']
        for state in ('unknown', 'hidden', 'missing_order'):
            with self.subTest(state=state):
                self.refresh()
                decision = self.review['decisions'][3]
                if state == 'unknown':
                    decision.pop('event_anchor')
                    decision['verdict'] = 'insufficient_evidence'
                elif state == 'hidden':
                    decision['knowledge'] = []
                else:
                    decision.pop('event_anchor')
                result = self.run_match()
                self.assertEqual(result['writer_packet'], prefix)
                self.assertFalse(result['author_audit'][0]['pov_progress_uncertain'])
                self.assertEqual(result['author_audit'][0]['applicability_status'], 'eligible')
                self.assertNotIn('读懂', result['writer_prompt'])

    def test_explicit_progression_preserves_default_selection_and_abstention(self):
        baseline = self.run_match()
        self.catalog['motifs'][0]['stage_mode'] = 'progression'
        self.refresh()
        result = self.run_match()
        self.assertEqual(result['writer_packet'], baseline['writer_packet'])
        self.assertEqual(result['author_audit'][0]['current_stage'], 'understood')
        self.assertEqual(result['author_audit'][0]['supported_stage_ids'], ['delivered', 'understood'])
        self.assertEqual(result['author_audit'][0]['applicability_status'], 'eligible')
        self.review['decisions'][3].pop('event_anchor')
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['current_stage'], 'delivered')
        self.assertTrue(result['author_audit'][0]['pov_progress_uncertain'])
        self.assertEqual(result['writer_packet']['proposals'], [])

    def test_invalid_stage_mode_is_rejected(self):
        for mode in (None, False, [], {}, 'parallel', ''):
            with self.subTest(mode=mode):
                self.catalog['motifs'][0]['stage_mode'] = mode
                self.refresh()
                with self.assertRaisesRegex(ValueError, 'invalid_stage_mode'):
                    self.run_match()

    def test_content_and_source_knowledge_remain_separate(self):
        self.review['decisions'][1]['knowledge'][1].update(verdict='insufficient_evidence', evidence=[])
        result = self.run_match()
        atoms = {a['fact_id']: a for a in result['atom_view']}
        self.assertEqual(atoms['content']['knowledge']['阿弥'], 'true')
        self.assertEqual(atoms['carrier']['knowledge']['阿弥'], 'unknown')
        self.assertEqual(atoms['carrier']['world'], 'true')

    def test_missing_knowledge_is_unknown_not_false(self):
        self.review['decisions'][0]['knowledge'] = []
        result = self.run_match()
        self.assertEqual(result['atom_view'][0]['knowledge']['阿弥'], 'unknown')
        self.assertEqual(result['writer_packet']['proposals'], [])

    def test_explicit_knowledge_contradiction_is_not_world_false(self):
        self.review['decisions'][0]['knowledge'][1]['verdict'] = 'contradicted'
        result = self.run_match()
        self.assertEqual(result['atom_view'][0]['world'], 'true')
        self.assertEqual(result['atom_view'][0]['knowledge']['阿弥'], 'false')
        self.assertEqual(result['writer_packet']['proposals'], [])

    def test_false_and_unknown_entry_are_distinct(self):
        self.review['decisions'][2].pop('event_anchor')
        self.review['decisions'][2]['verdict'] = 'contradicted'
        self.assertEqual(self.run_match()['author_audit'][0]['entry_status'], 'blocked')
        self.review['decisions'][2]['verdict'] = 'insufficient_evidence'
        self.assertEqual(self.run_match()['author_audit'][0]['entry_status'], 'needs_evidence')

    def test_reported_world_claim_cannot_become_established(self):
        self.review['decisions'][2].pop('event_anchor')
        for kind in ('reported', 'inferred', 'uncertain'):
            with self.subTest(kind=kind):
                self.review['decisions'][2]['epistemic_type'] = kind
                result = self.run_match()
                self.assertEqual(result['author_audit'][0]['entry_status'], 'needs_evidence')
                self.assertEqual(result['writer_packet']['proposals'], [])

    def test_prefix_stage_survives_unknown_future(self):
        self.refresh('s1')
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['current_stage'], 'delivered')
        self.assertEqual([v['id'] for v in result['pov_view']['variants']], ['read'])
        self.assertNotIn('读懂', result['writer_prompt'])
        self.assertNotIn('decoded', result['writer_prompt'])

    def test_reversed_event_order_blocks_advanced_stage(self):
        self.project['scenes'][0]['order'], self.project['scenes'][1]['order'] = 2, 1
        self.refresh()
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['stages'][1]['status'], 'blocked')
        self.assertEqual(result['author_audit'][0]['current_stage'], 'delivered')

    def test_hidden_later_stage_cannot_change_pov_plan(self):
        self.refresh('s1')
        prefix = self.run_match()['writer_packet']
        self.refresh()
        self.review['decisions'][3]['knowledge'] = []
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['current_stage'], 'understood')
        self.assertEqual(result['writer_packet'], prefix)

    def test_unbound_condition_and_missing_decision_are_unknown(self):
        del self.project['motif_annotations']['instances'][0]['condition_facts']['decoded']
        self.refresh()
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['conditions'][3]['world'], 'unknown')
        self.review['decisions'] = []
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['entry_status'], 'needs_evidence')

    def test_template_mismatch_cannot_relabel_a_true_fact(self):
        self.project['motif_annotations']['instances'][0]['condition_facts']['received'] = 'content'
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'condition_claim_mismatch'):
            self.run_match()

    def test_changed_project_packet_review_and_catalog_are_rejected(self):
        altered = copy.deepcopy(self.project); altered['project_id'] = 'other'
        with self.assertRaises(ValueError): match_motifs(altered, self.packet, self.review, self.catalog, self.root)
        altered_review = copy.deepcopy(self.review); altered_review['packet_sha256'] = 'bad'
        with self.assertRaises(ValueError): self.run_match(review=altered_review)
        self.catalog['motifs'][0]['title'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'catalog_binding_mismatch'): self.run_match()

    def test_source_hash_span_and_traversal_are_rejected(self):
        source = self.catalog['motifs'][0]['source']
        for field, bad in [('sha256', 'bad'), ('path', '../outside'), ('evidence', [{'start': 0, 'end': 1, 'quote': '错'}])]:
            with self.subTest(field=field):
                old = copy.deepcopy(source[field]); source[field] = bad; self.refresh()
                with self.assertRaises(ValueError): self.run_match()
                source[field] = old

    def test_source_symlink_escape_is_rejected(self):
        outside = self.root / 'private.txt'; outside.write_text('private', encoding='utf-8')
        self.source.unlink(); self.source.symlink_to(outside)
        with self.assertRaises(ValueError): self.run_match()

    def test_bad_schema_and_duplicate_identifiers_are_rejected(self):
        changes = [
            lambda c: c.update(schema_version=True),
            lambda c: c['motifs'].append(copy.deepcopy(c['motifs'][0])),
            lambda c: c['motifs'][0]['conditions'].append(copy.deepcopy(c['motifs'][0]['conditions'][0])),
            lambda c: c['motifs'][0]['stages'][0].update(requires=['missing']),
            lambda c: c['motifs'][0]['stages'][0].update(chronological=['carrier']),
            lambda c: c['motifs'][0]['conditions'][0].update(claim_template='{receiver.__class__}'),
            lambda c: c['motifs'][0]['conditions'][0].update(claim_template='{missing}'),
            lambda c: c['motifs'][0]['conditions'][0].update(claim_template='{receiver'),
            lambda c: c['motifs'][0]['conditions'][0].update(kind=[]),
            lambda c: c['motifs'][0]['variants'][0].update(from_stage='missing')]
        original = copy.deepcopy(self.catalog)
        for change in changes:
            with self.subTest(change=change):
                self.catalog = copy.deepcopy(original); change(self.catalog); self.refresh()
                with self.assertRaises(ValueError): self.run_match()

    def test_null_catalog_and_annotations_are_rejected(self):
        with self.assertRaises(ValueError):
            match_motifs(self.project, self.packet, self.review, None, self.root)
        self.project['motif_annotations'] = None
        self.packet = prepare_review(self.project); self.review = self.make_review(self.packet)
        with self.assertRaises(ValueError): self.run_match()

    def test_same_character_ids_do_not_make_reviews_cross_project(self):
        other = copy.deepcopy(self.project); other['project_id'] = 'second-story'
        other_packet = prepare_review(other)
        with self.assertRaisesRegex(ValueError, 'review_binding_mismatch'):
            match_motifs(other, other_packet, self.review, self.catalog, self.root)

    def test_order_within_one_scene_and_overlapping_locations(self):
        self.project['scenes'][0]['text'] += self.project['scenes'][1]['text']
        self.project['scenes'].pop()
        self.project['facts'][3]['scene_id'] = 's1'
        self.refresh()
        self.assertEqual(self.run_match()['author_audit'][0]['current_stage'], 'understood')

    def test_identical_or_overlapping_occurrence_spans_leave_order_unknown(self):
        self.project['scenes'][0]['text'] += self.project['scenes'][1]['text']
        self.project['scenes'].pop()
        self.project['facts'][3]['scene_id'] = 's1'
        self.refresh()
        text = self.project['scenes'][0]['text']
        start = text.index('阿弥收到红信。')
        broad = {'scene_id': 's1', 'start': start, 'end': len(text), 'quote': text[start:]}
        for decision in self.review['decisions'][2:]:
            decision['evidence'].append(broad)
            decision['event_anchor'] = dict(broad, relation='occurs_here')
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['stages'][1]['chronology'], 'unknown')
        self.assertEqual(result['author_audit'][0]['current_stage'], 'delivered')
        # Nested anchors are likewise insufficient to determine event order.
        self.review['decisions'][3]['event_anchor'] = dict(self.review['decisions'][3]['evidence'][0], relation='occurs_here')
        self.assertEqual(self.run_match()['author_audit'][0]['stages'][1]['chronology'], 'unknown')

    def test_reverse_nonoverlapping_occurrence_spans_are_contradicted(self):
        self.project['scenes'][0]['text'] = self.project['scenes'][1]['text'] + self.project['scenes'][0]['text']
        self.project['scenes'].pop()
        self.project['facts'][3]['scene_id'] = 's1'
        self.refresh()
        self.assertEqual(self.run_match()['author_audit'][0]['stages'][1]['chronology'], 'contradicted')

    def test_candidate_plan_quote_cannot_replace_actual_occurrence_anchor(self):
        self.project['scenes'][0]['text'] = self.project['scenes'][0]['text'].replace('阿弥收到红信。', '阿岚说：明天阿弥收到红信。')
        self.project['scenes'].append({'id': 's3', 'order': 3, 'function': 'action', 'tension': 2,
            'present_characters': ['阿弥'], 'text': '到了第三天，阿弥终于收到红信。'})
        self.refresh()
        quote = '阿弥终于收到红信。'
        text = self.project['scenes'][2]['text']; start = text.index(quote)
        actual = {'scene_id': 's3', 'start': start, 'end': start+len(quote), 'quote': quote}
        self.review['decisions'][2]['evidence'].append(actual)
        self.review['decisions'][2]['event_anchor'] = dict(actual, relation='occurs_here')
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['stages'][1]['chronology'], 'contradicted')
        self.assertEqual(result['author_audit'][0]['current_stage'], 'delivered')
        self.assertEqual(result['pov_view']['variants'], [])

    def test_missing_or_uncertain_sequence_review_fails_closed(self):
        self.review.pop('chronology_review')
        result = self.run_match()
        self.assertIsNone(result['author_audit'][0]['current_stage'])
        self.assertEqual(result['writer_packet']['proposals'], [])
        self.review = self.make_review(self.packet)
        self.review['chronology_review']['verdict'] = 'insufficient_evidence'
        self.assertIsNone(self.run_match()['author_audit'][0]['current_stage'])

    def test_reviewed_flashback_blocks_chronological_stages(self):
        self.review['chronology_review']['verdict'] = 'contradicted'
        result = self.run_match()
        self.assertEqual([s['status'] for s in result['author_audit'][0]['stages']], ['blocked', 'blocked'])
        self.assertEqual(result['writer_packet']['proposals'], [])

    def test_missing_anchor_cannot_use_candidate_location(self):
        self.review['decisions'][3].pop('event_anchor')
        result = self.run_match()
        self.assertEqual(result['author_audit'][0]['stages'][1]['chronology'], 'unknown')
        self.assertEqual(result['author_audit'][0]['current_stage'], 'delivered')

    def test_known_later_progress_with_missing_order_does_not_repeat_prior_action(self):
        self.review['decisions'][3].pop('event_anchor')
        result = self.run_match()
        self.assertEqual(result['writer_packet']['proposals'], [])
        self.assertTrue(result['author_audit'][0]['pov_progress_uncertain'])

    def test_known_later_progress_with_reverse_order_abstains(self):
        self.project['scenes'][0]['order'], self.project['scenes'][1]['order'] = 2, 1
        self.refresh()
        result = self.run_match()
        self.assertEqual(result['writer_packet']['proposals'], [])
        self.assertTrue(result['author_audit'][0]['pov_progress_uncertain'])

    def test_unknown_hidden_later_progress_does_not_trigger_abstention(self):
        self.review['decisions'][3].pop('event_anchor')
        self.review['decisions'][3]['knowledge'] = []
        result = self.run_match()
        self.assertEqual([v['id'] for v in result['pov_view']['variants']], ['read'])
        self.assertFalse(result['author_audit'][0]['pov_progress_uncertain'])

    def test_anchor_must_match_review_evidence_within_cutoff(self):
        original = copy.deepcopy(self.review)
        for change in [lambda a: a.update(scene_id='future'), lambda a: a.update(start=9999),
                       lambda a: a.update(quote='旧文本'), lambda a: a.update(relation='planned_here')]:
            with self.subTest(change=change):
                self.review = copy.deepcopy(original); change(self.review['decisions'][3]['event_anchor'])
                with self.assertRaises(ValueError): self.run_match()
        self.review = copy.deepcopy(original)
        other = self.review['decisions'][2]['evidence'][0]
        self.review['decisions'][3]['event_anchor'] = dict(other, relation='occurs_here')
        with self.assertRaisesRegex(ValueError, 'anchor_not_review_evidence'): self.run_match()

    def test_anchor_state_and_sequence_metadata_are_validated(self):
        original = copy.deepcopy(self.review)
        changes = [
            lambda r: r['decisions'][2].update(verdict='contradicted'),
            lambda r: r['decisions'][2].update(epistemic_type='reported'),
            lambda r: r['decisions'][2].update(event_anchor=False),
            lambda r: r['decisions'][0].update(event_anchor=dict(r['decisions'][0]['evidence'][0], relation='occurs_here')),
            lambda r: r['chronology_review'].update(verdict=False),
            lambda r: r['chronology_review'].update(relation='candidate_order'),
            lambda r: r['chronology_review'].update(reason=''),
            lambda r: r['chronology_review'].update(scene_ids=['s2','s1']),
            lambda r: r.update(chronology_review=None)]
        for change in changes:
            with self.subTest(change=change):
                self.review = copy.deepcopy(original); change(self.review)
                with self.assertRaises(ValueError): self.run_match()

    def test_no_chronology_requested_needs_no_sequence_review(self):
        for stage in self.catalog['motifs'][0]['stages']:
            stage['chronological'] = []
        self.refresh()
        self.review.pop('chronology_review')
        for decision in self.review['decisions']:
            decision.pop('event_anchor', None)
        self.assertEqual(self.run_match()['author_audit'][0]['current_stage'], 'understood')

    def test_bad_annotations_roles_and_types_are_rejected(self):
        changes = [
            lambda a: a.update(atoms=None),
            lambda a: a['atoms'].append(copy.deepcopy(a['atoms'][0])),
            lambda a: a['instances'].append(copy.deepcopy(a['instances'][0])),
            lambda a: a['instances'][0]['bindings'].update(receiver='陌生人'),
            lambda a: a['instances'][0]['bindings'].update(extra='x'),
            lambda a: a['instances'][0]['condition_facts'].update(extra='content'),
            lambda a: a['atoms'][0].update(kind='unknown'),
            lambda a: a['instances'][0].update(motif_id='unknown')]
        original = copy.deepcopy(self.project['motif_annotations'])
        for change in changes:
            with self.subTest(change=change):
                self.project['motif_annotations'] = copy.deepcopy(original); change(self.project['motif_annotations']); self.refresh()
                with self.assertRaises(ValueError): self.run_match()

    def test_no_mutation_and_deterministic_replay(self):
        before = copy.deepcopy((self.project, self.packet, self.review, self.catalog))
        first = self.run_match(); second = self.run_match()
        self.assertEqual(first, second)
        self.assertEqual(before, (self.project, self.packet, self.review, self.catalog))
        first['writer_packet']['facts'].clear()
        self.assertTrue(second['writer_packet']['facts'])

    def test_empty_motifs_and_atoms_produce_empty_plan(self):
        self.catalog['motifs'] = []
        self.project['motif_annotations'].update(atoms=[], instances=[])
        self.refresh()
        for decision in self.review['decisions']:
            decision.pop('event_anchor', None)
        self.assertEqual(self.run_match()['writer_packet'], {'facts': [], 'proposals': []})

    def test_cli_success_and_invalid_json_are_bounded(self):
        args = []
        for flag, value in [('project', self.project), ('packet', self.packet), ('review', self.review), ('catalog', self.catalog)]:
            path = self.root / (flag + '.json'); path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            args += ['--'+flag, str(path)]
        args += ['--repo-root', str(self.root)]
        out = io.StringIO()
        with redirect_stdout(out): self.assertEqual(main(args), 0)
        self.assertEqual(json.loads(out.getvalue())['project_id'], 'atomic-test')
        (self.root/'review.json').write_text('{invalid', encoding='utf-8')
        with redirect_stderr(io.StringIO()): self.assertEqual(main(args), 1)


if __name__ == '__main__':
    unittest.main()
