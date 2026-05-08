#!/usr/bin/env python3
"""
gate_extensions.py + gate_runner.py 测试

测试用例：
  - test_skip_when_truth_missing: truth 文件不存在时跳过
  - test_hook_health_pass: 无问题时 passed=True
  - test_hook_health_fail: 存在 stale_debt 时 passed=False
  - test_resource_consistency_pass: 资源正常
  - test_resource_consistency_fail: 突变检测
  - test_emotional_arc_pass: 情感正常
  - test_emotional_arc_fail: 情感突变
  - test_subplot_progress_pass: 支线正常
  - test_subplot_progress_fail: 支线过多
  - test_chapter_distance_pass: 字数合理
  - test_chapter_distance_fail: 字数差距大
  - test_run_full_gate_structure: gate_runner 输出结构正确
"""

from __future__ import annotations
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 确保 scripts/ 在 sys.path 中
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import gate_extensions  # noqa: E402
import truth_manager  # noqa: E402


class _BaseTestCase(unittest.TestCase):
    """所有测试的基类，提供临时项目目录"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.project_root = self._tmp

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _ensure_truth_dir(self):
        truth_manager.ensure_truth_dir(self.project_root)

    def _write_truth(self, file_name: str, data: dict):
        self._ensure_truth_dir()
        truth_manager.save_truth(self.project_root, file_name, data)


# ===========================================================================
# 跳过逻辑
# ===========================================================================

class TestSkipWhenTruthMissing(_BaseTestCase):
    """truth 文件不存在时，所有扩展检查应返回 passed=True"""

    def test_hook_health_skip(self):
        result = gate_extensions.check_hook_health(self.project_root, 1)
        self.assertTrue(result["passed"])
        self.assertEqual(result["issues"], [])
        self.assertIn("跳过", result["details"])

    def test_resource_consistency_skip(self):
        result = gate_extensions.check_resource_consistency(self.project_root, 1)
        self.assertTrue(result["passed"])
        self.assertIn("跳过", result["details"])

    def test_emotional_arc_skip(self):
        result = gate_extensions.check_emotional_arc(self.project_root, 1)
        self.assertTrue(result["passed"])
        self.assertIn("跳过", result["details"])

    def test_subplot_progress_skip(self):
        result = gate_extensions.check_subplot_progress(self.project_root, 1)
        self.assertTrue(result["passed"])
        self.assertIn("跳过", result["details"])

    def test_chapter_distance_skip(self):
        result = gate_extensions.check_chapter_distance(self.project_root, 1)
        self.assertTrue(result["passed"])
        self.assertIn("跳过", result["details"])


# ===========================================================================
# check_hook_health
# ===========================================================================

class TestHookHealth(_BaseTestCase):

    def test_pass_no_issues(self):
        """无钩子数据时通过"""
        self._write_truth("hook_ledger", {"hooks": [], "health": {}})
        result = gate_extensions.check_hook_health(self.project_root, 1)
        self.assertTrue(result["passed"])

    def test_fail_stale_debt(self):
        """超期钩子 → fail"""
        hooks = [{
            "id": "h1", "status": "open", "description": "测试钩子",
            "deadline_chapter": 3, "planted_chapter": 1, "mentions": [1],
        }]
        self._write_truth("hook_ledger", {"hooks": hooks, "health": {}})
        result = gate_extensions.check_hook_health(self.project_root, 5)
        self.assertFalse(result["passed"])
        self.assertTrue(any("超期" in i for i in result["issues"]))


# ===========================================================================
# check_resource_consistency
# ===========================================================================

class TestResourceConsistency(_BaseTestCase):

    def test_pass_normal(self):
        """资源变化合理时通过"""
        self._write_truth("resource_ledger", {"resources": [{
            "id": "r1", "name": "金币", "type": "currency", "owner": "主角",
            "amount": 100, "history": [
                {"chapter": 1, "amount": 100, "event": "初始"},
                {"chapter": 2, "amount": 120, "event": "任务奖励"},
            ],
        }], "power_levels": []})
        result = gate_extensions.check_resource_consistency(self.project_root, 2)
        self.assertTrue(result["passed"])

    def test_fail_sudden_change(self):
        """突变（>10倍无事件）→ fail"""
        self._write_truth("resource_ledger", {"resources": [{
            "id": "r1", "name": "金币", "type": "currency", "owner": "主角",
            "amount": 100, "history": [
                {"chapter": 1, "amount": 100, "event": "初始"},
                {"chapter": 2, "amount": 2000, "event": ""},
            ],
        }], "power_levels": []})
        result = gate_extensions.check_resource_consistency(self.project_root, 2)
        self.assertFalse(result["passed"])
        self.assertTrue(any("突变" in i for i in result["issues"]))


# ===========================================================================
# check_emotional_arc
# ===========================================================================

class TestEmotionalArc(_BaseTestCase):

    def test_pass_normal(self):
        self._write_truth("emotional_arcs", {"characters": {
            "张三": {"arc": [
                {"chapter": 1, "emotion": "开心", "intensity": 5, "trigger": "得奖"},
                {"chapter": 2, "emotion": "兴奋", "intensity": 7, "trigger": "冒险"},
            ], "current_emotion": "兴奋", "arc_direction": "上升"},
        }})
        result = gate_extensions.check_emotional_arc(self.project_root, 2)
        self.assertTrue(result["passed"])

    def test_fail_sudden_change(self):
        """情绪强度突变>5 且无 trigger → fail"""
        self._write_truth("emotional_arcs", {"characters": {
            "张三": {"arc": [
                {"chapter": 1, "emotion": "开心", "intensity": 3, "trigger": "得奖"},
                {"chapter": 2, "emotion": "绝望", "intensity": 10, "trigger": ""},
            ], "current_emotion": "绝望", "arc_direction": "上升"},
        }})
        result = gate_extensions.check_emotional_arc(self.project_root, 2)
        self.assertFalse(result["passed"])
        self.assertTrue(any("情感突变" in i for i in result["issues"]))


# ===========================================================================
# check_subplot_progress
# ===========================================================================

class TestSubplotProgress(_BaseTestCase):

    def test_pass_normal(self):
        self._write_truth("subplot_board", {"subplots": [{
            "id": "s1", "name": "支线A", "status": "active",
            "started_chapter": 1, "last_mentioned_chapter": 5,
            "key_characters": ["张三"], "tension_level": "medium",
        }]})
        result = gate_extensions.check_subplot_progress(self.project_root, 5)
        self.assertTrue(result["passed"])

    def test_fail_too_many(self):
        """活跃支线>5 → fail"""
        subplots = [{
            "id": f"s{i}", "name": f"支线{i}", "status": "active",
            "started_chapter": 1, "last_mentioned_chapter": 5,
            "key_characters": [], "tension_level": "medium",
        } for i in range(6)]
        self._write_truth("subplot_board", {"subplots": subplots})
        result = gate_extensions.check_subplot_progress(self.project_root, 5)
        self.assertFalse(result["passed"])
        self.assertTrue(any("过多" in i for i in result["issues"]))


# ===========================================================================
# check_chapter_distance
# ===========================================================================

class TestChapterDistance(_BaseTestCase):

    def test_pass_normal(self):
        self._write_truth("chapter_summaries", {"chapters": [
            {"chapter": 1, "char_count": 3000},
            {"chapter": 2, "char_count": 3500},
        ]})
        result = gate_extensions.check_chapter_distance(self.project_root, 2)
        self.assertTrue(result["passed"])

    def test_fail_large_gap(self):
        """字数差距>3倍 → fail"""
        self._write_truth("chapter_summaries", {"chapters": [
            {"chapter": 1, "char_count": 1000},
            {"chapter": 2, "char_count": 5000},
        ]})
        result = gate_extensions.check_chapter_distance(self.project_root, 2)
        self.assertFalse(result["passed"])
        self.assertTrue(any("差距过大" in i for i in result["issues"]))


# ===========================================================================
# gate_runner 输出结构
# ===========================================================================

class TestGateRunnerStructure(_BaseTestCase):
    """验证 gate_runner 输出的 JSON 结构"""

    def test_output_schema(self):
        """输出包含 passed + steps 且 10 个步骤键"""
        from gate_runner import run_full_gate

        # 创建最小项目结构
        manuscript = Path(self.project_root) / "03_manuscript"
        manuscript.mkdir(parents=True, exist_ok=True)
        ch_file = manuscript / "第001章_测试.md"
        ch_file.write_text("# 第001章 测试\n\n这是一段测试内容。\n", encoding="utf-8")

        gate_dir = Path(self.project_root) / "04_editing" / "gate_artifacts" / "第001章_测试"
        gate_dir.mkdir(parents=True, exist_ok=True)

        # 创建最小门禁产物
        for fname in ["memory_update.md", "consistency_report.md", "style_calibration.md",
                       "copyedit_report.md", "publish_ready.md", "quality_report.md"]:
            (gate_dir / fname).write_text(f"测试产物 - {fname}\n通过：True\n", encoding="utf-8")
        (gate_dir / "publish_ready.md").write_text("可发布\n", encoding="utf-8")

        result = run_full_gate(self.project_root, str(ch_file), min_bytes=5)

        # 验证结构
        self.assertIn("passed", result)
        self.assertIn("steps", result)
        expected_steps = [
            "memory_sync", "consistency", "style_calibration", "proofreading", "gate_script",
            "hook_health", "resource_consistency", "emotional_arc", "subplot_progress", "chapter_distance",
        ]
        for step in expected_steps:
            self.assertIn(step, result["steps"], f"缺少步骤: {step}")
            self.assertIn("passed", result["steps"][step])
            self.assertIn("issues", result["steps"][step])

        # 验证 gate_result.json 已写入
        gr_path = gate_dir / "gate_result.json"
        self.assertTrue(gr_path.exists())
        saved = json.loads(gr_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["passed"], result["passed"])


if __name__ == "__main__":
    unittest.main()
