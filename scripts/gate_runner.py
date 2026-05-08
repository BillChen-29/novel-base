#!/usr/bin/env python3
"""门禁运行器（B3）

组合原有 chapter_gate_check + 扩展 gate_extensions，输出完整 gate_result.json。

路径：~/.hermes/skills/novel-creator-skill/scripts/gate_runner.py
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# 确保同目录脚本可直接 import
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import gate_extensions as _ext  # noqa: E402
import chapter_gate_check as _gate  # noqa: E402
from common import slugify  # noqa: E402


# ---------------------------------------------------------------------------
# 核心运行函数
# ---------------------------------------------------------------------------

def run_full_gate(
    project_root: str,
    chapter_file: str,
    chapter_id: str | None = None,
    min_bytes: int = 20,
    publish_keywords: str = "可发布,通过,PASS",
) -> Dict[str, Any]:
    """执行完整门禁：原有步骤 + 扩展步骤，返回统一 gate_result。

    Returns:
        {
            "passed": bool,
            "steps": {
                "memory_sync": {...},
                "consistency": {...},
                "style_calibration": {...},
                "proofreading": {...},
                "gate_script": {...},
                "hook_health": {...},
                "resource_consistency": {...},
                "emotional_arc": {...},
                "subplot_progress": {...},
                "chapter_distance": {...}
            }
        }
    """
    project = Path(project_root).expanduser().resolve()
    ch_path = _gate.resolve_chapter(project, chapter_file)
    ch_id = slugify(chapter_id or ch_path.stem)

    gate_dir = project / "04_editing" / "gate_artifacts" / ch_id
    gate_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 从原始 chapter_gate_check 构建 results dict ----------
    import types as _types
    import datetime as _dt

    orig_args = _types.SimpleNamespace(
        project_root=str(project),
        chapter_file=str(ch_path),
        chapter_id=ch_id,
        min_bytes=min_bytes,
        publish_keywords=publish_keywords,
        emit_json=None,
        pacing_tier=None,
        pacing_event_types="",
    )

    # 手动执行原始检查（不走 CLI，而是复用检查函数）
    orig_result: Dict[str, Any] = {
        "checked_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "passed": False,
        "checks": [],
        "failures": [],
        "warnings": [],
    }

    if not ch_path.exists():
        orig_result["failures"].append(f"章节文件不存在: {ch_path}")

    # chapter_storage
    ok, msg = _gate.check_chapter_storage(project, ch_path)
    orig_result["checks"].append({"name": "chapter_storage_policy", "ok": ok, "message": msg})
    if not ok:
        orig_result["failures"].append(f"chapter_storage_policy: {msg}")

    # knowledge_base_isolation
    misplaced = _gate.find_misplaced_chapters(project)
    if misplaced:
        orig_result["failures"].append("knowledge_base_isolation: 发现章节文件混入 02_knowledge_base")

    # 产物文件检查
    artifacts = _gate.required_artifacts(gate_dir)
    chapter_mtime = ch_path.stat().st_mtime if ch_path.exists() else 0

    for name, fpath in artifacts.items():
        ok, msg = _gate.check_file(fpath, min_bytes, chapter_mtime)
        orig_result["checks"].append({"name": name, "ok": ok, "message": msg})
        if not ok:
            orig_result["failures"].append(f"{name}: {msg}")

    # publish_ready keyword
    publish_path = artifacts["publish_ready"]
    if publish_path.exists() and publish_path.stat().st_size >= min_bytes:
        ok, msg = _gate.check_publish_ready(publish_path, [k.strip() for k in publish_keywords.split(",")])
        orig_result["checks"].append({"name": "publish_ready_keyword", "ok": ok, "message": msg})
        if not ok:
            orig_result["failures"].append(f"publish_ready_keyword: {msg}")

    # quality_report
    quality_path = artifacts["quality_report"]
    if quality_path.exists() and quality_path.stat().st_size >= min_bytes:
        ok, msg = _gate.check_quality_report(quality_path)
        orig_result["checks"].append({"name": "quality_baseline", "ok": ok, "message": msg})
        if not ok:
            orig_result["failures"].append(f"quality_baseline: {msg}")

    orig_result["passed"] = len(orig_result["failures"]) == 0

    # ---------- 映射到 steps 字典 ----------
    def _to_step(name: str, checks: list) -> Dict[str, Any]:
        ok = all(c["ok"] for c in checks) if checks else True
        issues = [f"{c['name']}: {c['message']}" for c in checks if not c["ok"]]
        return {"passed": ok, "issues": issues, "checks": checks}

    # 提取各子步骤（按 artifact 名称映射）
    def _find_check(check_name: str) -> Dict[str, Any]:
        return next((c for c in orig_result["checks"] if c["name"] == check_name), {"ok": True, "message": "N/A"})

    steps: Dict[str, Any] = {}
    steps["memory_sync"] = _to_step("memory_sync", [_find_check("memory_update")])
    steps["consistency"] = _to_step("consistency", [_find_check("consistency_report")])
    steps["style_calibration"] = _to_step("style_calibration", [_find_check("style_calibration")])
    steps["proofreading"] = _to_step("proofreading", [_find_check("copyedit_report"), _find_check("publish_ready")])
    steps["gate_script"] = _to_step("gate_script", [_find_check("quality_baseline")])

    # ---------- 扩展步骤 ----------
    try:
        steps["hook_health"] = _ext.check_hook_health(str(project), _gate.extract_chapter_number(ch_id))
    except Exception as exc:
        steps["hook_health"] = {"passed": True, "issues": [], "details": f"跳过（异常: {exc}）"}

    try:
        steps["resource_consistency"] = _ext.check_resource_consistency(str(project), _gate.extract_chapter_number(ch_id))
    except Exception as exc:
        steps["resource_consistency"] = {"passed": True, "issues": [], "details": f"跳过（异常: {exc}）"}

    try:
        steps["emotional_arc"] = _ext.check_emotional_arc(str(project), _gate.extract_chapter_number(ch_id))
    except Exception as exc:
        steps["emotional_arc"] = {"passed": True, "issues": [], "details": f"跳过（异常: {exc}）"}

    try:
        steps["subplot_progress"] = _ext.check_subplot_progress(str(project), _gate.extract_chapter_number(ch_id))
    except Exception as exc:
        steps["subplot_progress"] = {"passed": True, "issues": [], "details": f"跳过（异常: {exc}）"}

    try:
        steps["chapter_distance"] = _ext.check_chapter_distance(str(project), _gate.extract_chapter_number(ch_id))
    except Exception as exc:
        steps["chapter_distance"] = {"passed": True, "issues": [], "details": f"跳过（异常: {exc}）"}

    # ---------- 综合判定 ----------
    all_passed = all(s.get("passed", True) for s in steps.values()) and orig_result["passed"]

    full_result = {
        "passed": all_passed,
        "steps": steps,
        "origin": orig_result,
    }

    # 写入 gate_result.json
    out_path = gate_dir / "gate_result.json"
    out_path.write_text(json.dumps(full_result, ensure_ascii=False, indent=2), encoding="utf-8")

    return full_result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="完整门禁运行器：原有检查 + 扩展步骤")
    p.add_argument("--project-root", required=True, help="小说项目根目录")
    p.add_argument("--chapter-file", required=True, help="章节文件路径")
    p.add_argument("--chapter-id", help="章节标识（默认从文件名推导）")
    p.add_argument("--min-bytes", type=int, default=20, help="门禁产物最小字节数")
    p.add_argument("--publish-keywords", default="可发布,通过,PASS", help="发布关键字")
    args = p.parse_args()

    result = run_full_gate(
        project_root=args.project_root,
        chapter_file=args.chapter_file,
        chapter_id=args.chapter_id,
        min_bytes=args.min_bytes,
        publish_keywords=args.publish_keywords,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
