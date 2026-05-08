#!/usr/bin/env python3
from __future__ import annotations
"""主观评估脚本 — 从哲学维度自评章节质量。

start: 读取章节 + philosophy.md，生成评估表单提示（3 个哲学问题 + 评分表单）。
submit: 写入 04_predictions/ch{N}.json 供后续交叉比对。
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# ── 确保同目录脚本可直接 import ──────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from common import slugify  # noqa: E402


# ── helpers ─────────────────────────────────────────────────

def _extract_chapter_number(chapter_id: str) -> int:
    m = re.search(r"(\d+)", chapter_id)
    return int(m.group(1)) if m else 0


def _read_file(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, PermissionError):
        return default


def _find_philosophy(project_root: Path) -> Path:
    """在项目根目录查找 philosophy.md。"""
    candidates = [
        project_root / "02_knowledge_base" / "philosophy.md",
        project_root / "philosophy.md",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[-1]  # 返回备用路径


def _find_chapter_file(project_root: Path, chapter_id: str) -> Path | None:
    """在 03_manuscript/ 下按章节号查找章节文件。"""
    chapter_no = _extract_chapter_number(chapter_id)
    if chapter_no == 0:
        return None
    ms_dir = project_root / "03_manuscript"
    if not ms_dir.exists():
        return None
    pattern = re.compile(rf"^第{chapter_no}章.*\.md$")
    for f in sorted(ms_dir.iterdir()):
        if f.is_file() and pattern.match(f.name):
            return f
    return None


def _build_philosophy_questions(philosophy_text: str) -> List[str]:
    """从 philosophy.md 提取 3 个追问问题，若文件为空则使用内置默认。"""
    defaults = [
        "本章是否推进了全书的核心命题？",
        "角色的行为是否符合/挑战了本书的哲学立场？",
        "读者在阅读本章后，是否对书中追问的问题有了新的思考？",
    ]
    # 尝试从 markdown 的有序列表中提取
    questions: List[str] = []
    for line in philosophy_text.splitlines():
        m = re.match(r"^\d+\.\s+(.+)$", line.strip())
        if m:
            q = m.group(1).strip()
            if q and "待填充" not in q:
                questions.append(q)
    return questions[:3] if len(questions) >= 3 else defaults


# ── start 子命令 ───────────────────────────────────────────

def cmd_start(args: argparse.Namespace) -> None:
    project_root = Path(args.project_root).expanduser().resolve()
    chapter_id = slugify(args.chapter_id) if args.chapter_id else ""

    # 确定章节文件
    if args.chapter_file:
        ch_path = Path(args.chapter_file)
        if not ch_path.is_absolute():
            ch_path = project_root / ch_path
        ch_path = ch_path.resolve()
        if not chapter_id:
            chapter_id = slugify(ch_path.stem)
    else:
        ch_path = _find_chapter_file(project_root, chapter_id)
        if ch_path is None:
            print(json.dumps({"ok": False, "error": f"未找到章节 {chapter_id} 对应文件"}, ensure_ascii=False))
            return

    # 读取内容
    chapter_text = _read_file(ch_path, "")
    philosophy_path = _find_philosophy(project_root)
    philosophy_text = _read_file(philosophy_path, "")

    # 解析哲学问题
    questions = _build_philosophy_questions(philosophy_text)

    # 提取核心命题
    core_proposition = ""
    in_section = False
    for line in philosophy_text.splitlines():
        if "## 核心命题" in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("##"):
                break
            stripped = line.strip()
            if stripped and stripped != "（待填充）":
                core_proposition += stripped + "\n"
    core_proposition = core_proposition.strip() or "（未填写）"

    # 提取追问问题
    questions_block = "\n".join(f"  {i + 1}. {q}" for i, q in enumerate(questions))

    # 输出评估表单提示
    output = {
        "chapter_id": chapter_id,
        "chapter_file": str(ch_path),
        "chapter_length": len(chapter_text),
        "philosophy_file": str(philosophy_path),
        "core_proposition": core_proposition,
        "evaluation_prompt": (
            f"请对章节《{chapter_id}》进行主观评估。\n\n"
            f"【哲学内核】\n{core_proposition or '（未填写）'}\n\n"
            f"【本章追问（3 个哲学问题）】\n{questions_block}\n\n"
            "请围绕以上 3 个问题评估本章，并给出 1-5 分评分。\n"
            "评分标准：\n"
            "  1 = 严重偏离 / 无关联\n"
            "  2 = 勉强相关，但处理粗糙\n"
            "  3 = 基本契合，有提升空间\n"
            "  4 = 紧密呼应，处理精到\n"
            "  5 = 完美融合，升华了主题\n\n"
            "请按以下格式提交 submit:\n"
            f"  --chapter-id {chapter_id}\n"
            "  --score <1-5>\n"
            "  --strengths \"<优点描述>\"\n"
            "  --weaknesses \"<不足描述>\"\n"
            "  --mindset \"<创作时的思维状态>\"\n"
        ),
        "chapter_preview": chapter_text[:500] + ("..." if len(chapter_text) > 500 else ""),
        "ok": True,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ── submit 子命令 ──────────────────────────────────────────

def cmd_submit(args: argparse.Namespace) -> None:
    project_root = Path(args.project_root).expanduser().resolve()
    chapter_id = slugify(args.chapter_id)
    chapter_no = _extract_chapter_number(chapter_id)

    # 校验分数
    score = int(args.score)
    if score < 1 or score > 5:
        print(json.dumps({"ok": False, "error": "score 必须在 1-5 之间"}, ensure_ascii=False))
        return

    # 读取哲学文件，计算 alignment
    philosophy_path = _find_philosophy(project_root)
    philosophy_text = _read_file(philosophy_path, "")
    questions = _build_philosophy_questions(philosophy_text)

    # 根据评分计算哲学对齐度
    alignment_map = {
        1: "严重偏离",
        2: "勉强相关",
        3: "基本契合",
        4: "紧密呼应",
        5: "完美融合",
    }
    philosophy_alignment = alignment_map.get(score, "未知")

    # 构造 JSON
    record: Dict[str, Any] = {
        "chapter_id": chapter_id,
        "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "score": score,
        "strengths": [s.strip() for s in args.strengths.split(";") if s.strip()] if args.strengths else [],
        "weaknesses": [w.strip() for w in args.weaknesses.split(";") if w.strip()] if args.weaknesses else [],
        "mindset": args.mindset or "",
        "philosophy_alignment": philosophy_alignment,
        "philosophy_questions": questions,
    }

    # 写入 04_predictions/
    out_dir = project_root / "04_predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ch{chapter_no}.json"
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "file": str(out_path)}, ensure_ascii=False))


# ── argparse ────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="主观评估脚本 — 从哲学维度自评章节质量")
    sub = p.add_subparsers(dest="command", required=True)

    # start
    sp = sub.add_parser("start", help="生成评估表单提示")
    sp.add_argument("--project-root", required=True, help="小说项目根目录")
    sp.add_argument("--chapter-file", default="", help="章节文件路径（可选，若不提供则按 chapter-id 自动查找）")
    sp.add_argument("--chapter-id", default="", help="章节标识（如 ch01）")

    # submit
    sp = sub.add_parser("submit", help="提交评估结果")
    sp.add_argument("--project-root", required=True, help="小说项目根目录")
    sp.add_argument("--chapter-id", required=True, help="章节标识（如 ch01）")
    sp.add_argument("--score", required=True, type=int, help="评分 1-5")
    sp.add_argument("--strengths", default="", help='优点，分号分隔；如 "主题契合;人物鲜明"')
    sp.add_argument("--weaknesses", default="", help='不足，分号分隔；如 "节奏偏慢"')
    sp.add_argument("--mindset", default="", help="创作时的思维状态描述")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "start":
        cmd_start(args)
    elif args.command == "submit":
        cmd_submit(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
