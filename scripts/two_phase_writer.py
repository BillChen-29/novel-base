#!/usr/bin/env python3
"""
Two Phase Writer - 两阶段写作系统

Phase 1（创意阶段）：
  - 读取真相文件
  - 搜索相关内容
  - 过滤和加权
  - 加载场景模板
  - 组装写作 prompt
  - 调用 novel_chapter_writer.py 生成正文

Phase 2（状态沉淀阶段）：
  - 调用 chapter_observer 组装输入
  - （LLM 调用由外部执行）
  - 调用 chapter_reflector 更新真相文件
  - 生成 markdown 投影

路径：~/.hermes/skills/novel-creator-skill/scripts/two_phase_writer.py
"""

from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 确保 scripts/ 在 sys.path 中
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import truth_manager  # noqa: E402
from common import (  # noqa: E402
    apply_distance_rules,
    filter_search_results,
    load_scenario_by_role,
    unified_search,
    read_text,
    load_json,
)
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


def _get_chapter_info(project_root: str, chapter: int) -> Dict[str, Any]:
    """获取章节元数据。"""
    meta_dir = Path(project_root) / "00_memory" / "retrieval" / "chapter_meta"
    if not meta_dir.exists():
        return {}

    for meta_file in sorted(meta_dir.glob("*.meta.json")):
        info = load_json(meta_dir / meta_file.name, default={})
        if info.get("chapter_number") == chapter:
            return info
    return {}


def _read_chapter_text(project_root: str, chapter: int) -> str:
    """读取章节正文。"""
    manuscript_dir = Path(project_root) / "03_manuscript"
    if not manuscript_dir.exists():
        return ""

    for f in manuscript_dir.glob(f"第{chapter}章*.md"):
        return read_text(f, default="")
    return ""


def phase1_assemble(
    project_root: str,
    chapter: int,
) -> Dict[str, Any]:
    """
    Phase 1：组装写作所需的全部上下文。

    Returns:
        {
            "truth_text": str,         # 真相文件文本
            "search_results": dict,     # unified_search 结果
            "filtered_results": dict,   # 过滤后的结果
            "weighted_results": list,   # 距离加权后的平铺列表
            "scenarios": list,          # 场景模板
            "chapter_info": dict,       # 章节元数据
        }
    """
    result: Dict[str, Any] = {}

    # 1. 读取真相文件
    result["truth_text"] = _load_truth_as_text(project_root)

    # 2. 获取章节元数据
    chapter_info = _get_chapter_info(project_root, chapter)
    result["chapter_info"] = chapter_info

    # 3. 统一搜索
    chapter_goal = chapter_info.get("chapter_purpose", "")
    query = chapter_goal or f"第{chapter}章 剧情"
    search_results = unified_search(query, project_root=project_root)
    result["search_results"] = search_results

    # 4. 三阶段过滤
    chapter_summaries_data, _ = truth_manager.load_truth(project_root, "chapter_summaries")
    chapter_summaries = []
    if chapter_summaries_data:
        chapter_summaries = chapter_summaries_data.get("chapters", [])

    filtered = filter_search_results(search_results, chapter, chapter_summaries)
    result["filtered_results"] = filtered

    # 5. 距离加权
    weighted = apply_distance_rules(filtered, chapter)
    result["weighted_results"] = weighted

    # 6. 加载场景模板
    chapter_role = chapter_info.get("chapter_role", "铺垫")
    scenarios = load_scenario_by_role(chapter_role)
    result["scenarios"] = scenarios

    return result


def phase1_write(
    project_root: str,
    chapter: int,
    extra_args: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Phase 1：调用 novel_chapter_writer.py 生成正文。

    Args:
        project_root: 项目根目录
        chapter: 章节号
        extra_args: 额外传递给 novel_chapter_writer.py 的参数

    Returns:
        {"ok": bool, "exit_code": int, "stdout": str, "stderr": str}
    """
    writer_script = _SCRIPT_DIR / "novel_chapter_writer.py"

    cmd = [
        sys.executable, str(writer_script),
        "--project-root", str(project_root),
    ]

    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "novel_chapter_writer.py 执行超时",
        }
    except Exception as e:
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
        }


def phase2_observe(
    project_root: str,
    chapter: int,
    chapter_text: Optional[str] = None,
) -> Tuple[str, Optional[dict], List[str]]:
    """
    Phase 2：组装 Observer 输入。

    Args:
        project_root: 项目根目录
        chapter: 章节号
        chapter_text: 章节正文（不提供则自动读取）

    Returns:
        (observer_prompt, parsed_delta, errors)
    """
    errors: List[str] = []

    # 读取章节正文
    if chapter_text is None:
        chapter_text = _read_chapter_text(project_root, chapter)
    if not chapter_text:
        errors.append(f"章节 {chapter} 正文为空")
        return ("", None, errors)

    # 加载当前真相
    current_truth = _load_truth_as_text(project_root)

    # 组装 Observer prompt
    prompt = assemble_observer_input(chapter_text, current_truth)

    return (prompt, None, errors)


def phase2_reflect(
    project_root: str,
    chapter: int,
    delta: dict,
) -> Dict[str, Any]:
    """
    Phase 2：执行 Reflector 更新真相文件。

    Args:
        project_root: 项目根目录
        chapter: 章节号
        delta: Observer 输出的增量信息

    Returns:
        reflect() 的返回值
    """
    # 更新真相文件
    result = reflect(project_root, delta, chapter)

    # 生成 markdown 投影
    truth_files = [
        "world_state", "character_matrix", "emotional_arcs",
        "resource_ledger", "subplot_board", "hook_ledger",
        "chapter_summaries",
    ]
    for name in truth_files:
        truth_manager.render_markdown(project_root, name)

    return result


def run_two_phase(
    project_root: str,
    chapter: int,
    extra_args: Optional[List[str]] = None,
    delta: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    执行两阶段写作流程。

    Args:
        project_root: 项目根目录
        chapter: 章节号
        extra_args: 额外传递给 novel_chapter_writer.py 的参数
        delta: Phase 2 的 delta（如已由外部 LLM 生成）

    Returns:
        {
            "phase1": {...},
            "phase2": {...} or None,
        }
    """
    result: Dict[str, Any] = {"phase1": None, "phase2": None}

    # Phase 1：创意写作
    print(f"[Phase 1] 组装写作上下文（第{chapter}章）...")
    assembly = phase1_assemble(project_root, chapter)
    print(f"[Phase 1] 搜索到 {len(assembly.get('weighted_results', []))} 条参考信息")

    print("[Phase 1] 调用 novel_chapter_writer.py 生成正文...")
    write_result = phase1_write(project_root, chapter, extra_args)
    result["phase1"] = {
        "assembly": {
            "chapter_info": assembly.get("chapter_info", {}),
            "weighted_results_count": len(assembly.get("weighted_results", [])),
            "scenarios_count": len(assembly.get("scenarios", [])),
        },
        "write_result": write_result,
    }

    if not write_result["ok"]:
        print(f"[Phase 1] 写作失败 (exit code {write_result['exit_code']})")
        print(f"[Phase 1] stderr: {write_result['stderr'][:500]}")
        print("[Phase 2] 跳过（Phase 1 失败）")
        return result

    print("[Phase 1] 写作成功")

    # Phase 2：状态沉淀
    print(f"[Phase 2] 组装 Observer 输入...")
    prompt, _, observe_errors = phase2_observe(project_root, chapter)

    if observe_errors:
        print(f"[Phase 2] Observer 错误: {observe_errors}")
        result["phase2"] = {"errors": observe_errors}
        return result

    if delta is None:
        # 无外部 delta，提示用户手动执行 LLM
        print("[Phase 2] 需要外部 LLM 调用获取 delta")
        print("[Phase 2] 可使用 auto_truth_sync.py 完成同步")
        result["phase2"] = {
            "status": "needs_llm",
            "prompt_length": len(prompt),
            "errors": [],
        }
        return result

    print("[Phase 2] 执行 Reflector 更新真相文件...")
    reflect_result = phase2_reflect(project_root, chapter, delta)
    result["phase2"] = reflect_result

    updated_count = len(reflect_result.get("updated", []))
    error_count = len(reflect_result.get("errors", []))
    print(f"[Phase 2] 更新完成: {updated_count} 项更新, {error_count} 项错误")

    return result


# =============================================================================
# CLI 入口
# =============================================================================

def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="两阶段写作系统：Phase 1 创意写作 + Phase 2 状态沉淀",
    )
    parser.add_argument("--project-root", "-p", required=True, help="项目根目录")
    parser.add_argument("--chapter", "-c", type=int, required=True, help="章节号")
    parser.add_argument("--delta-file", "-d", help="delta JSON 文件路径（Phase 2 用）")
    parser.add_argument("--dry-run", action="store_true", help="Phase 1 只组装不调用 writer")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    # novel_chapter_writer.py 的透传参数
    parser.add_argument("--provider", help="AI 提供商（透传）")
    parser.add_argument("--model", help="模型名称（透传）")
    parser.add_argument("--api-key", help="API 密钥（透传）")

    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.exists():
        print(f"[ERROR] 项目目录不存在: {project_root}")
        return 1

    # 构建透传参数
    extra_args = []
    if args.provider:
        extra_args.extend(["--provider", args.provider])
    if args.model:
        extra_args.extend(["--model", args.model])
    if args.api_key:
        extra_args.extend(["--api-key", args.api_key])
    if args.dry_run:
        extra_args.append("--dry-run")

    # 加载 delta（如果有）
    delta = None
    if args.delta_file:
        delta_path = Path(args.delta_file)
        if delta_path.exists():
            with open(delta_path, "r", encoding="utf-8") as f:
                delta = json.load(f)

    result = run_two_phase(
        str(project_root),
        args.chapter,
        extra_args=extra_args if extra_args else None,
        delta=delta,
    )

    if args.verbose:
        print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 简要输出
        p1_ok = result["phase1"]["write_result"]["ok"] if result["phase1"] else False
        p2_status = "skipped"
        if result["phase2"]:
            if result["phase2"].get("status") == "needs_llm":
                p2_status = "needs_llm"
            elif result["phase2"].get("updated"):
                p2_status = f"updated:{len(result['phase2']['updated'])}"
            elif result["phase2"].get("errors"):
                p2_status = f"errors:{len(result['phase2']['errors'])}"
        print(json.dumps({
            "ok": p1_ok,
            "phase1": "success" if p1_ok else "failed",
            "phase2": p2_status,
        }, ensure_ascii=False))

    if not result["phase1"]["write_result"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    exit(main())
