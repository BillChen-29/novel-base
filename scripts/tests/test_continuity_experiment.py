"""Contracts for a local novel continuity experiment, without models or real books."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from continuity_experiment import build_knowledge_records, query_variants, validate_case, validate_vectors, write_html


class ContinuityContracts(unittest.TestCase):
    def case(self):
        return {'id': 'demo', 'prefix': '林舟拿着钥匙。\n他来到门前。', 'actual_next': '门开了。',
                'prefix_start': 0, 'prefix_end': 14, 'next_start': 14, 'next_end': 18,
                'characters': ['林舟'], 'pov_character': '林舟',
                'order_review': {'eligible': True, 'reason': '逐句检查：动作顺序前进'},
                'goal': '尝试打开门', 'facts': [{'id': 'f1', 'text': '林舟持有钥匙', 'quote': '林舟拿着钥匙。',
                                              'epistemic_status': 'explicit', 'known_by': ['林舟']}]}

    def test_query_inputs_never_use_sealed_continuation(self):
        original = self.case()
        changed = copy.deepcopy(original)
        changed['actual_next'] = '另一个结局，未来的名字和密码。'
        self.assertEqual(query_variants(original), query_variants(changed))
        self.assertNotIn('未来', str(query_variants(changed)))

    def test_invalid_quotes_and_unreviewed_order_are_rejected(self):
        original = self.case()
        validate_case(original)
        for key in ('quote', 'order', 'future'):
            changed = copy.deepcopy(original)
            if key == 'quote': changed['facts'][0]['quote'] = '未在前文发生。'
            if key == 'order': changed['order_review']['eligible'] = False
            if key == 'future': changed['next_start'] = changed['prefix_end'] - 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_case(changed)

    def test_state_query_keeps_fact_status_and_original_text_query_is_bounded(self):
        case = self.case()
        case['facts'][0]['epistemic_status'] = 'character_claim'
        result = query_variants(case)
        self.assertIn('character_claim', result['state'])
        self.assertIn('林舟持有钥匙', result['state'])
        case['prefix'] = '甲' * 2000
        self.assertEqual(query_variants(case)['raw'], '甲' * 800)

    def test_unknown_knowledge_entity_is_rejected(self):
        case = self.case()
        case['facts'][0]['known_by'] = ['另一本书人物']
        with self.assertRaisesRegex(ValueError, 'Unknown character'):
            validate_case(case)

    def test_invalid_vectors_cannot_silently_produce_rankings(self):
        validate_vectors({'a': [0.5, 1]}, {'a'}, 2)
        for vectors in ({}, {'a': [float('nan'), 1]}, {'a': [1]}, {'a': [0, 0]}, {'a': [True, 1]}):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                validate_vectors(vectors, {'a'}, 2)

    def test_report_output_rejects_existing_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target, report = root / 'source.txt', root / 'report.html'
            target.write_text('preserve')
            report.symlink_to(target)
            with self.assertRaises(ValueError):
                write_html(report, 'replacement')
            self.assertEqual(target.read_text(), 'preserve')

    def test_situations_keep_parent_and_exact_source_separate_from_patterns(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = root / 'assets/motif_library/deadline.md'
            p.parent.mkdir(parents=True)
            source = '# 倒计时\n\n## 一句话定义\n时限迫近。\n\n## 叙事结构模板\n1. 确立时限。\n\n## 常见情境原型\n\n- **救援**：天亮前救人。\n- **取证**：销毁前取证。\n\n## 不适用场景\n超时没有代价。\n'
            p.write_text(source)
            records = build_knowledge_records(root)
            pattern = [r for r in records if r['kind'] == 'pattern']
            situations = [r for r in records if r['kind'] == 'situation']
            self.assertEqual(len(pattern), 1)
            self.assertEqual(len(situations), 2)
            for row in records:
                for ref in row['source_refs']:
                    self.assertEqual(source[ref['start']:ref['end']], ref['quote'])
            for row in situations:
                self.assertEqual(row['parent_id'], pattern[0]['id'])
                self.assertIn('超时没有代价', row['constraints_text'])


if __name__ == '__main__':
    unittest.main()
