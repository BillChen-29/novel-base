#!/usr/bin/env python3
"""
Auto Truth Sync - 自动同步脚本

功能：
1. 读取最新章节正文
2. 调用 chapter_observer 组装输入
3. 调用 chapter_reflector 更新真相文件
4. 调用 truth_manager.render_markdown 生成投影

路径：~/.hermes/skills/novel-creator-skill/scripts/auto_truth_sync.py
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保 scripts/ 在 sys.path 中
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import truth_manager  # noqa: E402
from common import read_text, load_json  # noqa: E402
from chapter_observer import assemble_observer_input, parse_observer_output  # noqa: E402
from chapter_reflector import reflect  # noqa: E402


def _load_truth_as_text(project_root: str) -> str:
    """将所有真相文件加载为文本摘要。"""
    truth_files = [
        "world_state", "character_matrix", "emotional_arcs",
        "resource_ledger", "subplot_board", "hook_ledger",
        "chapter_summaries",
    ]
    parts = []
    for name in truth_files:
        data, errors = truth_manager.load_truth(project_root, name)
        if data and not errors:
            parts.append(f"=== {name} ===\n{json.dumps(data, ensure_ascii=False, indent=2)}")
    return "\n\n".join(parts)


def _read_chapter_text(project_root: str, chapter: int) -> str:
    """读取章节正文。"""
    manuscript_dir = Path(project_root) / "03_manuscript"
    if not manuscript_dir.exists():
        return ""

    for f in sorted(manuscript_dir.glob(f"第{chapter}章*.md")):
        return read_text(f, default="")
    return ""


def auto_sync(
    project_root: str,
    chapter: int,
    chapter_text: Optional[str] = None,
    delta: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    自动同步：Observer 输入组装 + Reflector 更新 + Markdown 投影。

    Args:
        project_root: 项目根目录
        chapter: 章节号
        chapter_text: 章节正文（不提供则自动读取）
        delta: Observer 输出的增量信息（不提供则只组装 prompt）

    Returns:
        {
            "prompt": str,           # Observer prompt（供外部 LLM 使用）
            "observer_output": str,  # LLM 原始输出（如有）
            "delta": dict,           # 解析后的 delta（如有）
            "reflect_result": dict,  # Reflector 更新结果（如有）
            "errors": List[str],
        }
    """
    errors: List[str] = []
    result: Dict[str, Any] = {
        "prompt": "",
        "observer_output": "",
        "delta": None,
        "reflect_result": None,
        "errors": errors,
    }

    # 1. 读取章节正文
    if chapter_text is None:
        chapter_text = _read_chapter_text(project_root, chapter)
    if not chapter_text:
        errors.append(f"章节 {chapter} 正文为空，请提供 --chapter-text 参数")
        return result

    # 2. 加载当前真相
    current_truth = _load_truth_as_text(project_root)

    # 3. 组装 Observer prompt
    prompt = assemble_observer_input(chapter_text, current_truth)
    result["prompt"] = prompt

    # 4. 如果没有提供 delta，返回 prompt 供外部 LLM 使用
    if delta is None:
        print("[Auto Sync] 需要外部 LLM 处理 Observer prompt")
        print(f"[Auto Sync] Prompt 长度: {len(prompt)} 字符")
        return result

    # 5. 有 delta，执行 Reflector
    print(f"[Auto Sync] 执行 Reflector 更新（第{chapter}章）...")
    reflect_result = reflect(project_root, delta, chapter)
    result["delta"] = delta
    result["reflect_result"] = reflect_result

    updated_count = len(reflect_result.get("updated", []))
    error_count = len(reflect_result.get("errors", []))
    print(f"[Auto Sync] 更新完成: {updated_count} 项更新, {error_count} 项错误")

    # 6. 生成 markdown 投影
    print("[Auto Sync] 生成 markdown 投影...")
    truth_files = [
        "world_state", "character_matrix", "emotional_arcs",
        "resource_ledger", "subplot_board", "hook_ledger",
        "chapter_summaries",
    ]
    for name in truth_files:
        truth_manager.render_markdown(project_root, name)

    print("[Auto Sync] 同步完成")
    return result


# =============================================================================
# CLI 入口
# =============================================================================

def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="自动同步脚本：Observer + Reflector + Markdown 投影",
    )
    parser.add_argument("--project-root", "-p", required=True, help="项目根目录")
    parser.add_argument("--chapter", "-c", type=int, required=True, help="章节号")
    parser.add_argument("--chapter-text", "-t", help="章节正文文本（可选，不提供则自动读取文件）")
    parser.add_argument("--delta-file", "-d", help="delta JSON 文件路径（可选）")
    parser.add_argument("--output-prompt", "-o", help="将 Observer prompt 输出到文件")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.exists():
        print(f"[ERROR] 项目目录不存在: {project_root}")
        return 1

    # 加载 delta（如果有）
    delta = None
    if args.delta_file:
        delta_path = Path(args.delta_file)
        if delta_path.exists():
            with open(delta_path, "r", encoding="utf-8") as f:
                delta = json.load(f)

    # 如果提供了 --output-prompt，只输出 prompt
    if args.output_prompt and delta is None:
        chapter_text = args.chapter_text or _read_chapter_text(str(project_root), args.chapter)
        if not chapter_text:
            print(f"[ERROR] 章节 {args.chapter} 正文为空")
            return 1
        current_truth = _load_truth_as_text(str(project_root))
        prompt = assemble_observer_input(chapter_text, current_truth)
        out_path = Path(args.output_prompt)
        out_path.write_text(prompt, encoding="utf-8")
        print(json.dumps({
            "ok": True,
            "prompt_file": str(out_path),
            "prompt_length": len(prompt),
        }, ensure_ascii=False))
        return 0

    result = auto_sync(
        str(project_root),
        args.chapter,
        chapter_text=args.chapter_text,
        delta=delta,
    )

    # 输出结果
    output = {
        "ok": len(result["errors"]) == 0,
        "prompt_length": len(result["prompt"]),
        "has_delta": result["delta"] is not None,
    }
    if result["reflect_result"]:
        output["updated"] = result["reflect_result"].get("updated", [])
        output["errors"] = result["reflect_result"].get("errors", [])
    elif result["errors"]:
        output["errors"] = result["errors"]

    print(json.dumps(output, ensure_ascii=False, indent=2 if args.verbose else None))

    return 0 if output["ok"] else 1


if __name__ == "__main__":
    exit(main())
