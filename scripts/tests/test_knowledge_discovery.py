"""Offline capability and regression contracts for prefix-bound discovery."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge_discovery import build_index, discover, freeze_prefix
from retrieval_pilot import bm25_rank, collapse_documents, rrf_fuse


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class KnowledgeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = {
            'assets/technique_library/alpha.md': '# Alpha\nalpha copper\n## detail\nalpha lock\n',
            'assets/motif_library/beta.md': '# Beta\nbeta mirror\n',
            'assets/pacing/gamma.md': '# Gamma\ngamma rhythm\n',
        }
        for path, text in self.sources.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode('utf-8'))
        self.paths = list(self.sources)
        self.prefix = 'alpha 在雨夜看见铜钥匙。🔑'
        self.snapshot = freeze_prefix('project one', self.prefix + '未来真相 beta', len(self.prefix), '阿澄')
        self.index = build_index(self.root, self.paths)

    def analysis(self, *queries):
        return {'schema_version': 1, 'snapshot_sha256': self.snapshot['snapshot_sha256'],
                'queries': [{'text': query, 'evidence': [{'start': 0, 'end': len(self.prefix),
                                                         'quote': self.prefix}]} for query in queries]}

    def test_snapshot_contains_only_prefix_and_stable_canonical_binding(self):
        expected = {'schema_version': 1, 'project_id': 'project one', 'pov_character': '阿澄',
                    'cutoff_offset': len(self.prefix), 'text': self.prefix,
                    'source_sha256': digest(self.prefix)}
        self.assertEqual(self.snapshot, {**expected, 'snapshot_sha256': digest(expected)})
        other = freeze_prefix('project one', self.prefix + '另一个后文', len(self.prefix), '阿澄')
        self.assertEqual(self.snapshot, other)
        self.assertNotIn('未来', json.dumps(self.snapshot, ensure_ascii=False))
        self.assertEqual(freeze_prefix('x', '🔑', 1, '人')['text'], '🔑')

    def test_snapshot_rejects_empty_invalid_types_and_cutoffs(self):
        for field in ('project_id', 'source_text', 'pov_character'):
            for bad in (None, '', ' \n', [], {}, True, 7):
                args = dict(project_id='p', source_text='前文', cutoff_offset=1, pov_character='人')
                args[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    freeze_prefix(**args)
        for cutoff in (None, True, False, -1, 0, 3, 1.0, '1'):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                freeze_prefix('p', '前文', cutoff, '人')
        with self.assertRaises(ValueError):
            freeze_prefix('p', '  正文', 2, '人')

    def test_index_is_json_serializable_exact_and_order_independent(self):
        self.assertEqual(self.index, json.loads(json.dumps(self.index)))
        self.assertEqual(self.index, build_index(self.root, list(reversed(self.paths))))
        self.assertEqual(self.index['corpus_sha256'], digest({k: v for k, v in self.index.items()
                                                            if k != 'corpus_sha256'}))
        self.assertEqual({d['kind'] for d in self.index['documents']}, {'technique', 'motif', 'pacing'})
        for document in self.index['documents']:
            source = self.sources[document['source_path']]
            self.assertEqual(document['text'], source)
            self.assertEqual(document['source_sha256'], digest(source))
            for chunk in document['chunks']:
                self.assertEqual(chunk['text'], source[chunk['start']:chunk['end']])
                self.assertIn(':structure:', chunk['chunk_id'])

    def test_index_does_not_read_story_or_write_files(self):
        (self.root / 'stories').mkdir()
        (self.root / 'stories/private.md').write_bytes(b'\xff\xfe story must not be read')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(build_index(self.root, self.paths), self.index)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes()
                                  for p in self.root.rglob('*') if p.is_file()})

    def test_index_rejects_invalid_empty_duplicate_or_ineligible_paths(self):
        (self.root / 'assets/style_library').mkdir()
        (self.root / 'assets/style_library/index.md').write_text('# index')
        (self.root / 'assets/technique_library/config.json').write_text('{}')
        for paths in (None, '', [], [None], [True], [self.paths[0], self.paths[0]],
                      ['../outside.md'], ['/absolute.md'], ['assets/../outside.md'],
                      ['assets//technique_library/alpha.md'], ['assets\\alpha.md'],
                      ['assets/style_library/index.md'], ['assets/technique_library/config.json'],
                      ['stories/private.md'], ['assets/missing.md']):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                build_index(self.root, paths)

    def test_index_rejects_symlink_escape_and_non_utf8(self):
        outside = self.root / 'outside.md'
        outside.write_text('outside')
        link = self.root / 'assets/technique_library/escape.md'
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            build_index(self.root, [link.relative_to(self.root).as_posix()])
        link.unlink()
        invalid = self.root / self.paths[0]
        invalid.write_bytes(b'\xff\xfe')
        with self.assertRaises(ValueError):
            build_index(self.root, self.paths)

    def test_source_changes_change_corpus_identity(self):
        (self.root / self.paths[0]).write_text('alpha changed')
        changed = build_index(self.root, self.paths)
        self.assertNotEqual(changed['corpus_sha256'], self.index['corpus_sha256'])
        self.assertNotEqual(changed['documents'], self.index['documents'])

    def test_raw_prefix_is_direct_bm25_and_fused_equals_raw_without_analysis(self):
        result = discover(self.snapshot, self.index)
        chunks = [c for d in self.index['documents'] for c in d['chunks']]
        expected = collapse_documents(bm25_rank(self.prefix, chunks))
        self.assertEqual([h['source_path'] for h in result['methods']['raw_prefix']],
                         [h['source_path'] for h in expected])
        self.assertEqual(result['methods']['abstract_queries'], [])
        self.assertEqual(result['methods']['fused'], result['methods']['raw_prefix'])
        self.assertEqual(result['snapshot_sha256'], self.snapshot['snapshot_sha256'])
        self.assertEqual(result['corpus_sha256'], self.index['corpus_sha256'])
        for hit, original in zip(result['methods']['raw_prefix'], expected):
            self.assertEqual(hit['score'], original['score'])

    def test_three_rankings_use_two_equal_groups_not_flat_query_voting(self):
        analysis = self.analysis('beta', 'beta', 'beta', 'beta')
        result = discover(self.snapshot, self.index, analysis)
        raw, abstract, fused = [result['methods'][key] for key in
                                ('raw_prefix', 'abstract_queries', 'fused')]
        self.assertEqual([h['source_path'] for h in raw], [self.paths[0]])
        self.assertEqual([h['source_path'] for h in abstract], [self.paths[1]])
        self.assertEqual(len(fused), 2)
        self.assertAlmostEqual(fused[0]['score'], 1 / 61)
        self.assertAlmostEqual(fused[1]['score'], 1 / 61)
        one_query = discover(self.snapshot, self.index, self.analysis('beta'))
        self.assertEqual(fused, one_query['methods']['fused'])

    def test_multiple_queries_rrf_and_full_rankings_fuse_before_limit(self):
        analysis = self.analysis('beta gamma', 'gamma', 'alpha')
        chunks = [c for d in self.index['documents'] for c in d['chunks']]
        raw = collapse_documents(bm25_rank(self.prefix, chunks), len(chunks))
        abstract = rrf_fuse([bm25_rank(q['text'], chunks) for q in analysis['queries']])
        fused = rrf_fuse([raw, abstract])
        actual = discover(self.snapshot, self.index, analysis, limit=1)['methods']
        for name, ranking in [('raw_prefix', raw), ('abstract_queries', abstract), ('fused', fused)]:
            self.assertEqual(actual[name][0]['source_path'], ranking[0]['source_path'])
            self.assertAlmostEqual(actual[name][0]['score'], ranking[0]['score'])

    def test_hits_have_exact_excerpts_and_are_document_unique(self):
        result = discover(self.snapshot, self.index, self.analysis('alpha beta gamma'), limit=99)
        documents = {d['source_path']: d for d in self.index['documents']}
        for rows in result['methods'].values():
            self.assertEqual(len(rows), len({h['source_path'] for h in rows}))
            for hit in rows:
                self.assertEqual(set(hit), {'source_path', 'title', 'kind', 'source_sha256', 'score', 'matched_excerpt'})
                document = documents[hit['source_path']]
                self.assertIn(hit['matched_excerpt'], [c['text'] for c in document['chunks']])
                for key in ('title', 'kind', 'source_sha256'):
                    self.assertEqual(hit[key], document[key])

    def test_empty_match_and_zero_limit_are_empty(self):
        unmatched = freeze_prefix('p', 'quasineutrino', 13, '人')
        self.assertTrue(all(not v for v in discover(unmatched, self.index)['methods'].values()))
        self.assertTrue(all(not v for v in discover(self.snapshot, self.index, self.analysis('beta'), 0)['methods'].values()))
        for limit in (-1, True, 1.1, None, '5'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                discover(self.snapshot, self.index, limit=limit)

    def test_project_name_does_not_affect_ranking(self):
        renamed = freeze_prefix('beta gamma different name', self.prefix, len(self.prefix), '阿澄')
        analysis = self.analysis('beta')
        rebound = copy.deepcopy(analysis)
        rebound['snapshot_sha256'] = renamed['snapshot_sha256']
        self.assertEqual(discover(self.snapshot, self.index, analysis)['methods'],
                         discover(renamed, self.index, rebound)['methods'])

    def test_evidence_position_is_checked_but_semantic_entailment_not_claimed(self):
        analysis = self.analysis('arbitrary external interpretation')
        analysis['queries'][0]['evidence'] = [{'start': len(self.prefix)-1, 'end': len(self.prefix), 'quote': '🔑'}]
        self.assertEqual(discover(self.snapshot, self.index, analysis)['methods']['abstract_queries'], [])

    def test_analysis_rejects_wrong_binding_counts_schema_and_unknown_fields(self):
        mutations = [lambda a: a.update(snapshot_sha256='0'*64), lambda a: a.update(schema_version=True),
                     lambda a: a.update(extra='future'), lambda a: a.update(queries=[]),
                     lambda a: a.update(queries=a['queries']*5), lambda a: a.update(queries=None),
                     lambda a: a['queries'][0].update(text=' '), lambda a: a['queries'][0].update(text=[]),
                     lambda a: a['queries'][0].update(evidence=[]), lambda a: a['queries'][0].update(evidence=None),
                     lambda a: a['queries'][0].update(extra='x')]
        for mutate in mutations:
            candidate = self.analysis('beta')
            mutate(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                discover(self.snapshot, self.index, candidate)
        for bad in ([], 'x', True, {'schema_version': 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                discover(self.snapshot, self.index, bad)

    def test_analysis_rejects_outside_prefix_false_quotes_and_wrong_offsets(self):
        for evidence in (None, {}, {'start': 0, 'end': 1, 'quote': 'future'},
                         {'start': True, 'end': 1, 'quote': 'a'},
                         {'start': 0, 'end': False, 'quote': 'a'},
                         {'start': -1, 'end': 2, 'quote': 'al'},
                         {'start': 0, 'end': len(self.prefix)+1, 'quote': self.prefix},
                         {'start': 1, 'end': 1, 'quote': ''},
                         {'start': 0, 'end': 1, 'quote': 'a', 'extra': 'future'}):
            candidate = self.analysis('beta')
            candidate['queries'][0]['evidence'] = [evidence]
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                discover(self.snapshot, self.index, candidate)

    def test_snapshot_tampering_and_unknown_fields_are_rejected(self):
        for key, value in [('text', 'beta'), ('source_sha256', '0'*64), ('snapshot_sha256', '0'*64),
                           ('project_id', 'renamed'), ('schema_version', True), ('cutoff_offset', True),
                           ('future_text', 'secret')]:
            candidate = copy.deepcopy(self.snapshot)
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                discover(candidate, self.index)
        for bad in (None, [], {}, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                discover(bad, self.index)

    def test_index_tampering_is_rejected_even_if_outer_hash_is_recomputed(self):
        mutations = [lambda i: i['documents'][0].update(text='changed'),
                     lambda i: i['documents'][0].update(source_sha256='0'*64),
                     lambda i: i['documents'][0]['chunks'][0].update(text='fabricated'),
                     lambda i: i['documents'][0].update(source_path='../outside.md'),
                     lambda i: i['documents'].append(copy.deepcopy(i['documents'][0])),
                     lambda i: i.update(schema_version=True), lambda i: i.update(documents=[])]
        for mutate in mutations:
            candidate = copy.deepcopy(self.index)
            mutate(candidate)
            candidate['corpus_sha256'] = digest({k: v for k, v in candidate.items() if k != 'corpus_sha256'})
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                discover(self.snapshot, candidate)
        for key in ('title', 'kind'):
            candidate = copy.deepcopy(self.index)
            candidate['documents'][0][key] = 'tampered'
            with self.assertRaises(ValueError):
                discover(self.snapshot, candidate)
        for bad in (None, [], {}, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                discover(self.snapshot, bad)

    def test_inputs_unchanged_concurrent_replay_and_detached_outputs(self):
        analysis = self.analysis('beta')
        before = copy.deepcopy((self.snapshot, self.index, analysis))
        expected = discover(self.snapshot, self.index, analysis)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: discover(self.snapshot, self.index, analysis), range(8)))
        self.assertTrue(all(result == expected for result in results))
        self.assertEqual((self.snapshot, self.index, analysis), before)
        expected['methods']['raw_prefix'][0]['matched_excerpt'] = 'changed'
        self.assertEqual((self.snapshot, self.index, analysis), before)

    def test_long_unicode_source_and_special_characters_round_trip(self):
        source = '甲乙🔑 ; DROP TABLE x; <script> 标签\n' * 400
        self.assertGreater(len(source), 10000)
        path = self.paths[0]
        (self.root / path).write_bytes(source.encode('utf-8'))
        index = build_index(self.root, [path])
        snapshot = freeze_prefix('特殊 " 标识', source, len(source), '阿澄')
        result = discover(snapshot, index)
        self.assertEqual(result['methods']['raw_prefix'][0]['source_path'], path)
        self.assertIn(result['methods']['raw_prefix'][0]['matched_excerpt'], source)


if __name__ == '__main__':
    unittest.main()
