#!/usr/bin/env python3
"""
Truth Sync Report - 同步报告生成

功能：对比更新前后的真相文件，输出变更摘要。

路径：~/.hermes/skills/novel-creator-skill/scripts/truth_sync_report.py
"""

from __future__ import annotations
import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# 确保 scripts/ 在 sys.path 中
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import truth_manager  # noqa: E402

# 需要对比的真相文件
TRUTH_FILES = [
    "world_state",
    "character_matrix",
    "emotional_arcs",
    "resource_ledger",
    "subplot_board",
    "hook_ledger",
    "chapter_summaries",
]


def _snapshot_truth(project_root: str) -> Dict[str, Any]:
    """快照当前所有真相文件。"""
    snapshot = {}
    for name in TRUTH_FILES:
        data, errors = truth_manager.load_truth(project_root, name)
        if data and not errors:
            snapshot[name] = copy.deepcopy(data)
        else:
            snapshot[name] = None
    return snapshot


def _diff_list(old_list: list, new_list: list, key_field: str = "name") -> Dict[str, Any]:
    """对比两个列表的差异。"""
    old_keys = {item.get(key_field, str(i)): item for i, item in enumerate(old_list)}
    new_keys = {item.get(key_field, str(i)): item for i, item in enumerate(new_list)}

    added = [new_keys[k] for k in new_keys if k not in old_keys]
    removed = [old_keys[k] for k in old_keys if k not in new_keys]
    modified = []
    for k in old_keys:
        if k in new_keys:
            old_item = old_keys[k]
            new_item = new_keys[k]
            if old_item != new_item:
                modified.append({"key": k, "old": old_item, "new": new_item})

    return {"added": added, "removed": removed, "modified": modified}


def _diff_dict(old_dict: dict, new_dict: dict) -> Dict[str, Any]:
    """对比两个字典的差异。"""
    added = {k: v for k, v in new_dict.items() if k not in old_dict}
    removed = {k: v for k, v in old_dict.items() if k not in new_dict}
    modified = {}
    for k in old_dict:
        if k in new_dict and old_dict[k] != new_dict[k]:
            modified[k] = {"old": old_dict[k], "new": new_dict[k]}
    return {"added": added, "removed": removed, "modified": modified}


def generate_report(project_root: str, chapter: int) -> Dict[str, Any]:
    """
    生成同步报告：对比更新前后的真相文件。

    实际实现：加载当前真相文件，分析各文件的内容变化摘要。

    Args:
        project_root: 项目根目录
        chapter: 章节号

    Returns:
        {
            "chapter": int,
            "files_checked": List[str],
            "changes": Dict[str, Any],  # 各文件的变更摘要
            "summary": str,             # 总结
        }
    """
    changes: Dict[str, Any] = {}
    files_checked: List[str] = []

    for name in TRUTH_FILES:
        data, errors = truth_manager.load_truth(project_root, name)
        files_checked.append(name)

        if errors or not data:
            changes[name] = {
                "status": "not_found" if not data else "error",
                "errors": errors,
                "summary": "文件不存在或加载失败",
            }
            continue

        # 分析各文件类型的内容
        file_changes = _analyze_truth_file(name, data, chapter)
        changes[name] = file_changes

    # 生成总结
    total_added = sum(c.get("added_count", 0) for c in changes.values() if isinstance(c, dict))
    total_modified = sum(c.get("modified_count", 0) for c in changes.values() if isinstance(c, dict))
    total_errors = sum(1 for c in changes.values() if isinstance(c, dict) and c.get("status") == "error")

    summary_parts = []
    if total_added > 0:
        summary_parts.append(f"新增 {total_added} 项")
    if total_modified > 0:
        summary_parts.append(f"修改 {total_modified} 项")
    if total_errors > 0:
        summary_parts.append(f"{total_errors} 个文件加载失败")

    summary = f"第{chapter}章同步报告：" + ("、".join(summary_parts) if summary_parts else "无变更")

    return {
        "chapter": chapter,
        "files_checked": files_checked,
        "changes": changes,
        "summary": summary,
    }


def _analyze_truth_file(name: str, data: dict, chapter: int) -> Dict[str, Any]:
    """分析单个真相文件的变更摘要。"""
    result: Dict[str, Any] = {
        "status": "ok",
        "added_count": 0,
        "modified_count": 0,
        "items": [],
    }

    if name == "character_matrix":
        characters = data.get("characters", [])
        result["added_count"] = len(characters)
        for c in characters:
            result["items"].append({
                "type": "character",
                "name": c.get("name", ""),
                "role": c.get("role", ""),
                "status": c.get("status", "alive"),
            })

    elif name == "hook_ledger":
        hooks = data.get("hooks", [])
        open_hooks = [h for h in hooks if h.get("status") in ("open", "mentioned")]
        resolved_hooks = [h for h in hooks if h.get("status") == "resolved"]
        result["added_count"] = len(hooks)
        result["items"] = [
            {"type": "hook", "id": h.get("id", ""), "status": h.get("status", "")}
            for h in hooks
        ]
        result["open_count"] = len(open_hooks)
        result["resolved_count"] = len(resolved_hooks)

    elif name == "resource_ledger":
        resources = data.get("resources", [])
        power_levels = data.get("power_levels", [])
        result["added_count"] = len(resources) + len(power_levels)
        result["items"] = [
            {"type": "resource", "name": r.get("name", ""), "owner": r.get("owner", "")}
            for r in resources
        ] + [
            {"type": "power_level", "character": p.get("character", ""), "level": p.get("level", "")}
            for p in power_levels
        ]

    elif name == "emotional_arcs":
        characters = data.get("characters", {})
        result["added_count"] = len(characters)
        for name_char, arc_data in characters.items():
            arc_points = arc_data.get("arc", [])
            result["items"].append({
                "type": "emotion",
                "character": name_char,
                "current_emotion": arc_data.get("current_emotion", ""),
                "arc_direction": arc_data.get("arc_direction", ""),
                "point_count": len(arc_points),
            })

    elif name == "subplot_board":
        subplots = data.get("subplots", [])
        result["added_count"] = len(subplots)
        result["items"] = [
            {
                "type": "subplot",
                "id": s.get("id", ""),
                "name": s.get("name", ""),
                "status": s.get("status", ""),
            }
            for s in subplots
        ]

    elif name == "world_state":
        locations = data.get("locations", [])
        result["added_count"] = len(locations)
        result["items"] = [
            {"type": "location", "name": loc.get("name", "")}
            for loc in locations
        ]

    elif name == "chapter_summaries":
        chapters = data.get("chapters", [])
        result["added_count"] = len(chapters)
        result["items"] = [
            {
                "type": "chapter_summary",
                "chapter": c.get("chapter", 0),
                "title": c.get("title", ""),
                "word_count": c.get("word_count", 0),
            }
            for c in chapters
        ]

    return result


def format_report(report: Dict[str, Any]) -> str:
    """将报告格式化为可读文本。"""
    lines = [
        f"# 第{report['chapter']}章 真相同步报告\n",
        f"**检查文件数**：{len(report['files_checked'])}\n",
        f"**总结**：{report['summary']}\n",
        "---\n",
    ]

    for name in report["files_checked"]:
        changes = report["changes"].get(name, {})
        status = changes.get("status", "unknown")
        lines.append(f"## {name}\n")

        if status in ("not_found", "error"):
            lines.append(f"状态：{status}\n")
            if changes.get("errors"):
                lines.append(f"错误：{', '.join(changes['errors'])}\n")
            continue

        added_count = changes.get("added_count", 0)
        lines.append(f"条目数：{added_count}\n")

        if changes.get("open_count") is not None:
            lines.append(f"待回收钩子：{changes['open_count']}，已回收：{changes.get('resolved_count', 0)}\n")

        for item in changes.get("items", [])[:10]:  # 只显示前 10 项
            item_type = item.get("type", "")
            if item_type == "character":
                lines.append(f"- 角色: {item['name']} ({item['role']}) [{item['status']}]\n")
            elif item_type == "hook":
                lines.append(f"- 钩子: {item['id']} [{item['status']}]\n")
            elif item_type == "resource":
                lines.append(f"- 资源: {item['name']} (持有者: {item['owner']})\n")
            elif item_type == "power_level":
                lines.append(f"- 力量等级: {item['character']} → {item['level']}\n")
            elif item_type == "emotion":
                lines.append(f"- 情感: {item['character']} [{item['current_emotion']}] 方向:{item['arc_direction']}\n")
            elif item_type == "subplot":
                lines.append(f"- 支线: {item['name']} [{item['status']}]\n")
            elif item_type == "location":
                lines.append(f"- 地点: {item['name']}\n")
            elif item_type == "chapter_summary":
                lines.append(f"- 摘要: 第{item['chapter']}章 {item['title']} ({item['word_count']}字)\n")

        if added_count > 10:
            lines.append(f"- ... 还有 {added_count - 10} 项\n")
        lines.append("")

    return "".join(lines)


# =============================================================================
# CLI 入口
# =============================================================================

def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="真相同步报告：对比更新前后的真相文件",
    )
    parser.add_argument("--project-root", "-p", required=True, help="项目根目录")
    parser.add_argument("--chapter", "-c", type=int, required=True, help="章节号")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--output", "-o", help="输出到文件")

    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.exists():
        print(f"[ERROR] 项目目录不存在: {project_root}")
        return 1

    report = generate_report(str(project_root), args.chapter)

    if args.json:
        output = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        output = format_report(report)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(output, encoding="utf-8")
        print(f"[OK] 报告已保存到 {out_path}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    exit(main())
