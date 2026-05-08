#!/usr/bin/env python3
"""门禁扩展步骤（B3）

5个门禁检查函数，复用 truth_manager 现有逻辑并包装为统一格式。

路径：~/.hermes/skills/novel-creator-skill/scripts/gate_extensions.py
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# 确保同目录脚本可直接 import
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import truth_manager  # noqa: E402


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

_SKIP_RESULT: Dict[str, Any] = {
    "passed": True,
    "issues": [],
    "details": "跳过（truth文件不存在）",
}


def _truth_exists(project_root: str, file_name: str) -> bool:
    """判断 truth 文件是否存在"""
    return truth_manager.get_truth_path(project_root, file_name).exists()


def _wrap(project_root: str, file_name: str, check_fn) -> Dict[str, Any]:
    """通用包装：不存在 → skip，否则调用 check_fn，把 issues 映射为 passed"""
    if not _truth_exists(project_root, file_name):
        return dict(_SKIP_RESULT)
    try:
        issues: List[str] = check_fn()
        passed = len(issues) == 0
        details = "通过" if passed else "；".join(issues)
        return {"passed": passed, "issues": issues, "details": details}
    except Exception as exc:
        return {"passed": False, "issues": [f"异常: {exc}"], "details": f"异常: {exc}"}


# ---------------------------------------------------------------------------
# 1. check_hook_health
# ---------------------------------------------------------------------------

def check_hook_health(project_root: str, chapter: int) -> Dict[str, Any]:
    """检查钩子健康状态（stale_debt / burst / no_advance）"""
    return _wrap(project_root, "hook_ledger", lambda: _check_hook_health_impl(project_root, chapter))


def _check_hook_health_impl(project_root: str, chapter: int) -> List[str]:
    health = truth_manager.check_hook_health(project_root, chapter)
    issues: List[str] = []
    for item in health.get("stale_debt", []):
        issues.append(f"超期未回收: {item}")
    for item in health.get("burst_warning", []):
        issues.append(f"批量回收: {item}")
    for item in health.get("no_advance", []):
        issues.append(f"长期未提及: {item}")
    return issues


# ---------------------------------------------------------------------------
# 2. check_resource_consistency
# ---------------------------------------------------------------------------

def check_resource_consistency(project_root: str, chapter: int) -> Dict[str, Any]:
    """检查资源一致性（突变检测）"""
    return _wrap(project_root, "resource_ledger", lambda: truth_manager.check_resource_consistency(project_root, chapter))


# ---------------------------------------------------------------------------
# 3. check_emotional_arc
# ---------------------------------------------------------------------------

def check_emotional_arc(project_root: str, chapter: int) -> Dict[str, Any]:
    """检查情感弧光一致性"""
    return _wrap(project_root, "emotional_arcs", lambda: truth_manager.check_emotional_consistency(project_root, chapter))


# ---------------------------------------------------------------------------
# 4. check_subplot_progress
# ---------------------------------------------------------------------------

def check_subplot_progress(project_root: str, chapter: int) -> Dict[str, Any]:
    """检查支线进度（遗忘/过多/冲突）"""
    return _wrap(project_root, "subplot_board", lambda: truth_manager.check_subplot_health(project_root, chapter))


# ---------------------------------------------------------------------------
# 5. check_chapter_distance
# ---------------------------------------------------------------------------

def check_chapter_distance(project_root: str, chapter: int) -> Dict[str, Any]:
    """检查章间距：相邻章节摘要间字数差距过大"""
    data, errors = truth_manager.load_truth(project_root, "chapter_summaries")
    if errors or not data.get("chapters"):
        return dict(_SKIP_RESULT)

    issues: List[str] = []
    summaries = sorted(data["chapters"], key=lambda c: c.get("chapter", 0))
    for i in range(1, len(summaries)):
        prev_len = summaries[i - 1].get("char_count", 0)
        curr_len = summaries[i].get("char_count", 0)
        if prev_len > 0 and curr_len > 0:
            ratio = max(curr_len / prev_len, prev_len / curr_len)
            if ratio > 3.0:
                issues.append(
                    f"第{summaries[i-1].get('chapter')}章({prev_len}字) vs 第{summaries[i].get('chapter')}章({curr_len}字) 差距过大(ratio={ratio:.1f})"
                )

    passed = len(issues) == 0
    details = "通过" if passed else "；".join(issues)
    return {"passed": passed, "issues": issues, "details": details}
