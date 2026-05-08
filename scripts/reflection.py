#!/usr/bin/env python3
"""灵感记录脚本 — 管理创作过程中的灵感、反思与备忘。

子命令：
  new     — 创建一条新的灵感记录
  list    — 按时间倒序列出灵感记录
  search  — 全文搜索灵感记录内容

所有子命令输出 JSON，格式: {"ok": true/false, ...}
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# 脚本目录 & common 模块
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, read_text  # noqa: E402

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

REFLECTIONS_DIR = Path("00_memory") / "reflections"


def _reflections_path(project_root: Path) -> Path:
    return project_root / REFLECTIONS_DIR


def _parse_ts_from_filename(name: str) -> dt.datetime:
    """从文件名 YYYY-MM-DD_HHMMSS.md 中提取时间戳。"""
    stem = Path(name).stem
    try:
        return dt.datetime.strptime(stem, "%Y-%m-%d_%H%M%S")
    except ValueError:
        return dt.datetime.min


def _build_markdown(content: str, tags: List[str], chapter_ref: str) -> str:
    """构建反思笔记的 Markdown 正文。"""
    lines: List[str] = []
    lines.append("---")
    lines.append(f"created: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if tags:
        lines.append(f"tags: {', '.join(tags)}")
    if chapter_ref:
        lines.append(f"chapter_ref: {chapter_ref}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines) + "\n"


# ===========================================================================
# 子命令: new
# ===========================================================================


def cmd_new(project_root: Path, content: str, tags: List[str],
            chapter_ref: str) -> None:
    """创建一条新的灵感记录。"""
    ref_dir = _reflections_path(project_root)
    ensure_dir(ref_dir)

    ts = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{ts}.md"
    filepath = ref_dir / filename

    md = _build_markdown(content, tags, chapter_ref)
    filepath.write_text(md, encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "file": str(filepath),
    }, ensure_ascii=False, indent=2))


# ===========================================================================
# 子命令: list
# ===========================================================================


def cmd_list(project_root: Path, last_n: int) -> None:
    """列出所有灵感笔记，按时间倒序。"""
    ref_dir = _reflections_path(project_root)

    if not ref_dir.exists():
        print(json.dumps({"ok": True, "items": [], "count": 0},
                          ensure_ascii=False, indent=2))
        return

    files = sorted(ref_dir.glob("*.md"), reverse=True)
    items: List[Dict[str, Any]] = []
    for fp in files[:last_n]:
        text = read_text(fp, "")
        # 提取 YAML front-matter 中的 tags / chapter_ref
        tags: List[str] = []
        chapter_ref = ""
        m = re.search(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if m:
            for line in m.group(1).splitlines():
                if line.startswith("tags:"):
                    tags = [t.strip() for t in line.split(":", 1)[1].split(",") if t.strip()]
                elif line.startswith("chapter_ref:"):
                    chapter_ref = line.split(":", 1)[1].strip()
        items.append({
            "file": str(fp.name),
            "path": str(fp),
            "created": _parse_ts_from_filename(fp.name).isoformat(),
            "tags": tags,
            "chapter_ref": chapter_ref,
        })

    print(json.dumps({
        "ok": True,
        "items": items,
        "count": len(items),
    }, ensure_ascii=False, indent=2))


# ===========================================================================
# 子命令: search
# ===========================================================================


def cmd_search(project_root: Path, query: str) -> None:
    """全文搜索灵感记录。"""
    ref_dir = _reflections_path(project_root)

    if not ref_dir.exists():
        print(json.dumps({"ok": True, "items": [], "count": 0},
                          ensure_ascii=False, indent=2))
        return

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    hits: List[Dict[str, Any]] = []

    for fp in sorted(ref_dir.glob("*.md"), reverse=True):
        text = read_text(fp, "")
        if pattern.search(text):
            # 提取匹配行的摘要
            snippets: List[str] = []
            for line in text.splitlines():
                if pattern.search(line):
                    snippets.append(line.strip())
                    if len(snippets) >= 3:
                        break
            hits.append({
                "file": str(fp.name),
                "path": str(fp),
                "snippets": snippets,
            })

    print(json.dumps({
        "ok": True,
        "items": hits,
        "count": len(hits),
    }, ensure_ascii=False, indent=2))


# ===========================================================================
# CLI
# ===========================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="灵感记录管理工具 — 记录创作过程中的灵感与反思",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- new --
    p_new = sub.add_parser("new", help="创建一条新的灵感记录")
    p_new.add_argument("--project-root", required=True, help="项目根目录")
    p_new.add_argument("--content", required=True, help="灵感/反思内容")
    p_new.add_argument("--tags", default="", help="标签，逗号分隔（可选）")
    p_new.add_argument("--chapter-ref", default="", help="关联章节编号（可选）")

    # -- list --
    p_list = sub.add_parser("list", help="按时间倒序列出灵感记录")
    p_list.add_argument("--project-root", required=True, help="项目根目录")
    p_list.add_argument("--last-n", type=int, default=20, help="显示最近 N 条（默认 20）")

    # -- search --
    p_search = sub.add_parser("search", help="全文搜索灵感记录")
    p_search.add_argument("--project-root", required=True, help="项目根目录")
    p_search.add_argument("--query", required=True, help="搜索关键词")

    args = parser.parse_args()
    pr = Path(args.project_root).expanduser().resolve()

    if args.command == "new":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        cmd_new(pr, args.content, tags, args.chapter_ref)

    elif args.command == "list":
        cmd_list(pr, args.last_n)

    elif args.command == "search":
        cmd_search(pr, args.query)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
