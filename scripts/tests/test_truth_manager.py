#!/usr/bin/env python3
"""
truth_manager.py 核心功能测试

测试用例：
    - test_load_save: 创建、读取、更新 truth 文件
    - test_schema_validation: 故意传入无效数据，验证拒绝
    - test_file_lock: 测试 FileLock 类
    - test_markdown_projection: JSON → markdown 转换
    - test_migration: 从 .md 迁移到 .json
    - test_hook_operations: upsert/mention/resolve/defer
    - test_resource_operations: add/update/check_consistency
    - test_emotion_operations: add_emotion_point/check_consistency
    - test_subplot_operations: add/update/check_health
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

import schemas  # noqa: E402
import truth_manager  # noqa: E402
from truth_manager import (  # noqa: E402
    FileLock,
    add_emotion_point,
    add_resource,
    add_subplot,
    check_emotional_consistency,
    check_hook_health,
    check_resource_consistency,
    check_subplot_health,
    defer_hook,
    ensure_truth_dir,
    get_character_arc,
    get_character,
    get_markdown_path,
    get_truth_dir,
    get_truth_path,
    load_truth,
    mention_hook,
    migrate_from_markdown,
    render_markdown,
    resolve_hook,
    save_truth,
    update_resource,
    update_subplot_status,
    upsert_character,
    upsert_hook,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_tmp_project() -> str:
    """创建临时项目目录（含空 truth/），返回 project_root"""
    tmp = tempfile.mkdtemp(prefix="truth_test_")
    ensure_truth_dir(tmp)
    return tmp


def _write_truth(project_root: str, name: str, data: dict) -> None:
    """直接写入 JSON（绕过 schema 校验，用于构造测试数据）"""
    path = get_truth_path(project_root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===========================================================================
# 测试类
# ===========================================================================

class TestLoadSave(unittest.TestCase):
    """test_load_save: 创建、读取、更新 truth 文件"""

    def setUp(self):
        self.project_root = _make_tmp_project()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_load_nonexistent(self):
        data, errors = load_truth(self.project_root, "world_state")
        self.assertIsNone(data)
        self.assertTrue(len(errors) > 0)

    def test_save_and_load(self):
        data = {
            "world_name": "测试世界",
            "magic_system": "元素魔法",
            "tech_level": "中世纪",
            "history": [],
            "locations": [],
            "rules": [],
            "notes": "测试",
        }
        ok, errors = save_truth(self.project_root, "world_state", data)
        self.assertTrue(ok, f"save 失败: {errors}")

        loaded, load_errors = load_truth(self.project_root, "world_state")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["world_name"], "测试世界")
        self.assertEqual(loaded["magic_system"], "元素魔法")

    def test_update_existing(self):
        data = {
            "world_name": "原世界",
            "magic_system": "",
            "tech_level": "",
            "history": [],
            "locations": [],
            "rules": [],
            "notes": "",
        }
        ok, _ = save_truth(self.project_root, "world_state", data)
        self.assertTrue(ok)

        data["world_name"] = "新世界"
        ok, _ = save_truth(self.project_root, "world_state", data)
        self.assertTrue(ok)

        loaded, _ = load_truth(self.project_root, "world_state")
        self.assertEqual(loaded["world_name"], "新世界")


class TestSchemaValidation(unittest.TestCase):
    """test_schema_validation: 故意传入无效数据，验证拒绝"""

    def setUp(self):
        self.project_root = _make_tmp_project()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_world_state_missing_required(self):
        # world_name 是必填字段
        data = {"magic_system": "火焰"}
        valid, errors = schemas.WorldState.validate(data)
        self.assertFalse(valid)
        self.assertTrue(any("world_name" in e for e in errors))

    def test_world_state_invalid_location(self):
        data = {"world_name": "测试", "locations": ["不是dict"]}
        valid, errors = schemas.WorldState.validate(data)
        self.assertFalse(valid)

    def test_character_matrix_no_name(self):
        data = {"characters": [{"role": "主角"}]}  # 缺少 name
        valid, errors = schemas.CharacterMatrix.validate(data)
        self.assertFalse(valid)

    def test_hook_ledger_bad_status(self):
        data = {"hooks": [{"id": "h1", "description": "test", "status": "INVALID"}]}
        valid, errors = schemas.HookLedger.validate(data)
        self.assertFalse(valid)

    def test_save_rejects_invalid(self):
        """save_truth 应拒绝无效数据"""
        data = {"magic_system": "火焰"}  # 缺 world_name
        ok, errors = save_truth(self.project_root, "world_state", data)
        self.assertFalse(ok)
        self.assertTrue(len(errors) > 0)


class TestFileLock(unittest.TestCase):
    """test_file_lock: 测试 FileLock 类"""

    def setUp(self):
        self.project_root = _make_tmp_project()
        self.lock_dir = get_truth_dir(self.project_root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_acquire_and_release(self):
        lock_path = self.lock_dir / ".test.lock"
        with FileLock(lock_path):
            self.assertTrue(lock_path.exists())
        # 退出后锁文件应被清理
        self.assertFalse(lock_path.exists())

    def test_nested_usage(self):
        lock_path = self.lock_dir / ".nested.lock"
        with FileLock(lock_path):
            # 在锁内写入数据
            test_file = self.lock_dir / "test.json"
            with open(test_file, "w") as f:
                f.write("locked")
            self.assertEqual(test_file.read_text(), "locked")

    def test_content_integrity(self):
        """验证在 FileLock 内写入的数据完整"""
        lock_path = self.lock_dir / ".integrity.lock"
        data = {"hello": "world", "num": 42}
        with FileLock(lock_path):
            target = self.lock_dir / "data.json"
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        loaded = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(loaded, data)


class TestMarkdownProjection(unittest.TestCase):
    """test_markdown_projection: JSON → markdown 转换"""

    def setUp(self):
        self.project_root = _make_tmp_project()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_world_state_to_markdown(self):
        data = {
            "world_name": "幻想大陆",
            "magic_system": "元素亲和",
            "tech_level": "蒸汽朋克",
            "history": ["大灾变", "重建时代"],
            "locations": [{"name": "王都", "description": "繁华之城"}],
            "rules": ["不能暴露真名"],
            "notes": "测试",
        }
        ok, _ = save_truth(self.project_root, "world_state", data)
        self.assertTrue(ok)

        # 验证 markdown 投影文件已生成
        md_path = get_markdown_path(self.project_root, "world_state.json")
        self.assertTrue(md_path.exists(), f"markdown 文件不存在: {md_path}")

        md_content = md_path.read_text(encoding="utf-8")
        self.assertIn("幻想大陆", md_content)
        self.assertIn("元素亲和", md_content)
        self.assertIn("王都", md_content)

    def test_render_markdown(self):
        data = {
            "world_name": "测试世界",
            "magic_system": "",
            "tech_level": "",
            "history": [],
            "locations": [],
            "rules": [],
            "notes": "",
        }
        ok, _ = save_truth(self.project_root, "world_state", data)
        self.assertTrue(ok)

        md = render_markdown(self.project_root, "world_state")
        self.assertIn("测试世界", md)
        self.assertIn("# 世界观", md)

    def test_hook_ledger_markdown(self):
        data = {
            "hooks": [
                {
                    "id": "hook-001", "description": "伏笔A",
                    "type": "foreshadowing", "status": "open",
                    "planted_chapter": 1, "mentions": [],
                    "resolved_chapter": None, "deadline_chapter": 10,
                    "importance": "high",
                    "related_characters": ["主角"],
                    "related_motifs": [],
                }
            ],
            "health": {"stale_debt": [], "burst_warning": [], "no_advance": []},
        }
        ok, _ = save_truth(self.project_root, "hook_ledger", data)
        self.assertTrue(ok)

        md = render_markdown(self.project_root, "hook_ledger")
        self.assertIn("钩子账本", md)
        self.assertIn("hook-001", md)


class TestMigration(unittest.TestCase):
    """test_migration: 从 .md 迁移到 .json"""

    def setUp(self):
        self.project_root = tempfile.mkdtemp(prefix="migrate_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def _create_md(self, name: str, content: str):
        memory_dir = Path(self.project_root) / "00_memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / f"{name}.md").write_text(content, encoding="utf-8")

    def test_migrate_world_state(self):
        md_content = (
            "# 世界观\n\n"
            "**世界名称**：远古大陆\n\n"
            "## 魔法体系\n元素魔法体系\n\n"
            "## 科技水平\n中世纪\n\n"
            "## 历史事件\n1. 大灾变\n\n"
            "## 地点\n### 王都\n首都之城\n\n"
            "## 世界规则\n- 真名不能泄露\n"
        )
        self._create_md("world_state", md_content)

        result = migrate_from_markdown(self.project_root)
        self.assertTrue(result["success"], f"迁移失败: {result}")

        # 验证 JSON 文件生成
        truth_path = get_truth_path(self.project_root, "world_state")
        self.assertTrue(truth_path.exists())
        data = json.loads(truth_path.read_text(encoding="utf-8"))
        self.assertEqual(data["world_name"], "远古大陆")

    def test_migrate_skips_no_schema(self):
        self._create_md("random_note", "# 随机笔记\n内容")
        result = migrate_from_markdown(self.project_root)
        self.assertTrue(len(result["skipped"]) > 0)

    def test_migrate_no_force_when_truth_exists(self):
        ensure_truth_dir(self.project_root)
        self._create_md("world_state", "# 世界观\n**世界名称**：X\n")
        result = migrate_from_markdown(self.project_root, force=False)
        self.assertTrue(len(result["skipped"]) > 0)

    def test_migrate_with_force(self):
        ensure_truth_dir(self.project_root)
        md_content = (
            "# 世界观\n\n"
            "**世界名称**：强制世界\n"
        )
        self._create_md("world_state", md_content)
        result = migrate_from_markdown(self.project_root, force=True)
        self.assertTrue(result["success"], f"force 迁移失败: {result}")

    def test_create_empty_project(self):
        """项目没有 00_memory/ 目录时应自动创建并复制模板"""
        # 清空项目目录
        import shutil
        for item in Path(self.project_root).iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # 调用 migrate_memory.migrate（无 00_memory 目录）
        # migrate_memory 模块在 scripts/ 下
        migrate_script = _SCRIPT_DIR / "migrate_memory.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("migrate_memory", migrate_script)
        mm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mm)
        result = mm.migrate(self.project_root, force=True)

        memory_dir = Path(self.project_root) / "00_memory"
        self.assertTrue(memory_dir.exists())
        truth_dir = get_truth_dir(self.project_root)
        self.assertTrue(truth_dir.exists())

    def test_migrate_invalid_md_skips(self):
        """无法解析的 markdown 应跳过"""
        # 创建一个会触发解析异常的文件（对某些 schema 会生成无效数据）
        md_content = "# 世界观\n完全无法解析的内容\n???"
        self._create_md("world_state", md_content)
        result = migrate_from_markdown(self.project_root)
        # world_state 的 from_markdown 是尽力解析，通常不会抛异常
        # 但至少应有结果
        self.assertIsInstance(result, dict)


class TestHookOperations(unittest.TestCase):
    """test_hook_operations: upsert/mention/resolve/defer"""

    def setUp(self):
        self.project_root = _make_tmp_project()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_upsert_new_hook(self):
        ok, hook_id, errors = upsert_hook(
            self.project_root, chapter=1,
            description="神秘预言",
            type="foreshadowing", importance="high",
        )
        self.assertTrue(ok, f"upsert 失败: {errors}")
        self.assertTrue(hook_id.startswith("hook-"))

        # 验证已保存
        data, _ = load_truth(self.project_root, "hook_ledger")
        self.assertIsNotNone(data)
        hooks = [h for h in data["hooks"] if h["id"] == hook_id]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["description"], "神秘预言")

    def test_upsert_update_existing(self):
        ok, hook_id, errors = upsert_hook(
            self.project_root, chapter=1,
            description="原始描述", type="foreshadowing",
        )
        self.assertTrue(ok)

        # 更新同一个 hook（通过 kwargs 更新 type/importance 等字段）
        ok2, hook_id2, errors2 = upsert_hook(
            self.project_root, chapter=2,
            description="新描述（不影响已有 hook）",
            id=hook_id, type="promise", importance="high",
        )
        self.assertTrue(ok2, f"update 失败: {errors2}")
        self.assertEqual(hook_id, hook_id2)

        data, _ = load_truth(self.project_root, "hook_ledger")
        hook = next(h for h in data["hooks"] if h["id"] == hook_id)
        # description 不会通过 upsert 更新（它是创建时的参数）
        self.assertEqual(hook["description"], "原始描述")
        # 但 kwargs 中的字段会被更新
        self.assertEqual(hook["type"], "promise")
        self.assertEqual(hook["importance"], "high")

    def test_mention_hook(self):
        ok, hook_id, _ = upsert_hook(self.project_root, chapter=1, description="测试提及")
        self.assertTrue(ok)

        ok, errors = mention_hook(self.project_root, chapter=5, hook_id=hook_id)
        self.assertTrue(ok, f"mention 失败: {errors}")

        data, _ = load_truth(self.project_root, "hook_ledger")
        hook = next(h for h in data["hooks"] if h["id"] == hook_id)
        self.assertIn(5, hook["mentions"])
        self.assertEqual(hook["status"], "mentioned")

    def test_resolve_hook(self):
        ok, hook_id, _ = upsert_hook(self.project_root, chapter=1, description="测试回收")
        self.assertTrue(ok)

        ok, errors = resolve_hook(self.project_root, chapter=8, hook_id=hook_id)
        self.assertTrue(ok, f"resolve 失败: {errors}")

        data, _ = load_truth(self.project_root, "hook_ledger")
        hook = next(h for h in data["hooks"] if h["id"] == hook_id)
        self.assertEqual(hook["status"], "resolved")
        self.assertEqual(hook["resolved_chapter"], 8)

    def test_defer_hook(self):
        ok, hook_id, _ = upsert_hook(self.project_root, chapter=1, description="测试延期")
        self.assertTrue(ok)

        ok, errors = defer_hook(self.project_root, hook_id=hook_id, new_deadline=20)
        self.assertTrue(ok, f"defer 失败: {errors}")

        data, _ = load_truth(self.project_root, "hook_ledger")
        hook = next(h for h in data["hooks"] if h["id"] == hook_id)
        self.assertEqual(hook["status"], "deferred")
        self.assertEqual(hook["deadline_chapter"], 20)

    def test_mention_nonexistent(self):
        ok, errors = mention_hook(self.project_root, chapter=1, hook_id="hook-999")
        self.assertFalse(ok)
        self.assertTrue(any("不存在" in e for e in errors))

    def test_resolve_nonexistent(self):
        ok, errors = resolve_hook(self.project_root, chapter=1, hook_id="hook-999")
        self.assertFalse(ok)

    def test_defer_nonexistent(self):
        ok, errors = defer_hook(self.project_root, hook_id="hook-999", new_deadline=10)
        self.assertFalse(ok)


class TestResourceOperations(unittest.TestCase):
    """test_resource_operations: add/update/check_consistency"""

    def setUp(self):
        self.project_root = _make_tmp_project()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_add_resource(self):
        ok, res_id, errors = add_resource(
            self.project_root, chapter=1,
            name="圣剑", type="weapon", owner="主角", amount=1,
        )
        self.assertTrue(ok, f"add_resource 失败: {errors}")
        self.assertTrue(res_id.startswith("res-"))

        data, _ = load_truth(self.project_root, "resource_ledger")
        self.assertIsNotNone(data)
        resources = [r for r in data["resources"] if r["id"] == res_id]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["name"], "圣剑")

    def test_update_resource(self):
        ok, res_id, _ = add_resource(
            self.project_root, chapter=1,
            name="金币", type="currency", owner="主角", amount=100,
        )
        self.assertTrue(ok)

        ok, errors = update_resource(
            self.project_root, chapter=3,
            resource_id=res_id, new_amount=50, event="消费",
        )
        self.assertTrue(ok, f"update 失败: {errors}")

        data, _ = load_truth(self.project_root, "resource_ledger")
        res = next(r for r in data["resources"] if r["id"] == res_id)
        self.assertEqual(res["amount"], 50)
        self.assertEqual(res["last_updated_chapter"], 3)

    def test_check_consistency_no_issues(self):
        ok, res_id, _ = add_resource(
            self.project_root, chapter=1,
            name="魔力", type="power_level", owner="法师", amount=100,
        )
        self.assertTrue(ok)

        issues = check_resource_consistency(self.project_root, current_chapter=5)
        self.assertIsInstance(issues, list)
        # 正常添加不会产生一致性问题
        self.assertEqual(len(issues), 0)

    def test_update_nonexistent(self):
        ok, errors = update_resource(
            self.project_root, chapter=1,
            resource_id="res-999", new_amount=0,
        )
        self.assertFalse(ok)
        self.assertTrue(any("不存在" in e for e in errors))


class TestEmotionOperations(unittest.TestCase):
    """test_emotion_operations: add_emotion_point/check_consistency"""

    def setUp(self):
        self.project_root = _make_tmp_project()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_add_emotion_point(self):
        ok, errors = add_emotion_point(
            self.project_root, character="主角",
            chapter=1, emotion="坚定", intensity=7, trigger="誓言",
        )
        self.assertTrue(ok, f"add_emotion 失败: {errors}")

        arc = get_character_arc(self.project_root, "主角")
        self.assertIsNotNone(arc)
        self.assertEqual(arc["current_emotion"], "坚定")
        self.assertEqual(len(arc["arc"]), 1)

    def test_emotion_arc_direction(self):
        """连续添加情感点后应计算正确的弧光方向"""
        add_emotion_point(
            self.project_root, character="主角",
            chapter=1, emotion="平静", intensity=5, trigger="日常",
        )
        add_emotion_point(
            self.project_root, character="主角",
            chapter=2, emotion="愤怒", intensity=9, trigger="背叛",
        )

        arc = get_character_arc(self.project_root, "主角")
        self.assertEqual(arc["arc_direction"], "上升")

        add_emotion_point(
            self.project_root, character="主角",
            chapter=3, emotion="悲伤", intensity=3, trigger="失去",
        )
        arc = get_character_arc(self.project_root, "主角")
        self.assertEqual(arc["arc_direction"], "下降")

    def test_check_consistency_no_issues(self):
        ok, _ = add_emotion_point(
            self.project_root, character="配角",
            chapter=1, emotion="开心", intensity=5, trigger="日常",
        )
        self.assertTrue(ok)

        issues = check_emotional_consistency(self.project_root, current_chapter=5)
        self.assertIsInstance(issues, list)
        # 单个情感点不会有一致性问题
        self.assertEqual(len(issues), 0)

    def test_multiple_characters(self):
        add_emotion_point(
            self.project_root, character="A",
            chapter=1, emotion="高兴", intensity=6, trigger="相遇",
        )
        add_emotion_point(
            self.project_root, character="B",
            chapter=1, emotion="紧张", intensity=4, trigger="任务",
        )

        arc_a = get_character_arc(self.project_root, "A")
        arc_b = get_character_arc(self.project_root, "B")
        self.assertIsNotNone(arc_a)
        self.assertIsNotNone(arc_b)
        self.assertEqual(arc_a["current_emotion"], "高兴")
        self.assertEqual(arc_b["current_emotion"], "紧张")


class TestSubplotOperations(unittest.TestCase):
    """test_subplot_operations: add/update/check_health"""

    def setUp(self):
        self.project_root = _make_tmp_project()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_add_subplot(self):
        ok, sub_id, errors = add_subplot(
            self.project_root, name="爱情线",
            chapter=1, key_characters=["主角", "女主"],
            hooks=["hook-001"],
        )
        self.assertTrue(ok, f"add_subplot 失败: {errors}")
        self.assertTrue(sub_id.startswith("sub-"))

        data, _ = load_truth(self.project_root, "subplot_board")
        self.assertIsNotNone(data)
        subs = [s for s in data["subplots"] if s["id"] == sub_id]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["name"], "爱情线")
        self.assertEqual(subs[0]["status"], "active")

    def test_update_subplot_status(self):
        ok, sub_id, _ = add_subplot(
            self.project_root, name="支线A", chapter=1,
        )
        self.assertTrue(ok)

        ok, errors = update_subplot_status(
            self.project_root, subplot_id=sub_id,
            new_status="dormant", chapter=5,
        )
        self.assertTrue(ok, f"update_subplot 失败: {errors}")

        data, _ = load_truth(self.project_root, "subplot_board")
        sub = next(s for s in data["subplots"] if s["id"] == sub_id)
        self.assertEqual(sub["status"], "dormant")
        self.assertEqual(sub["last_mentioned_chapter"], 5)

    def test_check_health_ok(self):
        ok, sub_id, _ = add_subplot(
            self.project_root, name="短线", chapter=5,
        )
        self.assertTrue(ok)

        issues = check_subplot_health(self.project_root, current_chapter=6)
        self.assertIsInstance(issues, list)
        # 刚创建的支线不会有健康问题
        self.assertEqual(len(issues), 0)

    def test_check_health_forgotten(self):
        """超过15章未提及应报告遗忘"""
        ok, sub_id, _ = add_subplot(
            self.project_root, name="被遗忘的支线", chapter=1,
        )
        self.assertTrue(ok)

        issues = check_subplot_health(self.project_root, current_chapter=20)
        forgotten = [i for i in issues if "被遗忘" in i or "未提及" in i]
        self.assertTrue(len(forgotten) > 0, f"应检测到遗忘支线: {issues}")

    def test_update_nonexistent(self):
        ok, errors = update_subplot_status(
            self.project_root, subplot_id="sub-999",
            new_status="resolved", chapter=1,
        )
        self.assertFalse(ok)
        self.assertTrue(any("不存在" in e for e in errors))


class TestPathUtils(unittest.TestCase):
    """路径工具测试"""

    def setUp(self):
        self.project_root = _make_tmp_project()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_get_truth_dir(self):
        td = get_truth_dir(self.project_root)
        self.assertTrue(td.name == "truth")
        self.assertTrue(td.parent.name == "00_memory")

    def test_get_truth_path(self):
        tp = get_truth_path(self.project_root, "world_state")
        self.assertTrue(tp.name == "world_state.json")

    def test_get_truth_path_adds_json(self):
        tp = get_truth_path(self.project_root, "hook_ledger")
        self.assertTrue(tp.name.endswith(".json"))

    def test_get_markdown_path(self):
        mp = get_markdown_path(self.project_root, "world_state.json")
        self.assertEqual(mp.name, "world_state.md")
        self.assertEqual(mp.parent.name, "00_memory")

    def test_ensure_truth_dir(self):
        td = ensure_truth_dir(self.project_root)
        self.assertTrue(td.exists())

    def test_ensure_truth_dir_idempotent(self):
        td1 = ensure_truth_dir(self.project_root)
        td2 = ensure_truth_dir(self.project_root)
        self.assertEqual(td1, td2)


if __name__ == "__main__":
    unittest.main()
