"""Regression tests for passing bounded story context to the actual Beat expander."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import beat_sheet_generator as beat
import novel_flow_executor as flow
import novel_chapter_writer as writer


class WriterContextTests(unittest.TestCase):
    def test_demo_quality_padding_keeps_context_out_of_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); chapter = root / '第2章.md'
            chapter.write_text('主角站在门前，等待同伴。')
            args = argparse.Namespace(min_chars=300)
            flow.apply_targeted_quality_fix(root, chapter,
                {'failures': ['char_count<300'], 'paragraph_count': 1, 'sentence_count': 1},
                args, '核对名单', writing_context='禁止提前揭晓：幕后人是黑鹭。')
            body = chapter.read_text()
            self.assertNotIn('黑鹭', body)
            self.assertGreaterEqual(len(flow.re.sub(r'\s+', '', flow.clean_for_stats(body))), 300)

    def test_failed_expansion_never_synthesizes_stale_beat_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); beats=root/'00_memory/beats'; beats.mkdir(parents=True)
            chapter=root/'03_manuscript/第2章 新段.md'; chapter.parent.mkdir()
            for i in range(1,5):
                (beats/f'ch0002_beat{i:02d}_expand.md').write_text('旧截点后的秘密：蓝鲸已经死亡。')
            original_run=flow.run_python
            def fail_expand(script,args):
                if script.name=='beat_sheet_generator.py' and args[0]=='expand':
                    return 1,'','expansion failed',None
                return original_run(script,args)
            with patch.object(flow,'run_python',side_effect=fail_expand):
                ok,reason=flow._generate_beat_draft(root,chapter,2,'蓝鲸仍活着',{},
                    argparse.Namespace(draft_provider='template',pacing_mode='standard',beat_count=4))
            self.assertFalse(ok,reason)
            self.assertFalse(chapter.exists())

    def test_prepare_only_rejects_artifact_link_to_manuscript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'03_manuscript').mkdir(); (root/'.flow').mkdir()
            source=root/'03_manuscript/第1章 原文.md'; source.write_text('必须保留的原文。')
            (root/'.flow/writing_context_ch0002.json').symlink_to(source)
            with patch.object(sys,'argv',['flow','continue-write','--project-root',str(root),
                    '--prepare-only','--no-research','--no-constraints']): args=flow.parse_args()
            result=flow.continue_write(args)
            self.assertFalse(result['ok'])
            self.assertEqual(source.read_text(),'必须保留的原文。')

    def test_auto_without_model_keeps_prompt_and_does_not_publish_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(sys,'argv',['flow','continue-write','--project-root',str(root),
                    '--no-research']), patch.object(flow,'_resolve_draft_provider',return_value='template'):
                result=flow.continue_write(flow.parse_args())
            self.assertTrue(result['ok'],result)
            self.assertEqual(result['draft_provider_used'],'prompt_only')
            self.assertTrue(result['awaiting_draft'])
            self.assertFalse(result['gate_passed_final'])
            self.assertFalse((root/'00_memory/chapter_summaries/recent.md').exists())

    def test_non_beat_model_failure_preserves_bounded_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'03_manuscript').mkdir()
            (root/'03_manuscript/第1章 门前.md').write_text('前文证据：断剑仍在左手。')
            with patch.object(sys,'argv',['flow','continue-write','--project-root',str(root),
                    '--chapter-file',str(root/'03_manuscript/第2章 下一章.md'),
                    '--no-beat-sheet','--draft-provider','llm','--no-research']), \
                 patch.object(writer,'write_chapter',return_value={'ok':False,'error':'test_failure'}) as call:
                result=flow.continue_write(flow.parse_args())
            self.assertTrue(result['ok'],result)
            self.assertEqual(result['draft_provider_used'],'prompt_only')
            supplied=call.call_args.kwargs['config_overrides']
            self.assertIn('断剑仍在左手',supplied['writing_prompt'])
            self.assertFalse(supplied['auto_update_memory'])
            self.assertIn('断剑仍在左手',Path(result['chapter_file']).read_text())
            self.assertFalse(result['gate_passed_final'])

    def test_provided_prompt_never_loads_unbounded_project_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(writer.ContextExtractor, 'extract_context', side_effect=AssertionError('unbounded memory read')):
                result = writer.write_chapter(root, root/'03_manuscript/第2章 测试.md',
                    config_overrides={'writing_prompt': '只含截点前的依据', 'auto_update_memory': False}, dry_run=True)
            self.assertTrue(result['ok'])
            self.assertEqual(result['prompt'], '只含截点前的依据')

    def test_scene_decomposition_model_receives_tail_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured = []
            def fake_write(project, chapter_file, config_overrides, **kwargs):
                captured.append(config_overrides)
                chapter_file.parent.mkdir(parents=True, exist_ok=True)
                chapter_file.write_text(json.dumps({'moments': [{'id': i, 'action': '试探'} for i in range(3)]}))
                return {'ok': True}
            with patch.object(writer, 'write_chapter', side_effect=fake_write):
                flow._decompose_beat_scenes('正文目标。'*200+'末端证据：阿白不能瞬移。',900,{},root)
            self.assertIn('阿白不能瞬移', captured[0]['writing_prompt'])
            self.assertFalse(captured[0]['auto_update_memory'])

    def test_tail_uses_only_permitted_prefix_and_zero_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); manuscripts=root/'03_manuscript';manuscripts.mkdir()
            prefix='门前等候。🔑'; future='后文密钥：蓝鲸。'
            (manuscripts/'第1章 门前.md').write_text(prefix+future)
            result=flow._continuity_tail(root,1,len(prefix))
            self.assertEqual(result['previous_ending'],prefix)
            self.assertNotIn('蓝鲸',str(result))
            self.assertEqual(flow._continuity_tail(root,1,0)['previous_ending'],'')
            for offset in (-1,True,len(prefix+future)+1):
                with self.assertRaises(ValueError):flow._continuity_tail(root,1,offset)

    def test_prepare_only_preserves_manuscript_and_bounds_actual_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); manuscripts=root/'03_manuscript';manuscripts.mkdir()
            prefix='阿青在城门前等候，手持断剑。'; future='后文密钥：蓝鲸。'
            source=manuscripts/'第1章 门前.md'; source.write_text(prefix+future)
            (manuscripts/'第3章 揭晓.md').write_text('未来人物：黑鹭。')
            with patch.object(sys,'argv',['novel_flow_executor.py','continue-write','--project-root',str(root),
                    '--chapter-file',str(source),'--query','继续调查断剑','--prepare-only',
                    '--cutoff-chapter','1','--cutoff-offset',str(len(prefix)),'--no-research']):
                args=flow.parse_args()
            result=flow.continue_write(args)
            self.assertTrue(result['ok'],result)
            self.assertTrue(result['prepared_only'])
            prompt=Path(result['prepared_prompt_file']).read_text()
            self.assertIn('手持断剑',prompt)
            self.assertNotIn('蓝鲸',prompt)
            self.assertNotIn('黑鹭',prompt)
            self.assertEqual(source.read_text(),prefix+future)

    def test_previous_ending_and_separate_context_reach_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = '门后敲了三下，阿青左手仍握断剑。'
            context = {'history_context': '原文证据：城门尚未打开。',
                       'graph_context': '阿白在海岛，阿青并不知情。',
                       'source_cutoff': {'chapter': 1, 'offset': None}}
            context_file = root / 'context.json'
            context_file.write_text(json.dumps(context, ensure_ascii=False))
            args = argparse.Namespace(project_root=str(root), chapter=2, beat_count=4,
                pacing_depth='standard', chapter_goal='继续交谈', previous_ending=previous,
                context_file=str(context_file))
            beat.cmd_generate(args, beat.BeatConfig())
            for number in (1, 2):
                result = beat.cmd_expand(argparse.Namespace(project_root=str(root), chapter=2,
                    beat_id=number, pacing_depth=''), beat.BeatConfig())
                self.assertIn(previous, result['expand_prompt'])
                self.assertIn(context['history_context'], result['expand_prompt'])
                self.assertIn(context['graph_context'], result['expand_prompt'])

    def test_long_query_and_constraints_are_not_sliced_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '03_manuscript').mkdir()
            query = '推进对话与调查。' * 30 + '\n历史关键事实：左手断剑不能丢失。'
            constraints = {'outline_constraints': {'constraints_prompt': '保留悬念。' * 80},
                'event_recommendation': {'notes': ['展开调查。' * 30]},
                'graph_context': {'context_prompt': '图谱关键事实：阿白仍在海岛。'},
                'continuity_context': {'previous_ending': '门后仍在敲击。'}}
            ok, mode = flow._generate_beat_draft(root, root / '03_manuscript/第2章 测试.md',
                2, query, constraints,
                argparse.Namespace(draft_provider='template', pacing_mode='standard', beat_count=4))
            self.assertTrue(ok, mode)
            prompt = (root / '00_memory/beats/ch0002_beat01_expand.md').read_text()
            self.assertIn('左手断剑不能丢失', prompt)
            self.assertIn('阿白仍在海岛', prompt)
            self.assertIn('门后仍在敲击', prompt)


if __name__ == '__main__':
    unittest.main()
