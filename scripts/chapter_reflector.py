#!/usr/bin/env python3
"""
Chapter Reflector - 接收 Observer 的 JSON delta，更新真相文件

Reflector 角色：接收 Observer 的 JSON delta，
解析各类操作并调用 truth_manager 进行更新。

路径：~/.hermes/skills/novel-creator-skill/scripts/chapter_reflector.py
"""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# 确保 scripts/ 在 sys.path 中
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import truth_manager  # noqa: E402


def _safe_call(fn, *args, **kwargs) -> Tuple[bool, List[str]]:
    """
    安全调用 truth_manager 函数，捕获异常。

    Returns:
        (success, errors)
    """
    try:
        result = fn(*args, **kwargs)
        # 多数 truth_manager 函数返回 (success, errors) 或 (success, id, errors)
        if isinstance(result, tuple):
            if len(result) == 3:
                return result[0], result[2]  # (success, id, errors) → (success, errors)
            elif len(result) == 2:
                return result[0], result[1]
        return True, []
    except Exception as e:
        return False, [f"{fn.__name__} 异常: {e}"]


def reflect(
    project_root: str,
    delta: dict,
    current_chapter: int,
) -> Dict[str, Any]:
    """
    接收 Observer 的 JSON delta，更新真相文件。

    Args:
        project_root: 项目根目录
        delta: Observer 输出的增量信息字典
        current_chapter: 当前章节号

    Returns:
        {"updated": List[str], "errors": List[str]}
    """
    updated: List[str] = []
    errors: List[str] = []

    if not isinstance(delta, dict):
        errors.append("delta 格式错误：期望 dict")
        return {"updated": updated, "errors": errors}

    if not delta:
        # 空 delta，无变更
        return {"updated": updated, "errors": errors}

    # ── hook_operations ──
    for op in delta.get("hook_operations", []):
        if not isinstance(op, dict):
            errors.append(f"hook_operation 格式错误: {op}")
            continue

        operation = op.get("operation", "")
        try:
            if operation == "create":
                success, errs = _safe_call(
                    truth_manager.upsert_hook,
                    project_root, current_chapter,
                    op.get("description", ""),
                    id=op.get("hook_id", ""),
                    type=op.get("type", "foreshadowing"),
                    importance=op.get("importance", "medium"),
                    related_characters=op.get("related_characters", []),
                )
                if success:
                    updated.append(f"hook:create:{op.get('description', '')[:30]}")
                else:
                    errors.extend(errs)

            elif operation == "mention":
                hook_id = op.get("hook_id", "")
                if not hook_id:
                    errors.append("hook mention 缺少 hook_id")
                    continue
                success, errs = _safe_call(
                    truth_manager.mention_hook,
                    project_root, current_chapter, hook_id,
                )
                if success:
                    updated.append(f"hook:mention:{hook_id}")
                else:
                    errors.extend(errs)

            elif operation == "resolve":
                hook_id = op.get("hook_id", "")
                if not hook_id:
                    errors.append("hook resolve 缺少 hook_id")
                    continue
                success, errs = _safe_call(
                    truth_manager.resolve_hook,
                    project_root, current_chapter, hook_id,
                )
                if success:
                    updated.append(f"hook:resolve:{hook_id}")
                else:
                    errors.extend(errs)
            else:
                errors.append(f"未知 hook 操作: {operation}")
        except Exception as e:
            errors.append(f"hook 操作异常: {e}")

    # ── resource_changes ──
    for res in delta.get("resource_changes", []):
        if not isinstance(res, dict):
            errors.append(f"resource_change 格式错误: {res}")
            continue
        try:
            name = res.get("name", "")
            if not name:
                errors.append("resource_change 缺少 name")
                continue
            success, errs = _safe_call(
                truth_manager.add_resource,
                project_root, current_chapter,
                name=name,
                type=res.get("type", "item"),
                owner=res.get("owner", ""),
                amount=res.get("amount", 0),
            )
            if success:
                updated.append(f"resource:add:{name}")
            else:
                errors.extend(errs)
        except Exception as e:
            errors.append(f"resource 操作异常: {e}")

    # ── emotion_changes ──
    for emo in delta.get("emotion_changes", []):
        if not isinstance(emo, dict):
            errors.append(f"emotion_change 格式错误: {emo}")
            continue
        try:
            character = emo.get("character", "")
            if not character:
                errors.append("emotion_change 缺少 character")
                continue
            success, errs = _safe_call(
                truth_manager.add_emotion_point,
                project_root, character, current_chapter,
                emo.get("emotion", ""),
                emo.get("intensity", 5),
                emo.get("trigger", ""),
            )
            if success:
                updated.append(f"emotion:add:{character}")
            else:
                errors.extend(errs)
        except Exception as e:
            errors.append(f"emotion 操作异常: {e}")

    # ── subplot_progress ──
    for sub in delta.get("subplot_progress", []):
        if not isinstance(sub, dict):
            errors.append(f"subplot_progress 格式错误: {sub}")
            continue
        try:
            operation = sub.get("operation", "")
            name = sub.get("name", "")

            if operation == "create":
                if not name:
                    errors.append("subplot create 缺少 name")
                    continue
                success, errs = _safe_call(
                    truth_manager.add_subplot,
                    project_root, name, current_chapter,
                    key_characters=sub.get("key_characters", []),
                )
                if success:
                    updated.append(f"subplot:create:{name}")
                else:
                    errors.extend(errs)

            elif operation == "update":
                subplot_id = sub.get("subplot_id", "")
                if not subplot_id:
                    errors.append("subplot update 缺少 subplot_id")
                    continue
                new_status = sub.get("status", "active")
                success, errs = _safe_call(
                    truth_manager.update_subplot_status,
                    project_root, subplot_id, new_status, current_chapter,
                )
                if success:
                    updated.append(f"subplot:update:{subplot_id}")
                else:
                    errors.extend(errs)
            else:
                errors.append(f"未知 subplot 操作: {operation}")
        except Exception as e:
            errors.append(f"subplot 操作异常: {e}")

    # ── new_characters ──
    for char in delta.get("new_characters", []):
        if not isinstance(char, dict):
            errors.append(f"new_character 格式错误: {char}")
            continue
        try:
            name = char.get("name", "")
            if not name:
                errors.append("new_character 缺少 name")
                continue
            success, errs = _safe_call(
                truth_manager.upsert_character,
                project_root, name,
                role=char.get("role", ""),
                personality=char.get("personality", ""),
                motivation=char.get("motivation", ""),
                abilities=char.get("abilities", []),
                relationships=char.get("relationships", {}),
                status=char.get("status", "alive"),
                notes=char.get("notes", ""),
            )
            if success:
                updated.append(f"character:upsert:{name}")
            else:
                errors.extend(errs)
        except Exception as e:
            errors.append(f"character 操作异常: {e}")

    # ── world_additions ──
    for world in delta.get("world_additions", []):
        if not isinstance(world, dict):
            errors.append(f"world_addition 格式错误: {world}")
            continue
        try:
            operation = world.get("operation", "add_location")
            name = world.get("name", "")
            description = world.get("description", "")

            if operation == "add_location":
                if not name:
                    errors.append("world add_location 缺少 name")
                    continue
                success, errs = _safe_call(
                    truth_manager.add_location,
                    project_root, name, description,
                )
                if success:
                    updated.append(f"world:add_location:{name}")
                else:
                    errors.extend(errs)

            elif operation == "update_world":
                if not name:
                    errors.append("world update_world 缺少 name")
                    continue
                success, errs = _safe_call(
                    truth_manager.update_world_state,
                    project_root, **{name: description},
                )
                if success:
                    updated.append(f"world:update_world:{name}")
                else:
                    errors.extend(errs)
            else:
                errors.append(f"未知 world 操作: {operation}")
        except Exception as e:
            errors.append(f"world 操作异常: {e}")

    # ── relationship_changes ──
    for rel in delta.get("relationship_changes", []):
        if not isinstance(rel, dict):
            errors.append(f"relationship_change 格式错误: {rel}")
            continue
        try:
            character = rel.get("character", "")
            target = rel.get("target", "")
            relationship = rel.get("relationship", "")
            if not character:
                errors.append("relationship_change 缺少 character")
                continue
            success, errs = _safe_call(
                truth_manager.upsert_character,
                project_root, character,
                relationships={target: relationship} if target else {},
            )
            if success:
                updated.append(f"relationship:update:{character}->{target}")
            else:
                errors.extend(errs)
        except Exception as e:
            errors.append(f"relationship 操作异常: {e}")

    # ── power_level_changes ──
    for pl in delta.get("power_level_changes", []):
        if not isinstance(pl, dict):
            errors.append(f"power_level_change 格式错误: {pl}")
            continue
        try:
            character = pl.get("character", "")
            if not character:
                errors.append("power_level_change 缺少 character")
                continue
            level = pl.get("level", "")
            success, errs = _safe_call(
                truth_manager.add_resource,
                project_root, current_chapter,
                name=f"{character}_power_level",
                type="power_level",
                owner=character,
                amount=level,
            )
            if success:
                updated.append(f"power_level:update:{character}")
            else:
                errors.extend(errs)
        except Exception as e:
            errors.append(f"power_level 操作异常: {e}")

    # ── timeline_advance ──
    timeline = delta.get("timeline_advance", {})
    if timeline and isinstance(timeline, dict):
        try:
            chapter_summary = timeline.get("chapter_summary", "")
            if chapter_summary:
                success, errs = _safe_call(
                    truth_manager.add_chapter_summary,
                    project_root, current_chapter,
                    f"第{current_chapter}章",
                    chapter_summary,
                    key_events=timeline.get("key_events", []),
                    characters_involved=timeline.get("characters_involved", []),
                )
                if success:
                    updated.append(f"timeline:advance:ch{current_chapter}")
                else:
                    errors.extend(errs)
        except Exception as e:
            errors.append(f"timeline 操作异常: {e}")

    return {"updated": updated, "errors": errors}


# =============================================================================
# CLI 入口
# =============================================================================

def main():
    """命令行入口：读取 delta JSON 文件并执行更新。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Chapter Reflector - 更新真相文件")
    parser.add_argument("--project-root", "-p", required=True, help="项目根目录")
    parser.add_argument("--chapter", "-c", type=int, required=True, help="当前章节号")
    parser.add_argument("--delta-file", "-d", required=True, help="delta JSON 文件路径")
    args = parser.parse_args()

    delta_path = Path(args.delta_file)
    if not delta_path.exists():
        print(f"[ERROR] delta 文件不存在: {delta_path}")
        return 1

    with open(delta_path, "r", encoding="utf-8") as f:
        delta = json.load(f)

    result = reflect(args.project_root, delta, args.chapter)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    exit(main())
