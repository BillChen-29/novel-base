#!/usr/bin/env python3
from __future__ import annotations
"""碎片想法结构化填充脚本。

将用户模糊的碎片想法（一句话 / 几个关键词）写入目标配置文件的模板占位符。
脚本负责：
  1. 定位目标文件（若不存在则从模板复制）
  2. 读取模板结构，保留注释占位符
  3. 将 --input 映射到最合适的占位字段
  4. 写入结构化 markdown

AI 填充逻辑由 Hermes 的 LLM 负责，本脚本只负责模板读取和文件写入。

子命令:
  philosophy          → projects/<proj>/philosophy.md
  characters          → projects/<proj>/characters.md
  motifs              → projects/<proj>/motifs.md
  world               → projects/<proj>/world.md
  world_texture       → projects/<proj>/world_texture.md
  style_anchor        → projects/<proj>/00_memory/style_anchor.md
  character_archetypes → projects/<proj>/character_archetypes_local.md
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, read_text, write_text

# ── 路径映射 ──────────────────────────────────────────────────────

CONFIG_PATH_MAP: dict[str, str] = {
    "philosophy": "philosophy.md",
    "characters": "characters.md",
    "motifs": "motifs.md",
    "world": "world.md",
    "world_texture": "world_texture.md",
    "style_anchor": "00_memory/style_anchor.md",
    "character_archetypes": "character_archetypes_local.md",
}

# 模板目录（项目根目录的上级级 templates/）
TEMPLATE_DIR = SCRIPT_DIR.parent / "templates"

# 子命令 → 模板文件名
TEMPLATE_MAP: dict[str, str] = {
    "philosophy": "philosophy.template.md",
    "characters": "characters.template.md",
    "motifs": "motifs.template.md",
    "world": "world.template.md",
    "world_texture": "world_texture.template.md",
    "style_anchor": "style_anchor.template.md",
    "character_archetypes": "character_archetypes_local.template.md",
}

# ── 占位符模式 ────────────────────────────────────────────────────

# 匹配占位标记（三种格式）:
#   1. （待填充）或含待填充的中文括号  2. （待定）  3. {PLACEHOLDER}
_PLACEHOLDER_RE = re.compile(
    r"（[^）]*待填充[^）]*）"  # 含"待填充"的括号内容
    r"|（[^）]*待定[^）]*）"   # 含"待定"的括号内容
    r"|\{[A-Z_]+\}"          # {PLACEHOLDER} 格式
)

# 匹配空表格行 "| xxx |  |  |" 或 "| xxx | 待定 |"
_EMPTY_TABLE_RE = re.compile(r"^\|(.*?)(?:\| *（?待(?:填充|定)）? *|(?:\| *)*)\|$")


def _find_placeholders(content: str) -> list[tuple[int, str]]:
    """提取模板中所有占位符的位置和内容。

    Returns:
        [(line_no, placeholder_text), ...]  1-indexed line numbers
    """
    results: list[tuple[int, str]] = []
    for i, line in enumerate(content.splitlines(), start=1):
        for m in _PLACEHOLDER_RE.finditer(line):
            results.append((i, m.group()))
    return results


def _extract_first_section(content: str) -> str | None:
    """从模板中提取第一个 '## xxx' 标题下的内容（到下一个 ## 或 EOF）。"""
    lines = content.splitlines()
    capture = False
    section_lines: list[str] = []
    for line in lines:
        if re.match(r"^## ", line):
            if capture:
                break
            capture = True
        if capture:
            section_lines.append(line)
    return "\n".join(section_lines) if section_lines else None


def _extract_tables(content: str) -> list[str]:
    """提取模板中所有 markdown 表格结构（标题行 + 分隔行 + 示例数据行）。"""
    lines = content.splitlines()
    tables: list[str] = []
    in_table = False
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and "|" in stripped[1:]:
            in_table = True
            buf.append(line)
        else:
            if in_table and buf:
                tables.append("\n".join(buf))
                buf = []
            in_table = False
    if buf:
        tables.append("\n".join(buf))
    return tables


# ── 模板初始化 ────────────────────────────────────────────────────


def _ensure_target_file(project_root: Path, config_type: str) -> Path:
    """确保目标配置文件存在。若不存在，从模板复制。"""
    rel = CONFIG_PATH_MAP[config_type]
    target = project_root / rel

    if target.exists():
        return target

    # 尝试从模板复制
    tpl_name = TEMPLATE_MAP.get(config_type)
    tpl_path = TEMPLATE_DIR / tpl_name if tpl_name else None

    if tpl_path and tpl_path.exists():
        ensure_dir(target.parent)
        # 复制模板，替换项目特定的占位符
        tpl_content = read_text(tpl_path)
        write_text(target, tpl_content)
        print(f"[INFO] 从模板创建 {target}", file=sys.stderr)
    else:
        # 无模板可用，创建最小骨架
        ensure_dir(target.parent)
        write_text(target, f"# {config_type}\n\n（待填充）\n")
        print(f"[INFO] 创建空骨架 {target}", file=sys.stderr)

    return target


# ── 核心填充逻辑 ──────────────────────────────────────────────────


def _fill_content(content: str, user_input: str, config_type: str) -> str:
    """将用户碎片想法填充到模板结构中。

    策略（按优先级）：
    1. 找到含 '待填充' 的中文括号占位符 → 替换整个匹配
    2. 找到含 '待定' 的中文括号占位符 → 替换整个匹配
    3. 找到 '{PLACEHOLDER}' 占位符 → 替换第一个
    4. 都没有 → 追加到文件末尾

    后续占位符保留，等待 AI 逐个填充。
    """
    lines = content.splitlines()
    filled = False
    result: list[str] = []

    for line in lines:
        if not filled:
            m = _PLACEHOLDER_RE.search(line)
            if m:
                result.append(line[:m.start()] + user_input + line[m.end():])
                filled = True
                continue
        result.append(line)

    # 如果模板里没有标准占位符，追加到文件末尾
    if not filled:
        result.append("")
        result.append("<!-- 用户碎片想法 -->")
        result.append(f"{user_input}")
        result.append("")

    return "\n".join(result) + "\n"


def _build_preview(content: str, max_len: int = 100) -> str:
    """返回内容的前 max_len 个字符作为预览。"""
    text = content.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


# ── 子命令处理 ────────────────────────────────────────────────────


def _handle_fill(project_root: Path, config_type: str, user_input: str) -> dict:
    """通用填充入口。

    Returns:
        {"ok": bool, "file": str, "preview": str, "config_type": str}
    """
    try:
        target = _ensure_target_file(project_root, config_type)
        content = read_text(target)

        # 执行填充
        new_content = _fill_content(content, user_input, config_type)

        # 写入
        ok = write_text(target, new_content)

        return {
            "ok": ok,
            "file": str(target),
            "preview": _build_preview(new_content),
            "config_type": config_type,
        }
    except Exception as exc:
        return {
            "ok": False,
            "file": str(project_root / CONFIG_PATH_MAP.get(config_type, "?")),
            "error": repr(exc),
            "config_type": config_type,
        }


# ── CLI ───────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="碎片想法结构化填充脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 fill_config.py philosophy --project-root /path/to/proj "
            '--input "这本书探讨的是自由意志与命运的对抗"\n'
            "  python3 fill_config.py characters --project-root /path/to/proj "
            '--input "主角是一个失忆的剑客，沉默寡言但心地善良"\n'
        ),
    )
    sub = p.add_subparsers(dest="config_type", required=True)

    for cmd_name in CONFIG_PATH_MAP:
        help_text = f"填充 {cmd_name} 配置文件"
        s = sub.add_parser(cmd_name, help=help_text)
        s.add_argument("--project-root", required=True, help="项目目录路径")
        s.add_argument("--input", required=True, help="用户的碎片想法")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(json.dumps({
            "ok": False,
            "error": f"项目目录不存在: {project_root}",
        }, ensure_ascii=False, indent=2))
        return 1

    payload = _handle_fill(project_root, args.config_type, args.input)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
