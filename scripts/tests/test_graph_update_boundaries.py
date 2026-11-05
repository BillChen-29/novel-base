"""Production update application must preserve the builder's temporal contract."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import story_graph_builder as builder
import story_graph_updater as updater


class GraphUpdateBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '00_memory/graph_updates').mkdir(parents=True)
        self.path = self.root / '00_memory/story_graph.json'
        self.path.write_text(json.dumps({'nodes':[{'id':'c','type':'character','name':'阿青',
            'last_updated':1,'location':'城门','status':'正常','known_by':['阿青']}],'edges':[]}))

    def apply(self, updates):
        (self.root / '00_memory/graph_updates/ch0003_updates.json').write_text(
            json.dumps({'chapter':3,'updates':updates},ensure_ascii=False))
        return updater.cmd_apply(argparse.Namespace(project_root=str(self.root),chapter=3,
            force_low_confidence=False),updater.UpdaterConfig())

    def context(self, chapter, offset=None):
        return builder.cmd_context(argparse.Namespace(project_root=str(self.root),chapter=0,
            cutoff_chapter=chapter,cutoff_offset=offset,pov_character=None,
            max_events=20,max_foreshadows=20),builder.GraphConfig())['context_prompt']

    def test_apply_preserves_old_state_and_passes_same_chapter_offset(self):
        result=self.apply([{'type':'update-node','node_id':'c','chapter':3,'offset':12,
            'attrs':{'location':'王城'},'confidence':'high'}])
        self.assertTrue(result['ok'],result)
        self.assertIn('城门',self.context(1))
        self.assertNotIn('王城',self.context(3,11))
        self.assertIn('王城',self.context(3,12))
        node=json.loads(self.path.read_text())['nodes'][0]
        self.assertEqual(node['known_by'],['阿青'])
        self.assertTrue(node['state_history'])

    def test_add_node_cannot_backdate_attrs_and_does_not_invent_knowledge(self):
        result=self.apply([{'type':'add-node','node_type':'event','name':'新增发现',
            'chapter':3,'offset':12,'confidence':'high',
            'attrs':{'description':'新线索','chapter':3,'last_updated':1,
                     'source_position':{'chapter':1,'end':2},'participants':['阿青']}}])
        self.assertFalse(result['ok'],result)
        self.assertEqual(result['applied'],0)
        self.assertNotIn('新线索',self.context(1))
        result=self.apply([{'type':'add-node','node_type':'event','name':'新增发现',
            'chapter':3,'offset':12,'confidence':'high',
            'attrs':{'description':'新线索','chapter':3,'participants':['阿青']}}])
        self.assertTrue(result['ok'],result)
        self.assertNotIn('新线索',self.context(3,11))
        self.assertIn('新线索',self.context(3,12))
        node=json.loads(self.path.read_text())['nodes'][-1]
        self.assertNotIn('known_by',node)

    def test_unlocated_update_is_chapter_level_not_arbitrary_character_level(self):
        result=self.apply([{'type':'update-node','node_id':'c','chapter':3,
            'attrs':{'location':'驿站'},'confidence':'high'}])
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.context(3,500), '')
        self.assertNotIn('驿站',self.context(3,500))
        self.assertIn('驿站',self.context(3))

    def test_update_entry_cannot_claim_an_earlier_chapter_than_its_apply_batch(self):
        before=self.path.read_bytes()
        result=self.apply([{'type':'update-node','node_id':'c','chapter':1,
            'attrs':{'location':'被回填的新地点'},'confidence':'high'}])
        self.assertFalse(result['ok'])
        self.assertEqual(before,self.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
