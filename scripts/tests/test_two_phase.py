#!/usr/bin/env python3
"""
Two-Phase Writer 系统测试

测试覆盖：
- Observer prompt 加载
- Observer 输入组装
- Observer 输出解析（有效JSON、无效JSON、空输出）
- Reflector 更新（hook/resource/emotion/subplot/character/world）
- Reflector 错误处理（无效delta、空delta）
- Two phase writer 的 Phase 1 组装
- Auto truth sync 的端到端流程
"""

from __future__ import annotations
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保 scripts/ 在 sys.path 中
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import schemas  # noqa: E402
import truth_manager  # noqa: E402
from chapter_observer import (  # noqa: E402
    load_observer_prompt,
    assemble_observer_input,
    parse_observer_output,
    DELTA_FIELDS,
    _ensure_delta_schema,
    _strip_code_block,
)
from chapter_reflector import reflect  # noqa: E402
from two_phase_writer import phase1_assemble  # noqa: E402
from auto_truth_sync import auto_sync  # noqa: E402
from truth_sync_report import generate_report, format_report  # noqa: E402


# =============================================================================
# 测试辅助
# =============================================================================

def _create_test_project(tmp_dir: Path) -> str:
    """创建最小测试项目结构和真相文件。"""
    project_root = str(tmp_dir)

    # 确保目录存在
    truth_dir = tmp_dir / "00_memory" / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    manuscript_dir = tmp_dir / "03_manuscript"
    manuscript_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = tmp_dir / "00_memory" / "retrieval" / "chapter_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    # 写入最小真相文件
    world_state = {"world_name": "测试世界", "magic_system": "", "tech_level": "",
                   "history": [], "locations": [], "rules": [], "notes": ""}
    (truth_dir / "world_state.json").write_text(json.dumps(world_state, ensure_ascii=False), encoding="utf-8")

    character_matrix = {"characters": []}
    (truth_dir / "character_matrix.json").write_text(json.dumps(character_matrix, ensure_ascii=False), encoding="utf-8")

    emotional_arcs = {"characters": {}}
    (truth_dir / "emotional_arcs.json").write_text(json.dumps(emotional_arcs, ensure_ascii=False), encoding="utf-8")

    resource_ledger = {"resources": [], "power_levels": []}
    (truth_dir / "resource_ledger.json").write_text(json.dumps(resource_ledger, ensure_ascii=False), encoding="utf-8")

    subplot_board = {"subplots": []}
    (truth_dir / "subplot_board.json").write_text(json.dumps(subplot_board, ensure_ascii=False), encoding="utf-8")

    hook_ledger = {"hooks": [], "health": {"stale_debt": [], "burst_warning": [], "no_advance": []}}
    (truth_dir / "hook_ledger.json").write_text(json.dumps(hook_ledger, ensure_ascii=False), encoding="utf-8")

    chapter_summaries = {"chapters": []}
    (truth_dir / "chapter_summaries.json").write_text(json.dumps(chapter_summaries, ensure_ascii=False), encoding="utf-8")

    # 写入测试章节
    chapter_file = manuscript_dir / "第1章 测试章节.md"
    chapter_file.write_text("# 第1章 测试章节\n\n这是测试内容。李华走进了森林，遇到了一位老人。\n老人给了他一把剑。\n", encoding="utf-8")

    return project_root


def _make_valid_delta() -> dict:
    """生成一个有效的 delta 字典。"""
    return {
        "new_characters": [
            {
                "name": "老人",
                "role": "导师",
                "personality": "慈祥",
                "motivation": "寻找传人",
                "abilities": ["剑术"],
                "relationships": {"李华": "师徒"},
                "status": "alive",
                "notes": "神秘老人",
            }
        ],
        "relationship_changes": [
            {"character": "李华", "target": "老人", "relationship": "师徒"}
        ],
        "resource_changes": [
            {"name": "神秘剑", "type": "item", "owner": "李华", "amount": 1, "event": "老人赠剑"}
        ],
        "power_level_changes": [
            {"character": "李华", "level": "初级", "event": "获得神秘剑"}
        ],
        "emotion_changes": [
            {"character": "李华", "emotion": "惊喜", "intensity": 7, "trigger": "获得神秘剑"}
        ],
        "hook_operations": [
            {
                "operation": "create",
                "description": "老人的身份之谜",
                "type": "mystery",
                "importance": "high",
                "related_characters": ["老人"],
            }
        ],
        "subplot_progress": [
            {
                "operation": "create",
                "name": "老人的过去",
                "status": "active",
                "key_characters": ["老人"],
            }
        ],
        "world_additions": [
            {"operation": "add_location", "name": "迷雾森林", "description": "一片古老的森林"}
        ],
        "timeline_advance": {
            "chapter_summary": "李华在森林中遇到老人，获得神秘剑",
            "key_events": ["进入森林", "遇到老人", "获得神秘剑"],
            "characters_involved": ["李华", "老人"],
        },
    }


# =============================================================================
# Observer 测试
# =============================================================================

class TestObserverPrompt(unittest.TestCase):
    """Observer prompt 加载测试。"""

    def test_load_prompt_success(self):
        """测试 prompt 加载成功。"""
        prompt = load_observer_prompt()
        self.assertIsInstance(prompt, str)
        self.assertIn("{chapter_text}", prompt)
        self.assertIn("{current_truth}", prompt)
        self.assertIn("小说状态提取器", prompt)
        self.assertIn("new_characters", prompt)
        self.assertIn("hook_operations", prompt)

    def test_load_prompt_has_9_fields(self):
        """测试 prompt 包含 9 个字段。"""
        prompt = load_observer_prompt()
        for field in DELTA_FIELDS:
            self.assertIn(field, prompt, f"prompt 缺少字段: {field}")

    def test_load_prompt_has_placeholders(self):
        """测试 prompt 包含占位符。"""
        prompt = load_observer_prompt()
        self.assertIn("{chapter_text}", prompt)
        self.assertIn("{current_truth}", prompt)

    def test_load_prompt_rules(self):
        """测试 prompt 包含提取规则。"""
        prompt = load_observer_prompt()
        self.assertIn("只提取新事实", prompt)
        self.assertIn("不要重复已有信息", prompt)
        self.assertIn("JSON", prompt)


class TestObserverAssemble(unittest.TestCase):
    """Observer 输入组装测试。"""

    def test_assemble_basic(self):
        """测试基本组装。"""
        prompt = assemble_observer_input("章节正文内容", "真相状态内容")
        self.assertIn("章节正文内容", prompt)
        self.assertIn("真相状态内容", prompt)
        self.assertNotIn("{chapter_text}", prompt)
        self.assertNotIn("{current_truth}", prompt)

    def test_assemble_multiline(self):
        """测试多行文本组装。"""
        chapter = "第一行\n第二行\n第三行"
        truth = "真相1\n真相2"
        prompt = assemble_observer_input(chapter, truth)
        self.assertIn("第一行", prompt)
        self.assertIn("真相1", prompt)

    def test_assemble_empty_strings(self):
        """测试空字符串。"""
        prompt = assemble_observer_input("", "")
        self.assertIsInstance(prompt, str)
        self.assertNotIn("{chapter_text}", prompt)

    def test_assemble_preserves_template_structure(self):
        """测试保留模板结构。"""
        prompt = assemble_observer_input("text", "truth")
        self.assertIn("输出格式", prompt)
        self.assertIn("提取规则", prompt)


class TestObserverParse(unittest.TestCase):
    """Observer 输出解析测试。"""

    def test_parse_valid_json(self):
        """测试解析有效 JSON。"""
        delta = _make_valid_delta()
        output = json.dumps(delta, ensure_ascii=False)
        result, errors = parse_observer_output(output)

        self.assertIsNotNone(result)
        self.assertEqual(len(errors), 0)
        self.assertEqual(result["new_characters"][0]["name"], "老人")
        self.assertEqual(len(result["hook_operations"]), 1)
        self.assertEqual(result["timeline_advance"]["chapter_summary"], "李华在森林中遇到老人，获得神秘剑")

    def test_parse_json_with_code_block(self):
        """测试解析带 markdown 代码块的 JSON。"""
        delta = _make_valid_delta()
        output = f"```json\n{json.dumps(delta, ensure_ascii=False)}\n```"
        result, errors = parse_observer_output(output)

        self.assertIsNotNone(result)
        self.assertEqual(len(errors), 0)
        self.assertIn("new_characters", result)

    def test_parse_empty_output(self):
        """测试解析空输出。"""
        result, errors = parse_observer_output("")
        self.assertIsNone(result)
        self.assertTrue(len(errors) > 0)
        self.assertIn("空", errors[0])

    def test_parse_none_output(self):
        """测试解析 None。"""
        result, errors = parse_observer_output(None)
        self.assertIsNone(result)
        self.assertTrue(len(errors) > 0)

    def test_parse_invalid_json(self):
        """测试解析无效 JSON。"""
        result, errors = parse_observer_output("this is not json {{{")
        self.assertIsNone(result)
        self.assertTrue(len(errors) > 0)

    def test_parse_partial_json(self):
        """测试解析部分 JSON（包含在文本中）。"""
        delta = {"new_characters": [], "timeline_advance": {"chapter_summary": "测试"}}
        text = f"以下是结果：\n{json.dumps(delta, ensure_ascii=False)}\n以上。"
        result, errors = parse_observer_output(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["timeline_advance"]["chapter_summary"], "测试")

    def test_parse_missing_fields_defaults(self):
        """测试缺少字段时填充默认值。"""
        output = '{"new_characters": []}'
        result, errors = parse_observer_output(output)
        self.assertIsNotNone(result)
        self.assertEqual(result["hook_operations"], [])
        self.assertEqual(result["timeline_advance"], {})
        self.assertEqual(result["world_additions"], [])

    def test_parse_non_dict_output(self):
        """测试非字典输出。"""
        result, errors = parse_observer_output('"just a string"')
        self.assertIsNone(result)
        self.assertTrue(len(errors) > 0)

    def test_parse_list_output(self):
        """测试列表输出（非字典）。"""
        result, errors = parse_observer_output('[1, 2, 3]')
        self.assertIsNone(result)
        self.assertTrue(len(errors) > 0)

    def test_parse_whitespace_only(self):
        """测试纯空白输出。"""
        result, errors = parse_observer_output("   \n  \n  ")
        self.assertIsNone(result)
        self.assertTrue(len(errors) > 0)


class TestObserverStripCodeBlock(unittest.TestCase):
    """_strip_code_block 测试。"""

    def test_strip_json_block(self):
        """测试去除 json 代码块。"""
        text = '```json\n{"key": "value"}\n```'
        result = _strip_code_block(text)
        self.assertEqual(result, '{"key": "value"}')

    def test_strip_plain_block(self):
        """测试去除普通代码块。"""
        text = '```\n{"key": "value"}\n```'
        result = _strip_code_block(text)
        self.assertEqual(result, '{"key": "value"}')

    def test_no_block(self):
        """测试无代码块包裹。"""
        text = '{"key": "value"}'
        result = _strip_code_block(text)
        self.assertEqual(result, '{"key": "value"}')


class TestObserverEnsureSchema(unittest.TestCase):
    """_ensure_delta_schema 测试。"""

    def test_empty_dict(self):
        """测试空字典填充。"""
        result = _ensure_delta_schema({})
        for field in DELTA_FIELDS:
            self.assertIn(field, result)

    def test_partial_dict(self):
        """测试部分字段。"""
        result = _ensure_delta_schema({"new_characters": [{"name": "test"}]})
        self.assertEqual(len(result["new_characters"]), 1)
        self.assertEqual(result["hook_operations"], [])


# =============================================================================
# Reflector 测试
# =============================================================================

class TestReflector(unittest.TestCase):
    """Reflector 更新测试。"""

    def setUp(self):
        """创建测试项目。"""
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = _create_test_project(Path(self.tmp_dir))
        self.chapter = 1

    def tearDown(self):
        """清理测试项目。"""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_reflect_empty_delta(self):
        """测试空 delta。"""
        result = reflect(self.project_root, {}, self.chapter)
        self.assertEqual(result["updated"], [])
        self.assertEqual(result["errors"], [])

    def test_reflect_none_delta(self):
        """测试 None delta。"""
        result = reflect(self.project_root, None, self.chapter)
        self.assertTrue(len(result["errors"]) > 0)

    def test_reflect_invalid_delta(self):
        """测试无效 delta（非 dict）。"""
        result = reflect(self.project_root, "not a dict", self.chapter)
        self.assertTrue(len(result["errors"]) > 0)

    def test_reflect_hook_create(self):
        """测试创建钩子。"""
        delta = {
            "hook_operations": [
                {
                    "operation": "create",
                    "description": "测试伏笔",
                    "type": "foreshadowing",
                    "importance": "high",
                }
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("hook:create" in u for u in result["updated"]))
        # 验证钩子已创建
        data, _ = truth_manager.load_truth(self.project_root, "hook_ledger")
        self.assertEqual(len(data["hooks"]), 1)
        self.assertEqual(data["hooks"][0]["description"], "测试伏笔")

    def test_reflect_hook_mention(self):
        """测试提及钩子。"""
        # 先创建一个钩子
        truth_manager.upsert_hook(self.project_root, 1, "测试钩子", id="hook-001")
        delta = {
            "hook_operations": [
                {"operation": "mention", "hook_id": "hook-001"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("hook:mention" in u for u in result["updated"]))

    def test_reflect_hook_resolve(self):
        """测试回收钩子。"""
        truth_manager.upsert_hook(self.project_root, 1, "测试钩子", id="hook-001")
        delta = {
            "hook_operations": [
                {"operation": "resolve", "hook_id": "hook-001"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("hook:resolve" in u for u in result["updated"]))

    def test_reflect_resource_add(self):
        """测试添加资源。"""
        delta = {
            "resource_changes": [
                {"name": "金剑", "type": "item", "owner": "李华", "amount": 1}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("resource:add" in u for u in result["updated"]))
        data, _ = truth_manager.load_truth(self.project_root, "resource_ledger")
        self.assertTrue(len(data["resources"]) > 0)

    def test_reflect_emotion_add(self):
        """测试添加情感点。"""
        delta = {
            "emotion_changes": [
                {"character": "李华", "emotion": "开心", "intensity": 8, "trigger": "获得宝剑"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("emotion:add" in u for u in result["updated"]))
        arc = truth_manager.get_character_arc(self.project_root, "李华")
        self.assertIsNotNone(arc)
        self.assertEqual(arc["current_emotion"], "开心")

    def test_reflect_subplot_create(self):
        """测试创建支线。"""
        delta = {
            "subplot_progress": [
                {"operation": "create", "name": "身世之谜", "key_characters": ["李华"]}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("subplot:create" in u for u in result["updated"]))
        data, _ = truth_manager.load_truth(self.project_root, "subplot_board")
        self.assertEqual(len(data["subplots"]), 1)
        self.assertEqual(data["subplots"][0]["name"], "身世之谜")

    def test_reflect_subplot_update(self):
        """测试更新支线。"""
        success, sub_id, _ = truth_manager.add_subplot(self.project_root, "测试支线", 1)
        self.assertTrue(success, f"add_subplot 失败")
        delta = {
            "subplot_progress": [
                {"operation": "update", "subplot_id": sub_id, "status": "resolved"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("subplot:update" in u for u in result["updated"]))

    def test_reflect_character_upsert(self):
        """测试新增角色。"""
        delta = {
            "new_characters": [
                {"name": "张三", "role": "配角", "personality": "善良", "status": "alive"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("character:upsert" in u for u in result["updated"]))
        char = truth_manager.get_character(self.project_root, "张三")
        self.assertIsNotNone(char)
        self.assertEqual(char["role"], "配角")

    def test_reflect_world_add_location(self):
        """测试添加地点。"""
        delta = {
            "world_additions": [
                {"operation": "add_location", "name": "龙城", "description": "繁华都市"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("world:add_location" in u for u in result["updated"]))
        data, _ = truth_manager.load_truth(self.project_root, "world_state")
        self.assertTrue(any(loc["name"] == "龙城" for loc in data["locations"]))

    def test_reflect_world_update(self):
        """测试更新世界状态。"""
        delta = {
            "world_additions": [
                {"operation": "update_world", "name": "magic_system", "description": "元素魔法"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("world:update_world" in u for u in result["updated"]))

    def test_reflect_relationship_change(self):
        """测试关系变化。"""
        # 先创建角色
        truth_manager.upsert_character(self.project_root, "李华", role="主角")
        delta = {
            "relationship_changes": [
                {"character": "李华", "target": "王五", "relationship": "兄弟"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("relationship:update" in u for u in result["updated"]))

    def test_reflect_power_level(self):
        """测试力量等级变化。"""
        delta = {
            "power_level_changes": [
                {"character": "李华", "level": "筑基期", "event": "突破"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("power_level:update" in u for u in result["updated"]))

    def test_reflect_timeline_advance(self):
        """测试时间线推进。"""
        delta = {
            "timeline_advance": {
                "chapter_summary": "李华踏上旅途",
                "key_events": ["出发"],
                "characters_involved": ["李华"],
            }
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("timeline:advance" in u for u in result["updated"]))

    def test_reflect_full_delta(self):
        """测试完整 delta。"""
        delta = _make_valid_delta()
        result = reflect(self.project_root, delta, self.chapter)
        # 至少应该有一些更新
        self.assertTrue(len(result["updated"]) > 0, f"应该有更新，errors: {result['errors']}")
        print(f"  Full delta: {len(result['updated'])} updates, {len(result['errors'])} errors")

    def test_reflect_hook_create_missing_id(self):
        """测试缺少 hook_id 的 mention 操作。"""
        delta = {
            "hook_operations": [
                {"operation": "mention"}  # 缺少 hook_id
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("hook_id" in e for e in result["errors"]))

    def test_reflect_unknown_hook_operation(self):
        """测试未知 hook 操作。"""
        delta = {
            "hook_operations": [
                {"operation": "delete"}  # 未知操作
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("未知" in e for e in result["errors"]))

    def test_reflect_hook_mention_nonexistent(self):
        """测试提及不存在的钩子。"""
        delta = {
            "hook_operations": [
                {"operation": "mention", "hook_id": "hook-999"}
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(len(result["errors"]) > 0)

    def test_reflect_resource_missing_name(self):
        """测试资源缺少 name。"""
        delta = {
            "resource_changes": [
                {"type": "item", "owner": "李华"}  # 缺少 name
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("name" in e for e in result["errors"]))

    def test_reflect_emotion_missing_character(self):
        """测试情感缺少 character。"""
        delta = {
            "emotion_changes": [
                {"emotion": "开心", "intensity": 5}  # 缺少 character
            ]
        }
        result = reflect(self.project_root, delta, self.chapter)
        self.assertTrue(any("character" in e for e in result["errors"]))


# =============================================================================
# Two Phase Writer 测试
# =============================================================================

class TestTwoPhaseWriter(unittest.TestCase):
    """Two phase writer Phase 1 组装测试。"""

    def setUp(self):
        """创建测试项目。"""
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = _create_test_project(Path(self.tmp_dir))

    def tearDown(self):
        """清理测试项目。"""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_phase1_assemble_basic(self):
        """测试 Phase 1 基本组装。"""
        result = phase1_assemble(self.project_root, 1)
        self.assertIn("truth_text", result)
        self.assertIn("search_results", result)
        self.assertIn("filtered_results", result)
        self.assertIn("weighted_results", result)
        self.assertIn("scenarios", result)
        self.assertIn("chapter_info", result)
        self.assertIsInstance(result["truth_text"], str)
        self.assertTrue(len(result["truth_text"]) > 0)

    def test_phase1_assemble_truth_text(self):
        """测试 Phase 1 真相文件文本包含关键内容。"""
        result = phase1_assemble(self.project_root, 1)
        truth = result["truth_text"]
        self.assertIn("world_state", truth)
        self.assertIn("character_matrix", truth)
        self.assertIn("hook_ledger", truth)

    def test_phase1_assemble_scenarios(self):
        """测试 Phase 1 场景模板加载。"""
        result = phase1_assemble(self.project_root, 1)
        self.assertIsInstance(result["scenarios"], list)

    def test_phase1_assemble_weighted_results(self):
        """测试 Phase 1 距离加权结果。"""
        result = phase1_assemble(self.project_root, 1)
        self.assertIsInstance(result["weighted_results"], list)


# =============================================================================
# Auto Truth Sync 测试
# =============================================================================

class TestAutoTruthSync(unittest.TestCase):
    """Auto truth sync 端到端流程测试。"""

    def setUp(self):
        """创建测试项目。"""
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = _create_test_project(Path(self.tmp_dir))

    def tearDown(self):
        """清理测试项目。"""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_auto_sync_prompt_only(self):
        """测试只生成 prompt（无 delta）。"""
        result = auto_sync(self.project_root, 1)
        self.assertTrue(len(result["prompt"]) > 0)
        self.assertIsNone(result["delta"])
        self.assertIsNone(result["reflect_result"])

    def test_auto_sync_with_delta(self):
        """测试带 delta 的完整同步。"""
        delta = _make_valid_delta()
        result = auto_sync(self.project_root, 1, delta=delta)
        self.assertTrue(len(result["prompt"]) > 0)
        self.assertIsNotNone(result["delta"])
        self.assertIsNotNone(result["reflect_result"])
        self.assertTrue(len(result["reflect_result"]["updated"]) > 0)

    def test_auto_sync_with_custom_text(self):
        """测试使用自定义章节文本。"""
        text = "李华来到了一座古城，遇到了一位老者。"
        result = auto_sync(self.project_root, 1, chapter_text=text)
        self.assertIn("李华", result["prompt"])
        self.assertIn("古城", result["prompt"])

    def test_auto_sync_empty_chapter(self):
        """测试空章节。"""
        # 删除测试章节
        chapter_file = Path(self.project_root) / "03_manuscript" / "第1章 测试章节.md"
        chapter_file.unlink()
        result = auto_sync(self.project_root, 1)
        self.assertTrue(len(result["errors"]) > 0)

    def test_auto_sync_invalid_project(self):
        """测试无效项目目录。"""
        result = auto_sync("/nonexistent/path", 1)
        # 应该能执行但可能报错（取决于 _read_chapter_text 的行为）


# =============================================================================
# Truth Sync Report 测试
# =============================================================================

class TestTruthSyncReport(unittest.TestCase):
    """真相同步报告测试。"""

    def setUp(self):
        """创建测试项目。"""
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = _create_test_project(Path(self.tmp_dir))

    def tearDown(self):
        """清理测试项目。"""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_generate_report_basic(self):
        """测试基本报告生成。"""
        report = generate_report(self.project_root, 1)
        self.assertEqual(report["chapter"], 1)
        self.assertIn("world_state", report["files_checked"])
        self.assertIn("character_matrix", report["files_checked"])
        self.assertIn("summary", report)

    def test_generate_report_with_data(self):
        """测试有数据时的报告。"""
        # 添加一些数据
        truth_manager.upsert_character(self.project_root, "李华", role="主角")
        truth_manager.upsert_hook(self.project_root, 1, "伏笔1", id="hook-001")
        report = generate_report(self.project_root, 1)
        self.assertTrue(len(report["changes"]["character_matrix"]["items"]) > 0)
        self.assertTrue(len(report["changes"]["hook_ledger"]["items"]) > 0)

    def test_format_report(self):
        """测试报告格式化。"""
        report = generate_report(self.project_root, 1)
        text = format_report(report)
        self.assertIn("同步报告", text)
        self.assertIn("world_state", text)

    def test_format_report_json(self):
        """测试 JSON 格式报告。"""
        report = generate_report(self.project_root, 1)
        json_str = json.dumps(report, ensure_ascii=False, indent=2)
        self.assertIsInstance(json_str, str)
        # 验证可以解析回来
        parsed = json.loads(json_str)
        self.assertEqual(parsed["chapter"], 1)


# =============================================================================
# 集成测试
# =============================================================================

class TestIntegration(unittest.TestCase):
    """端到端集成测试。"""

    def setUp(self):
        """创建测试项目。"""
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = _create_test_project(Path(self.tmp_dir))

    def tearDown(self):
        """清理测试项目。"""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_full_workflow(self):
        """测试完整工作流：Observer → parse → Reflect → Report。"""
        # 1. 加载 prompt
        prompt = load_observer_input = assemble_observer_input(
            "李华遇到了老人，获得了一把剑。", "{}"
        )
        self.assertTrue(len(prompt) > 0)

        # 2. 模拟 LLM 输出
        delta = _make_valid_delta()

        # 3. 解析 delta
        parsed, errors = parse_observer_output(json.dumps(delta, ensure_ascii=False))
        self.assertIsNotNone(parsed)
        self.assertEqual(len(errors), 0)

        # 4. 执行 Reflector
        result = reflect(self.project_root, parsed, 1)
        self.assertTrue(len(result["updated"]) > 0)
        self.assertEqual(len(result["errors"]), 0)

        # 5. 验证真相文件已更新
        char_data, _ = truth_manager.load_truth(self.project_root, "character_matrix")
        self.assertTrue(len(char_data["characters"]) > 0)
        self.assertEqual(char_data["characters"][0]["name"], "老人")

        hook_data, _ = truth_manager.load_truth(self.project_root, "hook_ledger")
        self.assertTrue(len(hook_data["hooks"]) > 0)

        # 6. 生成报告
        report = generate_report(self.project_root, 1)
        self.assertEqual(report["chapter"], 1)
        self.assertTrue(len(report["changes"]["character_matrix"]["items"]) > 0)

    def test_auto_sync_end_to_end(self):
        """测试 auto_sync 端到端流程。"""
        delta = _make_valid_delta()
        result = auto_sync(self.project_root, 1, delta=delta)
        self.assertTrue(len(result["errors"]) == 0)
        self.assertIsNotNone(result["reflect_result"])

        # 验证 markdown 投影生成
        md_path = Path(self.project_root) / "00_memory" / "character_matrix.md"
        self.assertTrue(md_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
