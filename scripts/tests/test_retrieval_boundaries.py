"""Story retrieval must use only the requested project and prefix."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plot_rag_retriever as rag


class RetrievalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def project(self, name='book', chapters=None):
        root = self.base / name
        (root / '03_manuscript').mkdir(parents=True)
        (root / '00_memory').mkdir()
        (root / '00_memory/character_tracker.md').write_text('|人物|秘密|\n|---|---|\n|阿青|未来王城|\n')
        for number, body in (chapters or {}).items():
            (root / f'03_manuscript/第{number}章 片段.md').write_bytes(body.encode('utf-8'))
        return root

    def query(self, root, index=None, **kwargs):
        return rag.retrieve(index or rag.build_index(root), root, '阿青钥匙暗号', top_k=5,
            candidate_k=10, per_chapter=4, passage_max_chars=200, **kwargs)

    def cli(self, root, *args):
        proc = subprocess.run([sys.executable, str(Path(rag.__file__)), 'query', '--project-root', str(root),
            '--query', '阿青钥匙暗号', '--force', *args], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_chapter_cutoff_keeps_past_and_excludes_future_and_tracker(self):
        root = self.project(chapters={1:'阿青找到钥匙。', 3:'阿青知道暗号是未来白鲸。'})
        result = self.query(root, cutoff_chapter=1)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertIn('找到钥匙', serialized)
        self.assertNotIn('未来白鲸', serialized)
        self.assertNotIn('未来王城', serialized)
        self.assertEqual(result['relation_snippets'], [])

    def test_unicode_offset_limits_every_derived_field_and_quote(self):
        prefix = '阿青找到钥匙。🔑\r\n\r\n他仍在门外。'
        body = prefix + '阿青在未来王城发现暗号是白鲸。'
        root = self.project(chapters={1:body})
        result = self.query(root, cutoff_chapter=1, cutoff_offset=len(prefix))
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertIn('找到钥匙', serialized)
        self.assertNotIn('白鲸', serialized)
        self.assertNotIn('未来王城', serialized)
        for row in result['retrieved']:
            for quote in row['passages']:
                self.assertEqual(body[quote['start']:quote['end']], quote['text'])
                self.assertLessEqual(quote['end'], len(prefix))
                self.assertEqual(len(quote['source_sha256']), 64)
        later = self.query(root, cutoff_chapter=1, cutoff_offset=len(body))
        self.assertIn('白鲸', json.dumps(later, ensure_ascii=False))

    def test_zero_prefix_never_falls_back_to_full_chapter(self):
        root = self.project(chapters={1:'阿青找到钥匙。', 2:'暗号是白鲸。'})
        self.assertEqual(self.query(root, cutoff_chapter=0)['retrieved'], [])
        self.assertEqual(self.query(root, cutoff_chapter=1, cutoff_offset=0)['retrieved'], [])
        result = self.query(root, cutoff_chapter=2, cutoff_offset=0)
        self.assertEqual([r['chapter_file'] for r in result['retrieved']], ['第1章 片段.md'])

    def test_invalid_cutoffs_are_rejected(self):
        root = self.project(chapters={1:'钥匙。'})
        for kwargs in ({'cutoff_chapter':-1}, {'cutoff_chapter':True}, {'cutoff_chapter':'1'},
                       {'cutoff_offset':1}, {'cutoff_chapter':1,'cutoff_offset':True},
                       {'cutoff_chapter':1,'cutoff_offset':-1}, {'cutoff_chapter':1,'cutoff_offset':99},
                       {'cutoff_chapter':2,'cutoff_offset':1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.query(root, **kwargs)

    def test_foreign_project_and_forged_path_are_rejected(self):
        a = self.project('a',{1:'阿青找到甲钥匙。'})
        b = self.project('b',{1:'阿青找到乙钥匙。'})
        index = rag.build_index(a)
        with self.assertRaisesRegex(ValueError, 'project_mismatch'):
            self.query(b,index=index)
        altered = copy.deepcopy(index)
        altered['docs'][0]['chapter_path'] = str(b / '03_manuscript/第1章 片段.md')
        with self.assertRaisesRegex(ValueError, 'outside_manuscript'):
            self.query(a,index=altered)
        self.assertIn('甲钥匙', json.dumps(self.query(a,index=index),ensure_ascii=False))

    def test_manuscript_symlink_escape_is_rejected_before_read(self):
        root = self.project()
        other = self.base / 'outside.md'
        other.write_text('不可读取的别书正文')
        (root/'03_manuscript/第1章 片段.md').symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'outside_manuscript'):
            rag.build_index(root)

    def test_direct_api_rejects_stale_index(self):
        root = self.project(chapters={1:'阿青拿着旧钥匙。'})
        index = rag.build_index(root)
        (root/'03_manuscript/第1章 片段.md').write_text('阿青拿着新钥匙。')
        with self.assertRaisesRegex(ValueError, 'stale_index'):
            self.query(root,index=index)

    def test_cli_refreshes_content_with_same_size_and_mtime_then_deletion(self):
        root = self.project(chapters={1:'阿青暗号是旧青鸟。'})
        self.cli(root)
        path = root/'03_manuscript/第1章 片段.md'
        stat=path.stat()
        path.write_text('阿青暗号是新白鲸。')
        os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        result = self.cli(root)
        self.assertNotIn('旧青鸟',json.dumps(result,ensure_ascii=False))
        self.assertIn('新白鲸',json.dumps(result,ensure_ascii=False))
        path.unlink()
        self.assertEqual(self.cli(root)['result']['retrieved'],[])

    def test_cached_late_cutoff_never_served_to_early_cutoff(self):
        prefix='阿青拿着钥匙。'
        root=self.project(chapters={1:prefix+'暗号是未来白鲸。'})
        late=self.cli(root,'--cutoff-chapter','1')
        self.assertIn('未来白鲸',json.dumps(late,ensure_ascii=False))
        early=self.cli(root,'--cutoff-chapter','1','--cutoff-offset',str(len(prefix)))
        self.assertFalse(early['cache_hit'])
        self.assertNotIn('未来白鲸',json.dumps(early,ensure_ascii=False))
        self.assertTrue(self.cli(root,'--cutoff-chapter','1','--cutoff-offset',str(len(prefix)))['cache_hit'])

    def test_cache_parameters_and_tracker_contents_invalidate_results(self):
        root=self.project(chapters={1:'阿青拿着钥匙。'})
        self.cli(root)
        self.assertTrue(self.cli(root)['cache_hit'])
        self.assertFalse(self.cli(root,'--candidate-k','7')['cache_hit'])
        self.assertFalse(self.cli(root,'--min-score','2')['cache_hit'])
        (root/'00_memory/character_tracker.md').write_text('|人物|秘密|\n|---|---|\n|阿青|新的关系记录|\n')
        result=self.cli(root)
        self.assertFalse(result['cache_hit'])
        self.assertNotIn('未来王城',json.dumps(result,ensure_ascii=False))
        self.assertIn('新的关系记录',json.dumps(result,ensure_ascii=False))

    def test_unknown_chapter_and_ambiguous_offset_are_not_assumed_safe(self):
        root=self.project(chapters={1:'阿青拿着钥匙。'})
        (root/'03_manuscript/无序资料.md').write_text('未来白鲸秘密')
        self.assertNotIn('未来白鲸',json.dumps(self.query(root,cutoff_chapter=1),ensure_ascii=False))
        (root/'03_manuscript/第1章 重复.md').write_text('另一个第一章')
        with self.assertRaisesRegex(ValueError, 'one existing chapter'):
            self.query(root,cutoff_chapter=1,cutoff_offset=1)

    def test_pending_drafts_are_not_historical_facts(self):
        root=self.project(chapters={1:'阿青拿着钥匙。',
            2:'<!-- NOVEL_FLOW_STUB -->\n规划秘密甲',
            3:'<!-- BEAT_SHEET_STUB -->\n扩写提示秘密乙',
            4:'# 第4章\n[待写]\n规划秘密丙'})
        result=self.query(root,cutoff_chapter=4)
        self.assertEqual([r['chapter_no'] for r in result['retrieved']],[1])
        self.assertIn('拿着钥匙',json.dumps(result,ensure_ascii=False))
        for term in ('秘密甲','秘密乙','秘密丙'):
            self.assertNotIn(term,json.dumps(result,ensure_ascii=False))

    def test_linked_outputs_cannot_overwrite_manuscript_via_build_or_query(self):
        targets = ['story_index.json', 'entity_chapter_map.json', 'query_cache.json',
                   'next_plot_context.md', 'chapter_meta/chapter.meta.json']
        for command in ('build', 'query'):
            for link_type in ('symlink', 'hardlink'):
                for i, target in enumerate(targets):
                    with self.subTest(command=command,link_type=link_type,target=target):
                        root=self.project(f'{command}-{link_type}-{i}',{1:'阿青拿着钥匙，正文绝不可被索引覆盖。'})
                        chapter=root/'03_manuscript/第1章 片段.md'
                        original=chapter.read_bytes()
                        output=root/'00_memory/retrieval'/target
                        output.parent.mkdir(parents=True)
                        if link_type=='symlink':output.symlink_to(chapter)
                        else:os.link(chapter,output)
                        args=[sys.executable,str(Path(rag.__file__)),command,'--project-root',str(root)]
                        if command=='query':args+=['--query','阿青钥匙','--force']
                        proc=subprocess.run(args,capture_output=True,text=True)
                        self.assertEqual(chapter.read_bytes(),original,'derived output overwrote the original chapter')
                        self.assertNotEqual(proc.returncode,0)
                        self.assertIn('unsafe_retrieval_output',proc.stdout+proc.stderr)

    def test_output_parent_link_is_rejected_before_any_file_creation(self):
        root=self.project(chapters={1:'阿青拿着钥匙。'})
        directory=root/'03_manuscript'
        before={p.name:p.read_bytes() for p in directory.iterdir()}
        (root/'00_memory/retrieval').symlink_to(directory,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'unsafe_retrieval_output'):
            rag.build_index(root)
        self.assertEqual({p.name:p.read_bytes() for p in directory.iterdir()},before)

    def test_direct_cache_and_context_writes_reject_links(self):
        for kind in ('symlink','hardlink'):
            root=self.project(kind,{1:'阿青拿着钥匙。'})
            chapter=root/'03_manuscript/第1章 片段.md'
            original=chapter.read_bytes()
            output=root/'00_memory/retrieval/query_cache.json'
            output.parent.mkdir(parents=True)
            if kind=='symlink':output.symlink_to(chapter)
            else:os.link(chapter,output)
            with self.assertRaisesRegex(ValueError,'unsafe_retrieval_output'):
                rag.save_cache(output,{'entries':{}})
            with self.assertRaisesRegex(ValueError,'unsafe_retrieval_output'):
                rag.write_context_md(root,{'query':'钥匙','retrieved':[]})
            self.assertEqual(chapter.read_bytes(),original)

    def test_emit_json_preflight_rejects_links_and_accepts_regular_output(self):
        root=self.project(chapters={1:'阿青拿着钥匙。'})
        chapter=root/'03_manuscript/第1章 片段.md'
        original=chapter.read_bytes()
        linked=root/'output.json'
        linked.symlink_to(chapter)
        proc=subprocess.run([sys.executable,str(Path(rag.__file__)),'query','--project-root',str(root),
            '--query','钥匙','--emit-json',str(linked)],capture_output=True,text=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn('unsafe_retrieval_output',proc.stdout+proc.stderr)
        self.assertEqual(chapter.read_bytes(),original)
        self.assertFalse((root/'00_memory/retrieval').exists())
        linked.unlink()
        self.cli(root,'--emit-json',str(linked))
        self.assertTrue(json.loads(linked.read_text())['ok'])


if __name__=='__main__':
    unittest.main()
