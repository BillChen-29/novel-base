"""
真相文件 Schema 定义

7个真相文件的 Python dataclass 定义，包含：
- 字段定义（类型、必填、默认值）
- validate(data) → (bool, List[str])
- to_markdown(data) → str
- from_markdown(md_text) → dict

路径：~/.hermes/skills/novel-creator-skill/scripts/schemas.py
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# 基础工具
# =============================================================================

def _validate_required(data: dict, required_fields: List[str]) -> List[str]:
    """检查必填字段"""
    errors = []
    for f in required_fields:
        if f not in data or data[f] is None:
            errors.append(f"缺少必填字段: {f}")
    return errors


def _validate_type(value: Any, expected_type: str, field_name: str) -> List[str]:
    """检查字段类型"""
    errors = []
    if value is None:
        return errors
    type_map = {
        "str": str,
        "int": int,
        "float": (int, float),
        "bool": bool,
        "list": list,
        "dict": dict,
    }
    if expected_type in type_map:
        if not isinstance(value, type_map[expected_type]):
            errors.append(f"字段 {field_name} 类型错误: 期望 {expected_type}，实际 {type(value).__name__}")
    return errors


def _safe_json_loads(text: str) -> Optional[dict]:
    """安全解析 JSON"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# =============================================================================
# WorldState（世界观）
# =============================================================================

@dataclass
class WorldState:
    """世界观：地图、地点、科技水平、魔法体系、历史"""
    world_name: str = ""
    magic_system: str = ""
    tech_level: str = ""
    history: List[str] = field(default_factory=list)
    locations: List[Dict[str, Any]] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    notes: str = ""

    @staticmethod
    def validate(data: dict) -> Tuple[bool, List[str]]:
        errors = _validate_required(data, ["world_name"])
        for loc in data.get("locations", []):
            if not isinstance(loc, dict):
                errors.append("locations 元素必须是 dict")
            elif "name" not in loc:
                errors.append("locations 元素缺少 name 字段")
        return (len(errors) == 0, errors)

    @staticmethod
    def to_markdown(data: dict) -> str:
        lines = ["# 世界观\n"]
        if data.get("world_name"):
            lines.append(f"**世界名称**：{data['world_name']}\n")
        if data.get("magic_system"):
            lines.append(f"## 魔法体系\n{data['magic_system']}\n")
        if data.get("tech_level"):
            lines.append(f"## 科技水平\n{data['tech_level']}\n")
        if data.get("history"):
            lines.append("## 历史事件\n")
            for i, h in enumerate(data["history"], 1):
                lines.append(f"{i}. {h}")
            lines.append("")
        if data.get("locations"):
            lines.append("## 地点\n")
            for loc in data["locations"]:
                name = loc.get("name", "未知")
                desc = loc.get("description", "")
                lines.append(f"### {name}\n{desc}\n")
        if data.get("rules"):
            lines.append("## 世界规则\n")
            for r in data["rules"]:
                lines.append(f"- {r}")
            lines.append("")
        if data.get("notes"):
            lines.append(f"## 备注\n{data['notes']}\n")
        return "\n".join(lines)

    @staticmethod
    def from_markdown(md_text: str) -> dict:
        """从 markdown 解析为 dict（尽力解析，不保证完美）"""
        data = {"world_name": "", "magic_system": "", "tech_level": "",
                "history": [], "locations": [], "rules": [], "notes": ""}
        lines = md_text.split("\n")
        current_section = None
        current_loc = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("**世界名称**"):
                data["world_name"] = stripped.split("：", 1)[-1].strip()
            elif stripped.startswith("## 魔法体系"):
                current_section = "magic"
            elif stripped.startswith("## 科技水平"):
                current_section = "tech"
            elif stripped.startswith("## 历史事件"):
                current_section = "history"
            elif stripped.startswith("## 地点"):
                current_section = "locations"
            elif stripped.startswith("## 世界规则"):
                current_section = "rules"
            elif stripped.startswith("### ") and current_section == "locations":
                if current_loc:
                    data["locations"].append(current_loc)
                current_loc = {"name": stripped[4:], "description": ""}
            elif stripped.startswith("## "):
                current_section = "notes"
            elif stripped:
                if current_section == "magic":
                    data["magic_system"] += stripped + "\n"
                elif current_section == "tech":
                    data["tech_level"] += stripped + "\n"
                elif current_section == "history":
                    data["history"].append(stripped.lstrip("0123456789. "))
                elif current_section == "locations" and current_loc:
                    current_loc["description"] += stripped + "\n"
                elif current_section == "rules":
                    data["rules"].append(stripped.lstrip("- "))
                elif current_section == "notes":
                    data["notes"] += stripped + "\n"
        if current_loc:
            data["locations"].append(current_loc)
        data["magic_system"] = data["magic_system"].strip()
        data["tech_level"] = data["tech_level"].strip()
        data["notes"] = data["notes"].strip()
        return data


# =============================================================================
# CharacterMatrix（角色矩阵）
# =============================================================================

@dataclass
class Character:
    """单个角色"""
    name: str = ""
    role: str = ""  # 主角/配角/反派/导师/路人
    personality: str = ""
    motivation: str = ""
    abilities: List[str] = field(default_factory=list)
    relationships: Dict[str, str] = field(default_factory=dict)  # 角色名 → 关系描述
    arc: str = ""  # 角色弧光描述
    status: str = "alive"  # alive/dead/missing/unknown
    notes: str = ""


@dataclass
class CharacterMatrix:
    """角色矩阵"""
    characters: List[Character] = field(default_factory=list)

    @staticmethod
    def validate(data: dict) -> Tuple[bool, List[str]]:
        errors = []
        for i, c in enumerate(data.get("characters", [])):
            if not isinstance(c, dict):
                errors.append(f"characters[{i}] 必须是 dict")
            elif not c.get("name"):
                errors.append(f"characters[{i}] 缺少 name")
        return (len(errors) == 0, errors)

    @staticmethod
    def to_markdown(data: dict) -> str:
        lines = ["# 角色矩阵\n"]
        for c in data.get("characters", []):
            name = c.get("name", "未知")
            role = c.get("role", "")
            lines.append(f"## {name} ({role})\n")
            if c.get("personality"):
                lines.append(f"**性格**：{c['personality']}\n")
            if c.get("motivation"):
                lines.append(f"**动机**：{c['motivation']}\n")
            if c.get("abilities"):
                lines.append(f"**能力**：{', '.join(c['abilities'])}\n")
            if c.get("relationships"):
                lines.append("**关系**：\n")
                for other, rel in c["relationships"].items():
                    lines.append(f"- {other}：{rel}")
                lines.append("")
            if c.get("arc"):
                lines.append(f"**弧光**：{c['arc']}\n")
            if c.get("notes"):
                lines.append(f"**备注**：{c['notes']}\n")
        return "\n".join(lines)

    @staticmethod
    def from_markdown(md_text: str) -> dict:
        data = {"characters": []}
        current_char = None
        current_field = None
        for line in md_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## ") and "(" in stripped:
                if current_char:
                    data["characters"].append(current_char)
                parts = stripped[3:].split("(")
                name = parts[0].strip()
                role = parts[1].rstrip(")") if len(parts) > 1 else ""
                current_char = {"name": name, "role": role, "personality": "",
                                "motivation": "", "abilities": [], "relationships": {},
                                "arc": "", "status": "alive", "notes": ""}
                current_field = None
            elif current_char and stripped.startswith("**"):
                field_name = stripped.split("**")[1].rstrip("：:")
                field_map = {"性格": "personality", "动机": "motivation", "弧光": "arc", "备注": "notes"}
                current_field = field_map.get(field_name)
                if current_field and "：" in stripped:
                    current_char[current_field] = stripped.split("：", 1)[-1].strip()
            elif current_char and stripped.startswith("- ") and current_field == "relationships":
                parts = stripped[2:].split("：", 1)
                if len(parts) == 2:
                    current_char["relationships"][parts[0].strip()] = parts[1].strip()
            elif current_char and stripped.startswith("- ") and current_field == "abilities":
                current_char["abilities"].append(stripped[2:].strip())
            elif current_char and stripped and current_field:
                current_char[current_field] += stripped
        if current_char:
            data["characters"].append(current_char)
        return data


# =============================================================================
# EmotionalArcs（情感弧光）
# =============================================================================

@dataclass
class EmotionPoint:
    """情感点"""
    chapter: int = 0
    emotion: str = ""
    intensity: int = 5  # 1-10
    trigger: str = ""


@dataclass
class CharacterArc:
    """角色情感弧光"""
    arc: List[EmotionPoint] = field(default_factory=list)
    current_emotion: str = ""
    arc_direction: str = "平稳"  # 上升/平稳/下降


@dataclass
class EmotionalArcs:
    """情感弧光"""
    characters: Dict[str, CharacterArc] = field(default_factory=dict)

    @staticmethod
    def validate(data: dict) -> Tuple[bool, List[str]]:
        errors = []
        for name, arc_data in data.get("characters", {}).items():
            if not isinstance(arc_data, dict):
                errors.append(f"角色 {name} 数据必须是 dict")
            elif "arc" in arc_data and not isinstance(arc_data["arc"], list):
                errors.append(f"角色 {name} 的 arc 必须是 list")
        return (len(errors) == 0, errors)

    @staticmethod
    def to_markdown(data: dict) -> str:
        lines = ["# 情感弧光\n"]
        for name, arc_data in data.get("characters", {}).items():
            lines.append(f"## {name}\n")
            direction = arc_data.get("arc_direction", "平稳")
            current = arc_data.get("current_emotion", "未知")
            lines.append(f"**当前情感**：{current} | **方向**：{direction}\n")
            lines.append("| 章节 | 情感 | 强度 | 触发 |")
            lines.append("|------|------|------|------|")
            for p in arc_data.get("arc", []):
                lines.append(f"| {p.get('chapter', '')} | {p.get('emotion', '')} | {p.get('intensity', '')} | {p.get('trigger', '')} |")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def from_markdown(md_text: str) -> dict:
        data = {"characters": {}}
        current_char = None
        for line in md_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                current_char = stripped[3:].strip()
                data["characters"][current_char] = {"arc": [], "current_emotion": "", "arc_direction": "平稳"}
            elif current_char and stripped.startswith("**当前情感**"):
                parts = stripped.split("：", 1)
                if len(parts) > 1:
                    emotion_parts = parts[1].split("|")
                    data["characters"][current_char]["current_emotion"] = emotion_parts[0].strip()
                    if len(emotion_parts) > 1:
                        data["characters"][current_char]["arc_direction"] = emotion_parts[1].replace("**方向**", "").strip().strip("：")
            elif current_char and stripped.startswith("|") and not stripped.startswith("| 章节") and not stripped.startswith("|---"):
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                if len(cells) >= 3:
                    try:
                        data["characters"][current_char]["arc"].append({
                            "chapter": int(cells[0]) if cells[0].isdigit() else 0,
                            "emotion": cells[1],
                            "intensity": int(cells[2]) if cells[2].isdigit() else 5,
                            "trigger": cells[3] if len(cells) > 3 else ""
                        })
                    except (ValueError, IndexError):
                        pass
        return data


# =============================================================================
# ResourceLedger（资源账本）
# =============================================================================

@dataclass
class Resource:
    """资源"""
    id: str = ""
    name: str = ""
    type: str = ""  # currency/item/power_level/skill
    owner: str = ""
    amount: Any = None
    last_updated_chapter: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PowerLevel:
    """力量等级"""
    character: str = ""
    level: str = ""
    updated_chapter: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ResourceLedger:
    """资源账本"""
    resources: List[Resource] = field(default_factory=list)
    power_levels: List[PowerLevel] = field(default_factory=list)

    @staticmethod
    def validate(data: dict) -> Tuple[bool, List[str]]:
        errors = []
        for i, r in enumerate(data.get("resources", [])):
            if not isinstance(r, dict):
                errors.append(f"resources[{i}] 必须是 dict")
            elif not r.get("name"):
                errors.append(f"resources[{i}] 缺少 name")
        for i, p in enumerate(data.get("power_levels", [])):
            if not isinstance(p, dict):
                errors.append(f"power_levels[{i}] 必须是 dict")
            elif not p.get("character"):
                errors.append(f"power_levels[{i}] 缺少 character")
        return (len(errors) == 0, errors)

    @staticmethod
    def to_markdown(data: dict) -> str:
        lines = ["# 资源账本\n"]
        if data.get("resources"):
            lines.append("## 物品/资源\n")
            lines.append("| ID | 名称 | 类型 | 持有者 | 数量 | 最后更新 |")
            lines.append("|-----|------|------|--------|------|----------|")
            for r in data["resources"]:
                lines.append(f"| {r.get('id', '')} | {r.get('name', '')} | {r.get('type', '')} | {r.get('owner', '')} | {r.get('amount', '')} | 第{r.get('last_updated_chapter', '')}章 |")
            lines.append("")
        if data.get("power_levels"):
            lines.append("## 力量等级\n")
            lines.append("| 角色 | 等级 | 最后更新 |")
            lines.append("|------|------|----------|")
            for p in data["power_levels"]:
                lines.append(f"| {p.get('character', '')} | {p.get('level', '')} | 第{p.get('updated_chapter', '')}章 |")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def from_markdown(md_text: str) -> dict:
        data = {"resources": [], "power_levels": []}
        current_section = None
        for line in md_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## 物品") or stripped.startswith("## 资源"):
                current_section = "resources"
            elif stripped.startswith("## 力量"):
                current_section = "power_levels"
            elif stripped.startswith("|") and not stripped.startswith("|---") and not stripped.startswith("| ID") and not stripped.startswith("| 角色"):
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                if current_section == "resources" and len(cells) >= 5:
                    data["resources"].append({
                        "id": cells[0], "name": cells[1], "type": cells[2],
                        "owner": cells[3], "amount": cells[4],
                        "last_updated_chapter": int(cells[5].replace("第", "").replace("章", "")) if len(cells) > 5 and cells[5].replace("第", "").replace("章", "").isdigit() else 0,
                        "history": []
                    })
                elif current_section == "power_levels" and len(cells) >= 2:
                    data["power_levels"].append({
                        "character": cells[0], "level": cells[1],
                        "updated_chapter": int(cells[2].replace("第", "").replace("章", "")) if len(cells) > 2 and cells[2].replace("第", "").replace("章", "").isdigit() else 0,
                        "history": []
                    })
        return data


# =============================================================================
# SubplotBoard（支线管理）
# =============================================================================

@dataclass
class Subplot:
    """支线"""
    id: str = ""
    name: str = ""
    status: str = "active"  # active/dormant/resolved
    started_chapter: int = 0
    last_mentioned_chapter: int = 0
    key_characters: List[str] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)  # 关联的 hook_id
    tension_level: str = "medium"  # low/medium/high
    notes: str = ""


@dataclass
class SubplotBoard:
    """支线管理"""
    subplots: List[Subplot] = field(default_factory=list)

    @staticmethod
    def validate(data: dict) -> Tuple[bool, List[str]]:
        errors = []
        for i, s in enumerate(data.get("subplots", [])):
            if not isinstance(s, dict):
                errors.append(f"subplots[{i}] 必须是 dict")
            elif not s.get("name"):
                errors.append(f"subplots[{i}] 缺少 name")
            elif s.get("status") not in ("active", "dormant", "resolved", None, ""):
                errors.append(f"subplots[{i}] status 无效: {s.get('status')}")
        return (len(errors) == 0, errors)

    @staticmethod
    def to_markdown(data: dict) -> str:
        lines = ["# 支线管理\n"]
        lines.append("| ID | 名称 | 状态 | 张力 | 开始章 | 最后提及 | 关键角色 |")
        lines.append("|-----|------|------|------|--------|----------|----------|")
        for s in data.get("subplots", []):
            chars = ", ".join(s.get("key_characters", []))
            lines.append(f"| {s.get('id', '')} | {s.get('name', '')} | {s.get('status', '')} | {s.get('tension_level', '')} | {s.get('started_chapter', '')} | {s.get('last_mentioned_chapter', '')} | {chars} |")
        lines.append("")
        for s in data.get("subplots", []):
            if s.get("notes"):
                lines.append(f"**{s.get('name', '')}**：{s['notes']}\n")
        return "\n".join(lines)

    @staticmethod
    def from_markdown(md_text: str) -> dict:
        data = {"subplots": []}
        for line in md_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("|") and not stripped.startswith("|---") and not stripped.startswith("| ID"):
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                if len(cells) >= 6:
                    data["subplots"].append({
                        "id": cells[0], "name": cells[1], "status": cells[2],
                        "tension_level": cells[3],
                        "started_chapter": int(cells[4]) if cells[4].isdigit() else 0,
                        "last_mentioned_chapter": int(cells[5]) if cells[5].isdigit() else 0,
                        "key_characters": [c.strip() for c in cells[6].split(",")] if len(cells) > 6 else [],
                        "hooks": [], "notes": ""
                    })
        return data


# =============================================================================
# HookLedger（钩子账本）
# =============================================================================

@dataclass
class Hook:
    """钩子"""
    id: str = ""
    description: str = ""
    type: str = "foreshadowing"  # foreshadowing/promise/mystery/conflict
    status: str = "open"  # open/mentioned/resolved/deferred
    planted_chapter: int = 0
    mentions: List[int] = field(default_factory=list)
    resolved_chapter: Optional[int] = None
    deadline_chapter: int = 0
    importance: str = "medium"  # high/medium/low
    related_characters: List[str] = field(default_factory=list)
    related_motifs: List[str] = field(default_factory=list)


@dataclass
class HookHealth:
    """钩子健康状态"""
    stale_debt: List[str] = field(default_factory=list)      # 超期未回收
    burst_warning: List[str] = field(default_factory=list)   # 同章回收过多
    no_advance: List[str] = field(default_factory=list)      # 长期未提及


@dataclass
class HookLedger:
    """钩子账本"""
    hooks: List[Hook] = field(default_factory=list)
    health: HookHealth = field(default_factory=HookHealth)

    @staticmethod
    def validate(data: dict) -> Tuple[bool, List[str]]:
        errors = []
        for i, h in enumerate(data.get("hooks", [])):
            if not isinstance(h, dict):
                errors.append(f"hooks[{i}] 必须是 dict")
            elif not h.get("id"):
                errors.append(f"hooks[{i}] 缺少 id")
            elif not h.get("description"):
                errors.append(f"hooks[{i}] 缺少 description")
            elif h.get("status") not in ("open", "mentioned", "resolved", "deferred", None, ""):
                errors.append(f"hooks[{i}] status 无效: {h.get('status')}")
        return (len(errors) == 0, errors)

    @staticmethod
    def to_markdown(data: dict) -> str:
        lines = ["# 钩子账本\n"]
        open_hooks = [h for h in data.get("hooks", []) if h.get("status") == "open"]
        mentioned_hooks = [h for h in data.get("hooks", []) if h.get("status") == "mentioned"]
        resolved_hooks = [h for h in data.get("hooks", []) if h.get("status") == "resolved"]
        deferred_hooks = [h for h in data.get("hooks", []) if h.get("status") == "deferred"]
        if open_hooks:
            lines.append("## 待回收\n")
            lines.append("| ID | 描述 | 类型 | 重要性 | 埋下章 | 截止章 | 角色 |")
            lines.append("|-----|------|------|--------|--------|--------|------|")
            for h in open_hooks:
                chars = ", ".join(h.get("related_characters", []))
                lines.append(f"| {h.get('id', '')} | {h.get('description', '')} | {h.get('type', '')} | {h.get('importance', '')} | {h.get('planted_chapter', '')} | {h.get('deadline_chapter', '')} | {chars} |")
            lines.append("")
        if mentioned_hooks:
            lines.append("## 已提及（待回收）\n")
            for h in mentioned_hooks:
                mentions = ", ".join(str(m) for m in h.get("mentions", []))
                lines.append(f"- **{h.get('id', '')}**：{h.get('description', '')}（提及于第 {mentions} 章）")
            lines.append("")
        if resolved_hooks:
            lines.append("## 已回收\n")
            for h in resolved_hooks:
                lines.append(f"- **{h.get('id', '')}**：{h.get('description', '')}（回收于第 {h.get('resolved_chapter', '')} 章）")
            lines.append("")
        if deferred_hooks:
            lines.append("## 已延期\n")
            for h in deferred_hooks:
                lines.append(f"- **{h.get('id', '')}**：{h.get('description', '')}（延期至第 {h.get('deadline_chapter', '')} 章）")
            lines.append("")
        health = data.get("health", {})
        if any(health.get(k) for k in ("stale_debt", "burst_warning", "no_advance")):
            lines.append("## 健康状态\n")
            if health.get("stale_debt"):
                lines.append(f"**超期未回收**：{', '.join(health['stale_debt'])}\n")
            if health.get("burst_warning"):
                lines.append(f"**同章回收过多**：{', '.join(health['burst_warning'])}\n")
            if health.get("no_advance"):
                lines.append(f"**长期未提及**：{', '.join(health['no_advance'])}\n")
        return "\n".join(lines)

    @staticmethod
    def from_markdown(md_text: str) -> dict:
        data = {"hooks": [], "health": {"stale_debt": [], "burst_warning": [], "no_advance": []}}
        current_section = None
        for line in md_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## 待回收"):
                current_section = "open"
            elif stripped.startswith("## 已提及"):
                current_section = "mentioned"
            elif stripped.startswith("## 已回收"):
                current_section = "resolved"
            elif stripped.startswith("## 已延期"):
                current_section = "deferred"
            elif stripped.startswith("## 健康"):
                current_section = "health"
            elif stripped.startswith("**超期"):
                data["health"]["stale_debt"] = [s.strip() for s in stripped.split("：", 1)[-1].split(",")]
            elif stripped.startswith("**同章"):
                data["health"]["burst_warning"] = [s.strip() for s in stripped.split("：", 1)[-1].split(",")]
            elif stripped.startswith("**长期"):
                data["health"]["no_advance"] = [s.strip() for s in stripped.split("：", 1)[-1].split(",")]
            elif stripped.startswith("|") and not stripped.startswith("|---") and not stripped.startswith("| ID") and current_section == "open":
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                if len(cells) >= 6:
                    data["hooks"].append({
                        "id": cells[0], "description": cells[1], "type": cells[2],
                        "status": "open", "importance": cells[3],
                        "planted_chapter": int(cells[4]) if cells[4].isdigit() else 0,
                        "deadline_chapter": int(cells[5]) if cells[5].isdigit() else 0,
                        "related_characters": [c.strip() for c in cells[6].split(",")] if len(cells) > 6 else [],
                        "mentions": [], "resolved_chapter": None, "related_motifs": []
                    })
            elif stripped.startswith("- **") and current_section in ("mentioned", "resolved", "deferred"):
                parts = stripped.split("**：", 1)
                if len(parts) >= 2:
                    hook_id = parts[0].lstrip("- ").strip("**")
                    desc = parts[1].split("（")[0].strip()
                    status = current_section
                    hook = {"id": hook_id, "description": desc, "status": status,
                            "type": "", "planted_chapter": 0, "mentions": [],
                            "resolved_chapter": None, "deadline_chapter": 0,
                            "importance": "", "related_characters": [], "related_motifs": []}
                    if "提及于第" in parts[1]:
                        nums = re.findall(r"\d+", parts[1])
                        hook["mentions"] = [int(n) for n in nums]
                    elif "回收于第" in parts[1]:
                        nums = re.findall(r"\d+", parts[1])
                        hook["resolved_chapter"] = int(nums[0]) if nums else None
                    elif "延期至第" in parts[1]:
                        nums = re.findall(r"\d+", parts[1])
                        hook["deadline_chapter"] = int(nums[0]) if nums else 0
                    data["hooks"].append(hook)
        return data


# =============================================================================
# ChapterSummaries（章节摘要）
# =============================================================================

@dataclass
class ChapterSummary:
    """单章摘要"""
    chapter: int = 0
    title: str = ""
    summary: str = ""
    key_events: List[str] = field(default_factory=list)
    characters_involved: List[str] = field(default_factory=list)
    foreshadowing: List[str] = field(default_factory=list)
    word_count: int = 0


@dataclass
class ChapterSummaries:
    """章节摘要"""
    chapters: List[ChapterSummary] = field(default_factory=list)

    @staticmethod
    def validate(data: dict) -> Tuple[bool, List[str]]:
        errors = []
        for i, c in enumerate(data.get("chapters", [])):
            if not isinstance(c, dict):
                errors.append(f"chapters[{i}] 必须是 dict")
            elif not c.get("chapter"):
                errors.append(f"chapters[{i}] 缺少 chapter 编号")
        return (len(errors) == 0, errors)

    @staticmethod
    def to_markdown(data: dict) -> str:
        lines = ["# 章节摘要\n"]
        for c in data.get("chapters", []):
            ch_num = c.get("chapter", "?")
            title = c.get("title", "")
            lines.append(f"## 第{ch_num}章 {title}\n")
            if c.get("summary"):
                lines.append(f"{c['summary']}\n")
            if c.get("key_events"):
                lines.append("**关键事件**：" + "；".join(c["key_events"]) + "\n")
            if c.get("characters_involved"):
                lines.append("**涉及角色**：" + "、".join(c["characters_involved"]) + "\n")
            if c.get("word_count"):
                lines.append(f"**字数**：{c['word_count']}\n")
        return "\n".join(lines)

    @staticmethod
    def from_markdown(md_text: str) -> dict:
        data = {"chapters": []}
        current_ch = None
        for line in md_text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## 第") and "章" in stripped:
                if current_ch:
                    data["chapters"].append(current_ch)
                nums = re.findall(r"\d+", stripped)
                title = stripped.split("章", 1)[-1].strip() if "章" in stripped else ""
                current_ch = {"chapter": int(nums[0]) if nums else 0, "title": title,
                              "summary": "", "key_events": [], "characters_involved": [],
                              "foreshadowing": [], "word_count": 0}
            elif current_ch and stripped.startswith("**关键事件**"):
                events = stripped.split("：", 1)[-1].split("；")
                current_ch["key_events"] = [e.strip() for e in events if e.strip()]
            elif current_ch and stripped.startswith("**涉及角色**"):
                chars = stripped.split("：", 1)[-1].split("、")
                current_ch["characters_involved"] = [c.strip() for c in chars if c.strip()]
            elif current_ch and stripped.startswith("**字数**"):
                nums = re.findall(r"\d+", stripped)
                current_ch["word_count"] = int(nums[0]) if nums else 0
            elif current_ch and stripped and not stripped.startswith("#"):
                current_ch["summary"] += stripped + "\n"
        if current_ch:
            data["chapters"].append(current_ch)
        for c in data["chapters"]:
            c["summary"] = c["summary"].strip()
        return data


# =============================================================================
# Schema 注册表
# =============================================================================

SCHEMA_REGISTRY = {
    "world_state": WorldState,
    "character_matrix": CharacterMatrix,
    "emotional_arcs": EmotionalArcs,
    "resource_ledger": ResourceLedger,
    "subplot_board": SubplotBoard,
    "hook_ledger": HookLedger,
    "chapter_summaries": ChapterSummaries,
}


def get_schema(name: str):
    """获取 schema 类"""
    return SCHEMA_REGISTRY.get(name)


def validate_truth(name: str, data: dict) -> Tuple[bool, List[str]]:
    """验证真相文件数据"""
    schema = get_schema(name)
    if not schema:
        return (False, [f"未知 schema: {name}"])
    return schema.validate(data)


def to_markdown(name: str, data: dict) -> str:
    """将真相文件数据转为 markdown"""
    schema = get_schema(name)
    if not schema:
        return f"# 未知 schema: {name}\n"
    return schema.to_markdown(data)


def from_markdown(name: str, md_text: str) -> dict:
    """从 markdown 解析真相文件数据"""
    schema = get_schema(name)
    if not schema:
        return {}
    return schema.from_markdown(md_text)
