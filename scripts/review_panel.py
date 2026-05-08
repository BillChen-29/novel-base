#!/usr/bin/env python3
"""数据复盘面板 — 汇总自评数据与平台数据，输出统计摘要与时序趋势。

子命令：
1. summary — 统计摘要（自评均值、趋势、强弱项频率、哲学覆盖率）
2. trend   — 时序趋势数据（score / read_rate / completion_rate）

输出格式：JSON + 可读 Markdown（stdout 同时输出两种格式）。
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 确保同目录脚本可直接 import ──────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from common import load_json, ensure_dir  # noqa: E402


# ── 常量 ─────────────────────────────────────────────────────

_PREDICTIONS_DIR = "04_predictions"
_PLATFORM_DATA_DIR = "05_data"

# 有效评分范围
_SCORE_MIN, _SCORE_MAX = 1, 5


# ── 内部工具 ─────────────────────────────────────────────────

def _extract_chapter_no(filename: str) -> int:
    """从文件名 ch{N}.json 提取章节号。"""
    m = re.search(r"ch(\d+)", filename)
    return int(m.group(1)) if m else 0


def _load_predictions(root: Path, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
    """加载 04_predictions/ch*.json，按章节号排序。"""
    pred_dir = root / _PREDICTIONS_DIR
    if not pred_dir.exists():
        return []

    records: List[Dict[str, Any]] = []
    for f in sorted(pred_dir.glob("ch*.json")):
        data = load_json(f)
        if not data:
            continue
        # 确保有 chapter_no 字段
        if "chapter_no" not in data:
            data["chapter_no"] = _extract_chapter_no(f.name)
        records.append(data)

    # 按章节号排序
    records.sort(key=lambda r: r.get("chapter_no", 0))

    if last_n is not None and last_n > 0:
        records = records[-last_n:]

    return records


def _load_platform_data(root: Path) -> Dict[int, Dict[str, Any]]:
    """加载 05_data/ 下的平台数据（如果有）。

    期望文件格式: 05_data/ch{N}.json 或 05_data/platform_stats.json
    支持两种格式：
      - ch{N}.json: 单章平台数据
      - platform_stats.json: 全部章节汇总 {ch1: {...}, ch2: {...}, ...}
    """
    data_dir = root / _PLATFORM_DATA_DIR
    if not data_dir.exists():
        return {}

    platform: Dict[int, Dict[str, Any]] = {}

    # 尝试单章文件
    for f in sorted(data_dir.glob("ch*.json")):
        ch_no = _extract_chapter_no(f.name)
        if ch_no > 0:
            data = load_json(f)
            if data:
                platform[ch_no] = data

    # 尝试汇总文件
    stats_file = data_dir / "platform_stats.json"
    if stats_file.exists():
        stats = load_json(stats_file)
        for key, val in stats.items():
            if isinstance(val, dict):
                ch_no = _extract_chapter_no(key) if not key.isdigit() else int(key)
                if ch_no > 0:
                    platform[ch_no] = val

    return platform


def _compute_trend(scores: List[float]) -> str:
    """根据最近半数章节的分数变化判断趋势。

    返回: "上升" / "平稳" / "下降"
    """
    if len(scores) < 2:
        return "平稳"

    mid = len(scores) // 2
    first_half = scores[:mid] if mid > 0 else scores[:1]
    second_half = scores[mid:]

    avg_first = sum(first_half) / len(first_half)
    avg_second = sum(second_half) / len(second_half)

    diff = avg_second - avg_first
    if diff > 0.3:
        return "上升"
    elif diff < -0.3:
        return "下降"
    else:
        return "平稳"


def _compute_score_trend_series(scores: List[float], window: int = 3) -> List[str]:
    """为每个章节计算局部趋势（滑动窗口）。"""
    trends: List[str] = []
    for i in range(len(scores)):
        start = max(0, i - window + 1)
        window_scores = scores[start:i + 1]
        if len(window_scores) < 2:
            trends.append("—")
        else:
            trends.append(_compute_trend(window_scores))
    return trends


def _frequency_counter(items: List[str], top_n: int = 10) -> List[Dict[str, Any]]:
    """统计列表中各元素出现频率，返回 top_n。"""
    counter = Counter(items)
    return [{"label": k, "count": v} for k, v in counter.most_common(top_n)]


def _philosophy_coverage(predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算哲学覆盖率。"""
    total = len(predictions)
    covered = 0
    alignment_dist: Counter = Counter()

    for rec in predictions:
        alignment = rec.get("philosophy_alignment", "")
        if alignment:
            covered += 1
            alignment_dist[alignment] += 1

    coverage_rate = covered / total if total > 0 else 0.0
    return {
        "total_chapters": total,
        "covered_chapters": covered,
        "coverage_rate": round(coverage_rate, 3),
        "alignment_distribution": dict(alignment_dist.most_common()),
    }


def _format_markdown_summary(
    predictions: List[Dict[str, Any]],
    platform: Dict[int, Dict[str, Any]],
    result: Dict[str, Any],
) -> str:
    """将 summary 结果格式化为 Markdown。"""
    lines: List[str] = []
    lines.append("# 📊 数据复盘摘要")
    lines.append("")
    lines.append(f"- **章节数**: {result['chapters']}")
    lines.append(f"- **自评均值**: {result['avg_score']}")
    lines.append(f"- **趋势**: {result['trend']}")
    lines.append(f"- **哲学覆盖率**: {result['philosophy_coverage']['coverage_rate'] * 100:.1f}%")
    lines.append(f"- **平台数据**: {'有' if platform else '无'}")
    lines.append("")

    # 强项
    if result.get("top_strengths"):
        lines.append("## 🌟 高频强项")
        for item in result["top_strengths"]:
            lines.append(f"- {item['label']} × {item['count']}")
        lines.append("")

    # 弱项
    if result.get("top_weaknesses"):
        lines.append("## ⚠️ 高频弱项")
        for item in result["top_weaknesses"]:
            lines.append(f"- {item['label']} × {item['count']}")
        lines.append("")

    # 哲学对齐分布
    alignment = result.get("philosophy_coverage", {}).get("alignment_distribution", {})
    if alignment:
        lines.append("## 🎯 哲学对齐分布")
        for k, v in alignment.items():
            lines.append(f"- {k}: {v} 章")
        lines.append("")

    # 章节明细
    lines.append("## 📋 章节明细")
    lines.append("")
    lines.append("| # | 章节 | 评分 | 强项 | 弱项 |")
    lines.append("|---|------|------|------|------|")
    for rec in predictions:
        ch_no = rec.get("chapter_no", "?")
        score = rec.get("score", "—")
        strengths = "; ".join(rec.get("strengths", [])[:2])
        weaknesses = "; ".join(rec.get("weaknesses", [])[:2])
        lines.append(f"| {ch_no} | ch{ch_no} | {score} | {strengths} | {weaknesses} |")
    lines.append("")

    return "\n".join(lines)


def _format_markdown_trend(
    trend_data: List[Dict[str, Any]],
    metrics: List[str],
) -> str:
    """将 trend 结果格式化为 Markdown。"""
    lines: List[str] = []
    lines.append("# 📈 时序趋势")
    lines.append("")

    metric_labels = {
        "score": "自评分",
        "read_rate": "阅读率",
        "completion_rate": "完读率",
    }

    for metric in metrics:
        label = metric_labels.get(metric, metric)
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| 章节 | 值 | 局部趋势 |")
        lines.append("|------|-----|----------|")
        for row in trend_data:
            ch_no = row.get("chapter_no", "?")
            val = row.get(metric, "—")
            local_trend = row.get(f"{metric}_trend", "—")
            lines.append(f"| ch{ch_no} | {val} | {local_trend} |")
        lines.append("")

    return "\n".join(lines)


# ── summary 子命令 ───────────────────────────────────────────

def cmd_summary(args: argparse.Namespace) -> None:
    """汇总统计摘要。"""
    project_root = Path(args.project_root).expanduser().resolve()

    # 加载数据
    predictions = _load_predictions(project_root, last_n=args.last_n)
    platform = _load_platform_data(project_root)

    if not predictions:
        print(json.dumps({
            "ok": True,
            "chapters": 0,
            "avg_score": 0,
            "trend": "无数据",
            "message": f"未在 {project_root / _PREDICTIONS_DIR} 找到自评数据",
        }, ensure_ascii=False, indent=2))
        return

    # 提取评分序列
    scores = [float(rec.get("score", 0)) for rec in predictions]
    valid_scores = [s for s in scores if _SCORE_MIN <= s <= _SCORE_MAX]
    avg_score = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else 0

    # 趋势
    trend = _compute_trend(valid_scores) if len(valid_scores) >= 2 else "平稳"

    # 强弱项频率
    all_strengths: List[str] = []
    all_weaknesses: List[str] = []
    for rec in predictions:
        all_strengths.extend(rec.get("strengths", []))
        all_weaknesses.extend(rec.get("weaknesses", []))

    top_strengths = _frequency_counter(all_strengths, top_n=10)
    top_weaknesses = _frequency_counter(all_weaknesses, top_n=10)

    # 哲学覆盖率
    philosophy_coverage = _philosophy_coverage(predictions)

    # 平台数据汇总
    platform_summary: Dict[str, Any] = {}
    if platform:
        platform_metrics: Dict[str, List[float]] = {}
        for ch_no, pdata in platform.items():
            for key, val in pdata.items():
                if isinstance(val, (int, float)):
                    platform_metrics.setdefault(key, []).append(float(val))
        for key, vals in platform_metrics.items():
            if vals:
                platform_summary[key] = {
                    "avg": round(sum(vals) / len(vals), 3),
                    "min": round(min(vals), 3),
                    "max": round(max(vals), 3),
                }

    # 构建结果
    result: Dict[str, Any] = {
        "ok": True,
        "chapters": len(predictions),
        "avg_score": avg_score,
        "min_score": min(valid_scores) if valid_scores else 0,
        "max_score": max(valid_scores) if valid_scores else 0,
        "trend": trend,
        "top_strengths": top_strengths,
        "top_weaknesses": top_weaknesses,
        "philosophy_coverage": philosophy_coverage,
        "platform_summary": platform_summary,
    }

    # JSON 输出
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Markdown 输出到 stderr
    md = _format_markdown_summary(predictions, platform, result)
    print("\n" + "=" * 60 + "\n" + md, file=sys.stderr)


# ── trend 子命令 ─────────────────────────────────────────────

def cmd_trend(args: argparse.Namespace) -> None:
    """输出时序趋势数据。"""
    project_root = Path(args.project_root).expanduser().resolve()

    # 加载数据
    predictions = _load_predictions(project_root)
    platform = _load_platform_data(project_root)

    if not predictions and not platform:
        print(json.dumps({
            "ok": True,
            "chapters": 0,
            "metrics": [],
            "data": [],
            "message": "未找到可用数据",
        }, ensure_ascii=False, indent=2))
        return

    # 确定需要输出的指标
    requested_metrics = [m.strip() for m in args.metric.split(",")] if args.metric else []
    if not requested_metrics:
        # 全部输出（根据可用数据自动确定）
        all_metrics = {"score"}
        if platform:
            for pdata in platform.values():
                for k, v in pdata.items():
                    if isinstance(v, (int, float)):
                        all_metrics.add(k)
        requested_metrics = sorted(all_metrics)

    # 收集所有章节号
    all_ch_nos = set()
    for rec in predictions:
        all_ch_nos.add(rec.get("chapter_no", 0))
    all_ch_nos.update(platform.keys())
    all_ch_nos.discard(0)

    sorted_ch_nos = sorted(all_ch_nos)

    # 构建时序数据
    trend_data: List[Dict[str, Any]] = []

    for ch_no in sorted_ch_nos:
        row: Dict[str, Any] = {"chapter_no": ch_no}

        # 自评数据
        pred_rec = next((r for r in predictions if r.get("chapter_no") == ch_no), None)
        if pred_rec and "score" in requested_metrics:
            row["score"] = pred_rec.get("score")

        # 平台数据
        if ch_no in platform:
            pdata = platform[ch_no]
            for metric in requested_metrics:
                if metric != "score" and metric in pdata:
                    row[metric] = pdata[metric]

        trend_data.append(row)

    # 计算局部趋势（滑动窗口）
    for metric in requested_metrics:
        values = [row.get(metric) for row in trend_data]
        valid_values = [float(v) for v in values if v is not None and v != "—"]
        if valid_values:
            trends = _compute_score_trend_series(valid_values, window=3)
            # 映射回 trend_data
            valid_idx = 0
            for i, row in enumerate(trend_data):
                if row.get(metric) is not None and row[metric] != "—":
                    row[f"{metric}_trend"] = trends[valid_idx]
                    valid_idx += 1
                else:
                    row[f"{metric}_trend"] = "—"

    # 构建结果
    result: Dict[str, Any] = {
        "ok": True,
        "chapters": len(sorted_ch_nos),
        "metrics": requested_metrics,
        "data": trend_data,
    }

    # JSON 输出
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Markdown 输出到 stderr
    md = _format_markdown_trend(trend_data, requested_metrics)
    print("\n" + "=" * 60 + "\n" + md, file=sys.stderr)


# ── argparse ─────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="数据复盘面板 — 汇总自评数据与平台数据，输出统计摘要与时序趋势",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # summary
    sp = sub.add_parser("summary", help="统计摘要（自评均值、趋势、强弱项频率、哲学覆盖率）")
    sp.add_argument("--project-root", required=True, help="小说项目根目录")
    sp.add_argument("--last-n", type=int, default=10, help="仅统计最近 N 章（默认 10，0=全部）")

    # trend
    sp = sub.add_parser("trend", help="时序趋势数据")
    sp.add_argument("--project-root", required=True, help="小说项目根目录")
    sp.add_argument(
        "--metric",
        default="",
        help="指标名称，逗号分隔（score/read_rate/completion_rate），默认全部",
    )

    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "summary":
        cmd_summary(args)
    elif args.command == "trend":
        cmd_trend(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
