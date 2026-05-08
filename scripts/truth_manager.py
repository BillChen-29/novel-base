"""
真相文件管理器

所有真相文件的 CRUD 操作，包含：
- load_truth(project_root, file_name) → dict
- save_truth(project_root, file_name, data) → (bool, List[str])
- render_markdown(project_root, file_name) → str
- migrate_from_markdown(project_root) → dict

路径：~/.hermes/skills/novel-creator-skill/scripts/truth_manager.py
"""

from __future__ import annotations
import json
import os
import time
import shutil
import fcntl
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import schemas


# =============================================================================
# 路径工具
# =============================================================================

def get_truth_dir(project_root: str) -> Path:
    """获取真相文件目录"""
    return Path(project_root) / "00_memory" / "truth"


def get_truth_path(project_root: str, file_name: str) -> Path:
    """获取真相文件路径"""
    if not file_name.endswith(".json"):
        file_name = file_name + ".json"
    return get_truth_dir(project_root) / file_name


def get_markdown_path(project_root: str, file_name: str) -> Path:
    """获取 markdown 投影路径"""
    if file_name.endswith(".json"):
        file_name = file_name[:-5]
    return Path(project_root) / "00_memory" / f"{file_name}.md"


def ensure_truth_dir(project_root: str) -> Path:
    """确保真相文件目录存在"""
    truth_dir = get_truth_dir(project_root)
    truth_dir.mkdir(parents=True, exist_ok=True)
    return truth_dir


# =============================================================================
# 文件锁
# =============================================================================

class FileLock:
    """文件锁，防止并发写入"""

    def __init__(self, lock_path: Path, max_retries: int = 3, retry_delay: float = 0.5):
        self.lock_path = lock_path
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._fd = None

    def __enter__(self):
        for attempt in range(self.max_retries):
            try:
                self._fd = open(self.lock_path, "w")
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (IOError, OSError):
                if self._fd:
                    self._fd.close()
                    self._fd = None
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise IOError(f"无法获取文件锁: {self.lock_path}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fd:
            try:
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                self._fd.close()
            except (IOError, OSError):
                pass
            self._fd = None
        # 清理锁文件
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass


# =============================================================================
# CRUD 操作
# =============================================================================

def load_truth(project_root: str, file_name: str) -> Tuple[Optional[dict], List[str]]:
    """
    读取真相文件

    Returns:
        (data, errors): data 为 None 表示读取失败
    """
    errors = []
    truth_path = get_truth_path(project_root, file_name)

    if not truth_path.exists():
        return (None, [f"真相文件不存在: {truth_path}"])

    try:
        with open(truth_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data, [])
    except json.JSONDecodeError as e:
        return (None, [f"JSON 解析失败: {e}"])
    except OSError as e:
        return (None, [f"读取失败: {e}"])


def save_truth(project_root: str, file_name: str, data: dict) -> Tuple[bool, List[str]]:
    """
    保存真相文件（带 schema 校验和文件锁）

    Returns:
        (success, errors)
    """
    errors = []

    # 获取 schema 名称
    schema_name = file_name.replace(".json", "")
    schema_cls = schemas.get_schema(schema_name)
    if not schema_cls:
        return (False, [f"未知 schema: {schema_name}"])

    # 校验 schema
    valid, validation_errors = schema_cls.validate(data)
    if not valid:
        return (False, validation_errors)

    # 确保目录存在
    truth_dir = ensure_truth_dir(project_root)
    truth_path = get_truth_path(project_root, file_name)
    lock_path = truth_dir / f".{file_name}.lock"

    # 写入（带文件锁）
    try:
        with FileLock(lock_path):
            # 写入 JSON
            with open(truth_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 生成 markdown 投影
            md_content = schema_cls.to_markdown(data)
            md_path = get_markdown_path(project_root, file_name)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)

        return (True, [])
    except (IOError, OSError) as e:
        return (False, [f"写入失败: {e}"])


def render_markdown(project_root: str, file_name: str) -> str:
    """
    将真相文件渲染为 markdown

    Returns:
        markdown 内容，失败时返回错误信息
    """
    data, errors = load_truth(project_root, file_name)
    if errors:
        return f"# 错误\n\n{chr(10).join(errors)}"

    schema_name = file_name.replace(".json", "")
    return schemas.to_markdown(schema_name, data)


# =============================================================================
# Hook 操作（A2 扩展）
# =============================================================================

def _load_hook_ledger(project_root: str) -> dict:
    """加载钩子账本，不存在则返回空结构"""
    data, errors = load_truth(project_root, "hook_ledger")
    if errors:
        return {"hooks": [], "health": {"stale_debt": [], "burst_warning": [], "no_advance": []}}
    return data


def upsert_hook(project_root: str, chapter: int, description: str, **kwargs) -> Tuple[bool, str, List[str]]:
    """
    新增或更新钩子

    Returns:
        (success, hook_id, errors)
    """
    data = _load_hook_ledger(project_root)

    # 生成 ID
    existing_ids = {h.get("id", "") for h in data["hooks"]}
    hook_id = kwargs.get("id", "")
    if not hook_id:
        hook_num = len(data["hooks"]) + 1
        hook_id = f"hook-{hook_num:03d}"
        while hook_id in existing_ids:
            hook_num += 1
            hook_id = f"hook-{hook_num:03d}"

    # 查找已有钩子
    existing = next((h for h in data["hooks"] if h["id"] == hook_id), None)

    if existing:
        # 更新
        existing.update({k: v for k, v in kwargs.items() if v is not None})
        if chapter and chapter not in existing.get("mentions", []):
            existing.setdefault("mentions", []).append(chapter)
    else:
        # 新增
        hook = {
            "id": hook_id,
            "description": description,
            "type": kwargs.get("type", "foreshadowing"),
            "status": kwargs.get("status", "open"),
            "planted_chapter": chapter,
            "mentions": [],
            "resolved_chapter": None,
            "deadline_chapter": kwargs.get("deadline_chapter", 0),
            "importance": kwargs.get("importance", "medium"),
            "related_characters": kwargs.get("related_characters", []),
            "related_motifs": kwargs.get("related_motifs", []),
        }
        data["hooks"].append(hook)

    success, errors = save_truth(project_root, "hook_ledger", data)
    return (success, hook_id, errors)


def mention_hook(project_root: str, chapter: int, hook_id: str) -> Tuple[bool, List[str]]:
    """提及钩子"""
    data = _load_hook_ledger(project_root)
    hook = next((h for h in data["hooks"] if h["id"] == hook_id), None)
    if not hook:
        return (False, [f"钩子不存在: {hook_id}"])

    if chapter not in hook.get("mentions", []):
        hook.setdefault("mentions", []).append(chapter)
    if hook.get("status") == "open":
        hook["status"] = "mentioned"

    return save_truth(project_root, "hook_ledger", data)


def resolve_hook(project_root: str, chapter: int, hook_id: str) -> Tuple[bool, List[str]]:
    """回收钩子"""
    data = _load_hook_ledger(project_root)
    hook = next((h for h in data["hooks"] if h["id"] == hook_id), None)
    if not hook:
        return (False, [f"钩子不存在: {hook_id}"])

    hook["status"] = "resolved"
    hook["resolved_chapter"] = chapter

    return save_truth(project_root, "hook_ledger", data)


def defer_hook(project_root: str, hook_id: str, new_deadline: int) -> Tuple[bool, List[str]]:
    """延期钩子"""
    data = _load_hook_ledger(project_root)
    hook = next((h for h in data["hooks"] if h["id"] == hook_id), None)
    if not hook:
        return (False, [f"钩子不存在: {hook_id}"])

    hook["status"] = "deferred"
    hook["deadline_chapter"] = new_deadline

    return save_truth(project_root, "hook_ledger", data)


def get_open_hooks(project_root: str) -> List[dict]:
    """获取所有待回收钩子"""
    data = _load_hook_ledger(project_root)
    return [h for h in data["hooks"] if h.get("status") in ("open", "mentioned")]


def check_hook_health(project_root: str, current_chapter: int) -> dict:
    """检查钩子健康状态"""
    data = _load_hook_ledger(project_root)
    health = {"stale_debt": [], "burst_warning": [], "no_advance": []}

    for hook in data["hooks"]:
        if hook.get("status") not in ("open", "mentioned"):
            continue

        hook_id = hook.get("id", "")

        # 检测超期未回收
        deadline = hook.get("deadline_chapter", 0)
        if deadline > 0 and current_chapter > deadline:
            health["stale_debt"].append(f"{hook_id}: {hook.get('description', '')}")

        # 检测长期未提及
        mentions = hook.get("mentions", [])
        last_mention = max(mentions) if mentions else hook.get("planted_chapter", 0)
        if current_chapter - last_mention > 10:
            health["no_advance"].append(f"{hook_id}: {hook.get('description', '')}")

    # 检测同章回收过多
    resolved_this_chapter = [
        h for h in data["hooks"]
        if h.get("status") == "resolved" and h.get("resolved_chapter") == current_chapter
    ]
    if len(resolved_this_chapter) > 3:
        health["burst_warning"] = [f"第{current_chapter}章回收了{len(resolved_this_chapter)}个钩子"]

    # 更新健康状态
    data["health"] = health
    save_truth(project_root, "hook_ledger", data)

    return health


# =============================================================================
# 资源操作（A3 扩展）
# =============================================================================

def _load_resource_ledger(project_root: str) -> dict:
    """加载资源账本，不存在则返回空结构"""
    data, errors = load_truth(project_root, "resource_ledger")
    if errors:
        return {"resources": [], "power_levels": []}
    return data


def add_resource(project_root: str, chapter: int, name: str, type: str, owner: str, amount: Any) -> Tuple[bool, str, List[str]]:
    """新增资源"""
    data = _load_resource_ledger(project_root)

    # 生成 ID
    existing_ids = {r.get("id", "") for r in data["resources"]}
    res_num = len(data["resources"]) + 1
    res_id = f"res-{res_num:03d}"
    while res_id in existing_ids:
        res_num += 1
        res_id = f"res-{res_num:03d}"

    resource = {
        "id": res_id,
        "name": name,
        "type": type,
        "owner": owner,
        "amount": amount,
        "last_updated_chapter": chapter,
        "history": [{"chapter": chapter, "amount": amount, "event": "初始"}],
    }
    data["resources"].append(resource)

    success, errors = save_truth(project_root, "resource_ledger", data)
    return (success, res_id, errors)


def update_resource(project_root: str, chapter: int, resource_id: str, new_amount: Any, event: str = "") -> Tuple[bool, List[str]]:
    """更新资源数量"""
    data = _load_resource_ledger(project_root)
    res = next((r for r in data["resources"] if r["id"] == resource_id), None)
    if not res:
        return (False, [f"资源不存在: {resource_id}"])

    res["amount"] = new_amount
    res["last_updated_chapter"] = chapter
    res.setdefault("history", []).append({
        "chapter": chapter,
        "amount": new_amount,
        "event": event or "更新",
    })

    return save_truth(project_root, "resource_ledger", data)


def get_resources_by_owner(project_root: str, owner: str) -> List[dict]:
    """获取某角色的所有资源"""
    data = _load_resource_ledger(project_root)
    return [r for r in data["resources"] if r.get("owner") == owner]


def check_resource_consistency(project_root: str, current_chapter: int) -> List[str]:
    """检查资源一致性"""
    data = _load_resource_ledger(project_root)
    issues = []

    for res in data["resources"]:
        history = res.get("history", [])
        if len(history) < 2:
            continue

        # 检测突变（金额变化>10倍且无事件记录）
        for i in range(1, len(history)):
            prev = history[i - 1]
            curr = history[i]
            prev_amount = prev.get("amount", 0)
            curr_amount = curr.get("amount", 0)
            if isinstance(prev_amount, (int, float)) and isinstance(curr_amount, (int, float)):
                if prev_amount > 0 and curr_amount > 0:
                    ratio = max(curr_amount / prev_amount, prev_amount / curr_amount)
                    if ratio > 10 and not curr.get("event"):
                        issues.append(f"资源 {res.get('name', '')} 在第{curr.get('chapter', '')}章突变 {prev_amount}→{curr_amount}（无事件记录）")

    return issues


# =============================================================================
# 情感操作（A4 扩展）
# =============================================================================

def _load_emotional_arcs(project_root: str) -> dict:
    """加载情感弧光，不存在则返回空结构"""
    data, errors = load_truth(project_root, "emotional_arcs")
    if errors:
        return {"characters": {}}
    return data


def add_emotion_point(project_root: str, character: str, chapter: int, emotion: str, intensity: int, trigger: str) -> Tuple[bool, List[str]]:
    """新增情感点"""
    data = _load_emotional_arcs(project_root)

    if character not in data["characters"]:
        data["characters"][character] = {"arc": [], "current_emotion": "", "arc_direction": "平稳"}

    char_arc = data["characters"][character]
    char_arc["arc"].append({
        "chapter": chapter,
        "emotion": emotion,
        "intensity": intensity,
        "trigger": trigger,
    })
    char_arc["current_emotion"] = emotion

    # 计算方向
    arc = char_arc["arc"]
    if len(arc) >= 2:
        recent_intensity = arc[-1]["intensity"]
        prev_intensity = arc[-2]["intensity"]
        if recent_intensity > prev_intensity:
            char_arc["arc_direction"] = "上升"
        elif recent_intensity < prev_intensity:
            char_arc["arc_direction"] = "下降"
        else:
            char_arc["arc_direction"] = "平稳"

    return save_truth(project_root, "emotional_arcs", data)


def get_character_arc(project_root: str, character: str) -> Optional[dict]:
    """获取角色情感弧光"""
    data = _load_emotional_arcs(project_root)
    return data["characters"].get(character)


def check_emotional_consistency(project_root: str, current_chapter: int) -> List[str]:
    """检查情感一致性"""
    data = _load_emotional_arcs(project_root)
    issues = []

    for name, char_data in data.get("characters", {}).items():
        arc = char_data.get("arc", [])
        if len(arc) < 2:
            continue

        # 检测情感突变（intensity 变化>5 且无 trigger）
        for i in range(1, len(arc)):
            prev = arc[i - 1]
            curr = arc[i]
            intensity_diff = abs(curr.get("intensity", 5) - prev.get("intensity", 5))
            if intensity_diff > 5 and not curr.get("trigger"):
                issues.append(f"角色 {name} 在第{curr.get('chapter', '')}章情感突变（强度变化{intensity_diff}，无触发）")

        # 检测情感停滞（>10章 emotion 不变）
        last_emotion = arc[-1].get("emotion", "")
        last_chapter = arc[-1].get("chapter", 0)
        all_same = all(p.get("emotion") == last_emotion for p in arc[-3:]) if len(arc) >= 3 else False
        if all_same and current_chapter - last_chapter > 10:
            issues.append(f"角色 {name} 情感停滞（'{last_emotion}' 持续>10章）")

    return issues


# =============================================================================
# 支线操作（A5 扩展）
# =============================================================================

def _load_subplot_board(project_root: str) -> dict:
    """加载支线管理，不存在则返回空结构"""
    data, errors = load_truth(project_root, "subplot_board")
    if errors:
        return {"subplots": []}
    return data


def add_subplot(project_root: str, name: str, chapter: int, key_characters: List[str] = None, hooks: List[str] = None) -> Tuple[bool, str, List[str]]:
    """新增支线"""
    data = _load_subplot_board(project_root)

    # 生成 ID
    existing_ids = {s.get("id", "") for s in data["subplots"]}
    sub_num = len(data["subplots"]) + 1
    sub_id = f"sub-{sub_num:03d}"
    while sub_id in existing_ids:
        sub_num += 1
        sub_id = f"sub-{sub_num:03d}"

    subplot = {
        "id": sub_id,
        "name": name,
        "status": "active",
        "started_chapter": chapter,
        "last_mentioned_chapter": chapter,
        "key_characters": key_characters or [],
        "hooks": hooks or [],
        "tension_level": "medium",
        "notes": "",
    }
    data["subplots"].append(subplot)

    success, errors = save_truth(project_root, "subplot_board", data)
    return (success, sub_id, errors)


def update_subplot_status(project_root: str, subplot_id: str, new_status: str, chapter: int) -> Tuple[bool, List[str]]:
    """更新支线状态"""
    data = _load_subplot_board(project_root)
    sub = next((s for s in data["subplots"] if s["id"] == subplot_id), None)
    if not sub:
        return (False, [f"支线不存在: {subplot_id}"])

    sub["status"] = new_status
    sub["last_mentioned_chapter"] = chapter

    return save_truth(project_root, "subplot_board", data)


def get_active_subplots(project_root: str) -> List[dict]:
    """获取所有活跃支线"""
    data = _load_subplot_board(project_root)
    return [s for s in data["subplots"] if s.get("status") == "active"]


def check_subplot_health(project_root: str, current_chapter: int) -> List[str]:
    """检查支线健康状态"""
    data = _load_subplot_board(project_root)
    issues = []

    active_subplots = [s for s in data["subplots"] if s.get("status") == "active"]

    # 检测遗忘支线（>15章未提及）
    for sub in active_subplots:
        last_mentioned = sub.get("last_mentioned_chapter", 0)
        if current_chapter - last_mentioned > 15:
            issues.append(f"支线 '{sub.get('name', '')}' 被遗忘（>15章未提及，最后第{last_mentioned}章）")

    # 检测支线过多（>5条）
    if len(active_subplots) > 5:
        issues.append(f"活跃支线过多（{len(active_subplots)}条），建议合并或休眠")

    # 检测支线冲突（共享角色但发展方向矛盾）
    for i, sub1 in enumerate(active_subplots):
        chars1 = set(sub1.get("key_characters", []))
        for sub2 in active_subplots[i + 1:]:
            chars2 = set(sub2.get("key_characters", []))
            shared = chars1 & chars2
            if shared and sub1.get("tension_level") == "high" and sub2.get("tension_level") == "high":
                issues.append(f"支线 '{sub1.get('name', '')}' 和 '{sub2.get('name', '')}' 共享角色 {shared} 且均为高张力")

    return issues


# =============================================================================
# 章节摘要操作
# =============================================================================

def _load_chapter_summaries(project_root: str) -> dict:
    """加载章节摘要，不存在则返回空结构"""
    data, errors = load_truth(project_root, "chapter_summaries")
    if errors:
        return {"chapters": []}
    return data


def add_chapter_summary(project_root: str, chapter: int, title: str, summary: str,
                        key_events: List[str] = None, characters_involved: List[str] = None,
                        word_count: int = 0) -> Tuple[bool, List[str]]:
    """新增章节摘要"""
    data = _load_chapter_summaries(project_root)

    # 检查是否已存在
    existing = next((c for c in data["chapters"] if c.get("chapter") == chapter), None)
    if existing:
        existing.update({
            "title": title,
            "summary": summary,
            "key_events": key_events or [],
            "characters_involved": characters_involved or [],
            "word_count": word_count,
        })
    else:
        data["chapters"].append({
            "chapter": chapter,
            "title": title,
            "summary": summary,
            "key_events": key_events or [],
            "characters_involved": characters_involved or [],
            "foreshadowing": [],
            "word_count": word_count,
        })

    # 按章节排序
    data["chapters"].sort(key=lambda c: c.get("chapter", 0))

    return save_truth(project_root, "chapter_summaries", data)


def get_chapter_summaries_as_text(project_root: str) -> List[str]:
    """获取所有章节摘要（纯文本列表）"""
    data = _load_chapter_summaries(project_root)
    return [c.get("summary", "") for c in data.get("chapters", []) if c.get("summary")]


# =============================================================================
# 角色矩阵操作
# =============================================================================

def _load_character_matrix(project_root: str) -> dict:
    """加载角色矩阵，不存在则返回空结构"""
    data, errors = load_truth(project_root, "character_matrix")
    if errors:
        return {"characters": []}
    return data


def upsert_character(project_root: str, name: str, **kwargs) -> Tuple[bool, List[str]]:
    """新增或更新角色"""
    data = _load_character_matrix(project_root)

    existing = next((c for c in data["characters"] if c.get("name") == name), None)
    if existing:
        existing.update({k: v for k, v in kwargs.items() if v is not None})
    else:
        char = {
            "name": name,
            "role": kwargs.get("role", ""),
            "personality": kwargs.get("personality", ""),
            "motivation": kwargs.get("motivation", ""),
            "abilities": kwargs.get("abilities", []),
            "relationships": kwargs.get("relationships", {}),
            "arc": kwargs.get("arc", ""),
            "status": kwargs.get("status", "alive"),
            "notes": kwargs.get("notes", ""),
        }
        data["characters"].append(char)

    return save_truth(project_root, "character_matrix", data)


def get_character(project_root: str, name: str) -> Optional[dict]:
    """获取角色信息"""
    data = _load_character_matrix(project_root)
    return next((c for c in data["characters"] if c.get("name") == name), None)


# =============================================================================
# 世界观操作
# =============================================================================

def _load_world_state(project_root: str) -> dict:
    """加载世界观，不存在则返回空结构"""
    data, errors = load_truth(project_root, "world_state")
    if errors:
        return {"world_name": "", "magic_system": "", "tech_level": "",
                "history": [], "locations": [], "rules": [], "notes": ""}
    return data


def update_world_state(project_root: str, **kwargs) -> Tuple[bool, List[str]]:
    """更新世界观"""
    data = _load_world_state(project_root)
    data.update({k: v for k, v in kwargs.items() if v is not None})
    return save_truth(project_root, "world_state", data)


def add_location(project_root: str, name: str, description: str) -> Tuple[bool, List[str]]:
    """新增地点"""
    data = _load_world_state(project_root)
    existing = next((l for l in data["locations"] if l.get("name") == name), None)
    if existing:
        existing["description"] = description
    else:
        data["locations"].append({"name": name, "description": description})
    return save_truth(project_root, "world_state", data)


# =============================================================================
# 迁移
# =============================================================================

def migrate_from_markdown(project_root: str, force: bool = False) -> Dict[str, Any]:
    """
    从 markdown 迁移到 JSON

    Returns:
        {"success": List[str], "skipped": List[str], "errors": List[str]}
    """
    result = {"success": [], "skipped": [], "errors": []}
    memory_dir = Path(project_root) / "00_memory"
    truth_dir = get_truth_dir(project_root)

    # 检查目录
    if not memory_dir.exists():
        result["errors"].append(f"00_memory 目录不存在: {memory_dir}")
        return result

    if truth_dir.exists() and not force:
        result["skipped"].append(f"truth 目录已存在，使用 --force 覆盖")
        return result

    # 确保 truth 目录存在
    ensure_truth_dir(project_root)

    # 遍历 markdown 文件
    md_files = list(memory_dir.glob("*.md"))
    if not md_files:
        result["skipped"].append("没有找到 markdown 文件")
        return result

    for md_file in md_files:
        file_name = md_file.stem
        schema_name = file_name.replace("-", "_").lower()

        # 查找匹配的 schema
        schema_cls = schemas.get_schema(schema_name)
        if not schema_cls:
            result["skipped"].append(f"跳过 {md_file.name}（无匹配 schema）")
            continue

        # 读取 markdown
        try:
            md_content = md_file.read_text(encoding="utf-8")
        except OSError as e:
            result["errors"].append(f"读取 {md_file.name} 失败: {e}")
            continue

        # 解析为 dict
        try:
            data = schema_cls.from_markdown(md_content)
        except Exception as e:
            result["errors"].append(f"解析 {md_file.name} 失败: {e}")
            continue

        # 校验
        valid, validation_errors = schema_cls.validate(data)
        if not valid:
            result["errors"].append(f"校验 {md_file.name} 失败: {validation_errors}")
            continue

        # 保存 JSON
        json_path = truth_dir / f"{schema_name}.json"
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            result["success"].append(f"{md_file.name} → {schema_name}.json")
        except OSError as e:
            result["errors"].append(f"写入 {schema_name}.json 失败: {e}")

    return result


# =============================================================================
# 初始化空模板
# =============================================================================

def init_empty_truth(project_root: str) -> Dict[str, Any]:
    """初始化空真相文件（从模板复制）"""
    result = {"success": [], "errors": []}
    truth_dir = ensure_truth_dir(project_root)

    template_dir = Path(__file__).parent.parent / "templates" / "truth"
    if not template_dir.exists():
        result["errors"].append(f"模板目录不存在: {template_dir}")
        return result

    for template_file in template_dir.glob("*.json"):
        target = truth_dir / template_file.name
        if not target.exists():
            try:
                shutil.copy2(template_file, target)
                result["success"].append(template_file.name)
            except OSError as e:
                result["errors"].append(f"复制 {template_file.name} 失败: {e}")

    return result
