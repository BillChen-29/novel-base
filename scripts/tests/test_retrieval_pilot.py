"""Offline behavior contracts for retrieval experiments; no QMD/model required."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from retrieval_pilot import (  # noqa: E402
    bm25_rank, build_chunks, collapse_documents, load_fixture, rrf_fuse, score_ranking,
)


def hit(path: str, chunk: str, score: float = 1.0) -> dict:
    return {'source_path': path, 'chunk_id': chunk, 'score': score}


class RetrievalPilotContracts(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[dict, Path]:
        asset = root / 'assets/technique_library/dialogue.md'
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text('# 对话潜台词\n双方借铜钥匙试探对方的目的。\n## 限制\n不要直接断言人物撒谎。\n', encoding='utf-8')
        fixture = {
            'schema_version': 1,
            'annotation': {'method': 'agent_authored_pilot', 'limitation': '人工设定的试验标签，不代表真实用户评测。'},
            'documents': [{'path': 'assets/technique_library/dialogue.md', 'reason': '代表技巧文档'}],
            'queries': [
                {'id': 'q-dialogue', 'text': '两个人怎样借钥匙试探对方？', 'category': 'technique',
                 'split': 'development', 'relevant_paths': ['assets/technique_library/dialogue.md'],
                 'evidence': [{'path': 'assets/technique_library/dialogue.md', 'quote': '双方借铜钥匙试探对方的目的。'}],
                 'notes': '需要对话情境。'},
                {'id': 'q-none', 'text': '怎样修理核潜艇的反应堆？', 'category': 'out_of_scope',
                 'split': 'holdout', 'relevant_paths': [], 'evidence': [], 'notes': '样本没有这方面知识。'},
            ],
        }
        fixture_path = root / 'pilot.json'
        fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        return fixture, fixture_path

    def test_fixture_load_verifies_quotes_and_leaves_source_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, path = self.make_fixture(root)
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            loaded = load_fixture(path, root)
            again = load_fixture(path, root)
            self.assertEqual(loaded, again)
            self.assertEqual(loaded['documents'], fixture['documents'])
            self.assertEqual(loaded['queries'], fixture['queries'])
            after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(after, before)

    def test_fixture_rejects_false_or_missing_relevance_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, path = self.make_fixture(root)
            variants = []
            wrong = copy.deepcopy(fixture)
            wrong['queries'][0]['evidence'][0]['quote'] = '原文中不存在的具体创作建议。'
            variants.append(wrong)
            missing = copy.deepcopy(fixture)
            missing['queries'][0]['evidence'] = []
            variants.append(missing)
            outside = copy.deepcopy(fixture)
            outside['queries'][0]['relevant_paths'] = ['assets/technique_library/not-in-sample.md']
            variants.append(outside)
            stray = copy.deepcopy(fixture)
            stray['queries'][1]['evidence'] = copy.deepcopy(fixture['queries'][0]['evidence'])
            variants.append(stray)
            for index, candidate in enumerate(variants):
                with self.subTest(index=index):
                    path.write_text(json.dumps(candidate, ensure_ascii=False), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_fixture(path, root)

    def test_fixture_rejects_duplicate_documents_queries_and_bad_split(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, path = self.make_fixture(root)
            variants = []
            duplicate_doc = copy.deepcopy(fixture)
            duplicate_doc['documents'].append(copy.deepcopy(duplicate_doc['documents'][0]))
            variants.append(duplicate_doc)
            duplicate_query = copy.deepcopy(fixture)
            duplicate_query['queries'][1]['id'] = duplicate_query['queries'][0]['id']
            variants.append(duplicate_query)
            bad_split = copy.deepcopy(fixture)
            bad_split['queries'][0]['split'] = 'validation-typo'
            variants.append(bad_split)
            for index, candidate in enumerate(variants):
                with self.subTest(index=index):
                    path.write_text(json.dumps(candidate, ensure_ascii=False), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_fixture(path, root)

    def test_fixture_rejects_assets_outside_scope_or_ineligible_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, path = self.make_fixture(root)
            (root / 'outside.md').write_text('不应成为资产', encoding='utf-8')
            (root / 'assets/style_library').mkdir(parents=True)
            (root / 'assets/style_library/index.md').write_text('# 索引', encoding='utf-8')
            (root / 'assets/technique_library/config.json').write_text('{}', encoding='utf-8')
            (root / 'assets/technique_library/escape.md').symlink_to(root / 'outside.md')
            for bad_path in ('../outside.md', 'outside.md', 'assets/style_library/index.md',
                             'assets/technique_library/config.json', 'assets/technique_library/escape.md'):
                with self.subTest(path=bad_path):
                    candidate = copy.deepcopy(fixture)
                    candidate['documents'][0]['path'] = bad_path
                    candidate['queries'] = [candidate['queries'][1]]
                    path.write_text(json.dumps(candidate, ensure_ascii=False), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_fixture(path, root)

    def test_chunk_modes_preserve_source_spans_and_cover_all_nonblank_characters(self):
        source = '# 雨夜 🗝️\n\n## 线索\n' + '铜钥匙还在林舟手中。\n' * 31 + '\n## 限制\n' + '不要提前揭露秘密。\n' * 29
        expected_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
        for mode in ('window', 'structure'):
            with self.subTest(mode=mode):
                chunks = build_chunks(source, 'assets/technique_library/test.md', mode, max_chars=200, overlap=40)
                self.assertGreater(len(chunks), 2)
                self.assertEqual(len({row['chunk_id'] for row in chunks}), len(chunks))
                self.assertEqual(len({row['document_id'] for row in chunks}), 1)
                covered = set()
                for row in chunks:
                    self.assertLess(row['start'], row['end'])
                    self.assertGreaterEqual(row['start'], 0)
                    self.assertLessEqual(row['end'], len(source))
                    self.assertEqual(row['text'], source[row['start']:row['end']])
                    self.assertEqual(row['source_sha256'], expected_hash)
                    self.assertEqual(row['source_path'], 'assets/technique_library/test.md')
                    self.assertEqual(row['start_line'], source.count('\n', 0, row['start']) + 1)
                    self.assertEqual(row['end_line'], source.count('\n', 0, row['end'] - 1) + 1)
                    self.assertEqual(row['scope'], 'shared')
                    self.assertIsNone(row['project_id'])
                    self.assertTrue(row['title'])
                    self.assertIn('heading_path', row)
                    covered.update(range(row['start'], row['end']))
                self.assertTrue({i for i, char in enumerate(source) if not char.isspace()} <= covered)

    def test_chunk_modes_produce_different_boundaries_for_sectioned_source(self):
        source = '# 章标题\n\n## 第一节\n' + '甲' * 109 + '\n\n## 第二节\n' + '乙' * 137 + '\n\n## 第三节\n' + '丙' * 113
        windows = build_chunks(source, 'assets/pacing/example.md', 'window', max_chars=180, overlap=20)
        structured = build_chunks(source, 'assets/pacing/example.md', 'structure', max_chars=180, overlap=20)
        self.assertNotEqual([(x['start'], x['end']) for x in windows], [(x['start'], x['end']) for x in structured])

    def test_chunk_results_are_deterministic_even_when_called_concurrently(self):
        source = '# 叙事\n' + '不同视角，保留未知。🔑\n' * 70
        for mode in ('window', 'structure'):
            def run(_):
                return build_chunks(source, 'assets/pacing/example.md', mode, max_chars=250, overlap=40)
            expected = run(0)
            with ThreadPoolExecutor(max_workers=4) as pool:
                actual = list(pool.map(run, range(8)))
            self.assertTrue(all(rows == expected for rows in actual))

    def test_empty_source_has_no_chunks_and_short_source_keeps_content(self):
        for mode in ('window', 'structure'):
            self.assertEqual(build_chunks('', 'assets/pacing/example.md', mode), [])
            short = '一枚铜钥匙。🗝️'
            rows = build_chunks(short, 'assets/pacing/example.md', mode)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['text'], short)

    def test_chunker_rejects_invalid_modes_and_nonprogressing_windows(self):
        for mode in ('vector', '', None):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                build_chunks('正文', 'assets/pacing/example.md', mode)
        for size, overlap in ((0, 0), (-1, 0), (20, -1), (20, 20), (20, 21)):
            with self.subTest(size=size, overlap=overlap), self.assertRaises(ValueError):
                build_chunks('正文', 'assets/pacing/example.md', 'window', max_chars=size, overlap=overlap)

    def test_bm25_ranks_relevant_chinese_content_without_mutating_chunks(self):
        chunks = []
        chunks += build_chunks('# 铜钥匙\n铜钥匙打开旧档案柜，钥匙刻着数字七。', 'assets/motif_library/key.md', 'window')
        chunks += build_chunks('# 雨夜\n雨落在旧街道上，行人撑伞走过桥。', 'assets/motif_library/rain.md', 'window')
        before = copy.deepcopy(chunks)
        rows = bm25_rank('铜钥匙', chunks)
        self.assertEqual(rows[0]['source_path'], 'assets/motif_library/key.md')
        self.assertGreater(rows[0]['score'], 0)
        self.assertEqual(rows, bm25_rank('铜钥匙', chunks))
        self.assertEqual(chunks, before)
        self.assertEqual(bm25_rank('', chunks), [])
        self.assertEqual(bm25_rank('铜钥匙', []), [])

    def test_document_collapse_preserves_rank_order_and_selects_first_evidence(self):
        rows = [hit('a', 'a1', 9), hit('a', 'a2', 8), hit('b', 'b1', 7), hit('c', 'c1', 6)]
        before = copy.deepcopy(rows)
        actual = collapse_documents(rows, limit=2)
        self.assertEqual([x['source_path'] for x in actual], ['a', 'b'])
        self.assertEqual(actual[0]['chunk_id'], 'a1')
        self.assertEqual(rows, before)
        self.assertEqual(collapse_documents([], limit=5), [])

    def test_rrf_fuses_document_ranks_without_inflation_from_multiple_chunks(self):
        rankings = [[hit('a', 'a1'), hit('a', 'a2'), hit('b', 'b1')], [hit('b', 'b2'), hit('c', 'c1')]]
        before = copy.deepcopy(rankings)
        fused = rrf_fuse(rankings, k=60)
        self.assertEqual([x['source_path'] for x in fused], ['b', 'a', 'c'])
        self.assertAlmostEqual(fused[0]['score'], 1 / 62 + 1 / 61)
        self.assertAlmostEqual(fused[1]['score'], 1 / 61)
        self.assertAlmostEqual(fused[2]['score'], 1 / 62)
        self.assertEqual(rankings, before)
        self.assertEqual(rrf_fuse([], k=60), [])
        self.assertEqual(rrf_fuse([[], []], k=60), [])

    def test_rrf_matches_single_document_ranking_after_deduplication(self):
        once = rrf_fuse([[hit('a', 'a1'), hit('b', 'b1')]], k=60)
        repeated = rrf_fuse([[hit('a', 'a1'), hit('a', 'a2'), hit('a', 'a3'), hit('b', 'b1')]], k=60)
        self.assertEqual(repeated, once)

    def test_recall_mrr_hit_use_top_k_and_document_relevance(self):
        score = score_ranking(['x', 'a', 'y', 'b'], ['a', 'b', 'c'], k=3)
        self.assertAlmostEqual(score['recall_at_k'], 1 / 3)
        self.assertAlmostEqual(score['mrr_at_k'], 1 / 2)
        self.assertEqual(score['hit_at_k'], 1)
        miss = score_ranking(['x', 'y'], ['a'], k=5)
        self.assertEqual(miss, {'recall_at_k': 0.0, 'mrr_at_k': 0.0, 'hit_at_k': 0.0})
        empty = score_ranking([], ['a'], k=5)
        self.assertEqual(empty, miss)
        top_one = score_ranking(['x', 'a'], ['a'], k=1)
        self.assertEqual(top_one, miss)

    def test_no_answer_questions_return_unscored_metrics(self):
        for ranked in ([], ['x', 'y']):
            self.assertEqual(score_ranking(ranked, [], k=5), {
                'recall_at_k': None, 'mrr_at_k': None, 'hit_at_k': None,
            })


if __name__ == '__main__':
    unittest.main()
