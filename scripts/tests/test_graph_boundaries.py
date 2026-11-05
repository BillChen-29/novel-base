"""Graph projections must obey narrative time and explicit knowledge labels."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import story_graph_builder as graph


class GraphBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '00_memory').mkdir()

    def write(self, nodes, edges=None):
        self.path = self.root / '00_memory/story_graph.json'
        self.path.write_text(json.dumps({'nodes': nodes, 'edges': edges or [], 'timeline': []}, ensure_ascii=False))

    def context(self, chapter=None, offset=None, pov=None, legacy=0):
        return graph.cmd_context(argparse.Namespace(project_root=str(self.root), chapter=legacy,
            cutoff_chapter=chapter, cutoff_offset=offset, pov_character=pov,
            max_events=20, max_foreshadows=20), graph.GraphConfig())

    def test_all_types_filter_future_and_unknown_latest_state(self):
        self.write([
            {'id':'past', 'type':'event', 'chapter':1, 'description':'此前发现钥匙'},
            {'id':'future', 'type':'event', 'chapter':3, 'description':'未来打开宝库'},
            {'id':'f1', 'type':'foreshadow', 'chapter_planted':1, 'description':'旧玉佩'},
            {'id':'f3', 'type':'foreshadow', 'planted_chapter':3, 'description':'未来密信'},
            {'id':'c', 'type':'character', 'name':'阿青', 'last_updated':3, 'location':'未来王城'},
            {'id':'unknown', 'type':'character', 'name':'无时间角色', 'location':'来源不明地点'},
        ])
        result = self.context(1)
        self.assertIn('此前发现钥匙', result['context_prompt'])
        self.assertIn('旧玉佩', result['context_prompt'])
        for future in ('未来打开宝库', '未来密信', '未来王城', '来源不明地点'):
            self.assertNotIn(future, result['context_prompt'])
        self.assertTrue(result['omissions'])

    def test_character_history_restores_complete_old_state_not_latest_fields(self):
        self.write([{'id':'c', 'type':'character', 'name':'改名后的阿青', 'last_updated':3,
            'location':'未来王城', 'secret':'未来秘密', 'state_history':[
                {'chapter':1, 'end_offset':7, 'state':{'id':'c', 'type':'character',
                    'name':'阿青', 'location':'旧城门', 'status':'受伤', 'known_by':['阿青']}}
            ]}])
        result = self.context(1, 8, '阿青')
        self.assertIn('旧城门', result['context_prompt'])
        self.assertIn('受伤', result['context_prompt'])
        self.assertNotIn('未来', result['context_prompt'])
        self.assertNotIn('改名', result['context_prompt'])

    def test_pov_requires_known_by_and_does_not_assume_participants_know(self):
        self.write([
            {'id':'seen','type':'event','chapter':1,'description':'阿青看到钥匙','known_by':['阿青']},
            {'id':'secret','type':'event','chapter':1,'description':'阿白暗号夜航','known_by':['阿白']},
            {'id':'unknown','type':'event','chapter':1,'description':'参与者不代表知情','participants':['阿青']},
        ])
        result = self.context(1, pov='阿青')
        self.assertIn('看到钥匙', result['context_prompt'])
        self.assertNotIn('夜航', result['context_prompt'])
        self.assertNotIn('参与者不代表知情', result['context_prompt'])

    def test_same_chapter_offset_and_zero_cutoff_are_not_unbounded(self):
        self.write([
            {'id':'early','type':'event','chapter':1,'source_position':{'chapter':1,'end':8},'description':'早段线索'},
            {'id':'late','type':'event','chapter':1,'source_position':{'chapter':1,'end':16},'description':'晚段秘密'},
            {'id':'unlocated','type':'event','chapter':1,'description':'本章未知位置'},
        ])
        text = self.context(1, 8)['context_prompt']
        self.assertIn('早段线索', text)
        self.assertNotIn('晚段秘密', text)
        self.assertNotIn('本章未知位置', text)
        self.assertEqual(self.context(1, 0)['context_prompt'], '')
        self.assertEqual(self.context(0)['context_prompt'], '')
        self.assertIn('晚段秘密', self.context(1, 16)['context_prompt'])

    def test_edges_and_evidence_are_both_preserved_and_filtered(self):
        self.write([
            {'id':'a','name':'阿青','type':'character','last_updated':1,'location':'城门'},
            {'id':'b','name':'阿白','type':'character','last_updated':1,'location':'城门'},
            {'id':'e','type':'event','chapter':1,'description':'两人重逢','known_by':['阿青'],
             'source_refs':[{'chapter':1,'quote':'你仍是我的师父。','source_path':'03_manuscript/第1章.md','start':1,'end':10},
                            {'chapter':3,'quote':'未来引文不可用。'},
                            {'chapter':1,'quote':'阿白独有的秘密。','known_by':['阿白']}]}
        ], [{'id':'r','type':'mentor','source':'b','target':'a','since_chapter':1,
             'description':'旧日师徒','known_by':['阿青']},
            {'id':'r3','type':'enemy','source':'a','target':'b','since_chapter':3,'description':'未来反目','known_by':['阿青']}])
        result = self.context(1,pov='阿青')
        self.assertEqual(result['relation_count'], 1)
        self.assertIn('旧日师徒', result['context_prompt'])
        self.assertIn('你仍是我的师父。', result['context_prompt'])
        self.assertIn('03_manuscript/第1章.md', result['context_prompt'])
        for text in ('未来引文','独有的秘密','未来反目'):
            self.assertNotIn(text,result['context_prompt'])

    def test_future_resolution_does_not_hide_old_unresolved_foreshadow(self):
        self.write([{'id':'f','type':'foreshadow','chapter_planted':1,'description':'旧伏笔',
                     'resolved':True,'resolved_chapter':3}])
        self.assertIn('旧伏笔',self.context(1)['context_prompt'])
        self.assertNotIn('旧伏笔',self.context(3)['context_prompt'])

    def test_update_records_history_and_does_not_reuse_old_source_position(self):
        self.write([{'id':'c','type':'character','name':'阿青','last_updated':1,
                     'source_position':{'chapter':1,'end':8},'location':'城门','status':'正常'}])
        args=argparse.Namespace(project_root=str(self.root),node_id='c',chapter=3,offset=5,
                                attrs=json.dumps({'location':'王城'},ensure_ascii=False))
        self.assertTrue(graph.cmd_update_node(args,graph.GraphConfig())['ok'])
        self.assertIn('城门',self.context(1)['context_prompt'])
        self.assertNotIn('王城',self.context(3,4)['context_prompt'])
        self.assertIn('王城',self.context(3,5)['context_prompt'])

    def test_invalid_cutoffs_rejected(self):
        self.write([])
        for chapter,offset in ((-1,None),(True,None),(1,-1),(1,True),(None,3)):
            with self.subTest(chapter=chapter,offset=offset),self.assertRaises(ValueError):
                self.context(chapter,offset)

    def test_repeated_same_chapter_updates_select_latest_at_chapter_end(self):
        self.write([{'id':'c','type':'character','name':'阿青','last_updated':1,'location':'城门'}])
        for location in ('驿站','客栈'):
            graph.cmd_update_node(argparse.Namespace(project_root=str(self.root),node_id='c',chapter=1,
                attrs=json.dumps({'location':location},ensure_ascii=False)),graph.GraphConfig())
        self.assertIn('客栈', self.context(1)['context_prompt'])
        self.assertNotIn('驿站', self.context(1)['context_prompt'])
        self.assertEqual(self.context(1,4)['context_prompt'], '')

    def test_update_without_time_does_not_backdate_new_state(self):
        self.write([{'id':'c','type':'character','name':'阿青','last_updated':1,'location':'城门'}])
        graph.cmd_update_node(argparse.Namespace(project_root=str(self.root),node_id='c',chapter=0,
            attrs=json.dumps({'location':'未知时间王城'},ensure_ascii=False)),graph.GraphConfig())
        self.assertEqual(self.context(1)['context_prompt'], '')
        self.assertNotIn('未知时间王城', self.context(1)['context_prompt'])
        self.assertIn('未知时间王城', self.context()['context_prompt'])

    def test_resolution_without_same_chapter_position_is_not_assumed_pending(self):
        self.write([{'id':'f','type':'foreshadow','chapter_planted':1,'description':'已解但不知何时',
            'resolved':True,'resolved_chapter':2}])
        self.assertNotIn('已解但不知何时', self.context(2,8)['context_prompt'])
        self.assertTrue(self.context(2,8)['omissions'])

    def test_later_precisely_located_state_supersedes_an_unlocated_old_version(self):
        self.write([{'id':'c','type':'character','name':'阿青','last_updated':3,'location':'客栈',
            'source_position':{'chapter':3,'end':12},'state_history':[
                {'chapter':3,'end_offset':None,'state':{'id':'c','type':'character','name':'阿青','location':'驿站'}}]}])
        self.assertEqual(self.context(3,11)['context_prompt'], '')
        self.assertIn('客栈',self.context(3,12)['context_prompt'])

    def test_reference_chapter_path_cannot_inherit_an_earlier_parent_time(self):
        self.write([{'id':'e','type':'event','chapter':1,'description':'旧线索','known_by':['阿青'],
            'source_refs':[{'source_path':'03_manuscript/第3章 揭晓.md','quote':'未来答案蓝鲸','start':0,'end':8},
                {'source_path':'03_manuscript/第1章 初遇.md','quote':'当前允许的引文','start':0,'end':8},
                {'source_path':'unknown.txt','quote':'来源时间未知的引文'},
                {'source_path':'03_manuscript/第3章 揭晓.md','chapter':1,'quote':'时间标记冲突的引文'}]}])
        result=self.context(1,pov='阿青')
        self.assertIn('当前允许的引文',result['context_prompt'])
        for forbidden in ('未来答案蓝鲸','来源时间未知','时间标记冲突'):
            self.assertNotIn(forbidden,result['context_prompt'])

    def test_partial_update_cannot_backdate_future_fields(self):
        self.write([{'id':'c','type':'character','name':'阿青','last_updated':3,
            'location':'未来王城','status':'健康'}])
        before=self.path.read_bytes()
        for chapter,offset in ((1,None),(3,12)):
            with self.subTest(chapter=chapter,offset=offset),self.assertRaises(ValueError):
                graph.cmd_update_node(argparse.Namespace(project_root=str(self.root),node_id='c',
                    chapter=chapter,offset=offset,attrs=json.dumps({'status':'受伤'})),graph.GraphConfig())
        self.assertEqual(before,self.path.read_bytes())
        self.assertNotIn('未来王城',self.context(1)['context_prompt'])

    def test_legacy_unbounded_character_context_is_compatible(self):
        self.write([{'id':'c','name':'阿青','type':'character','location':'城门'}])
        self.assertIn('城门',self.context()['context_prompt'])

    def test_epistemic_status_survives_event_projection(self):
        self.write([{'id':'e','type':'event','chapter':1,'description':'模仿犯案',
                     'epistemic_status':'character_inference_not_solved_case'}])
        self.assertIn('[character_inference_not_solved_case]',self.context(1)['context_prompt'])


if __name__ == '__main__':
    unittest.main()
