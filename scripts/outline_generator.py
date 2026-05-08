#!/usr/bin/env python3
"""大纲生成与修订脚本。

子命令：
1. generate — 根据 philosophy.md / characters.md / motifs.md 生成 outline.md 模板
2. revise   — 读取伏笔追踪器检查伏笔断裂，生成版本化 outline_v{n}.md

注意：AI 生成逻辑由 Hermes LLM 负责，本脚本负责文件读写、伏笔检查、版本管理。
输出格式：JSON {"ok": true, ...} 与项目其他脚本保持一致。
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, load_json, read_text, save_json, write_text


# ── 配置常量 ──────────────────────────────────────────────────────────────────

# 知识库文件相对路径（相对于 project-root）
KB_PHILOSOPHY = "02_knowledge_base/philosophy.md"
KB_CHARACTERS = "02_knowledge_base/characters.md"
KB_MOTIFS     = "02_knowledge_base/motifs.md"

# 大纲文件相对路径
OUTLINE_FILE       = "02_knowledge_base/outline.md"
FORESHADOWING_FILE = "00_memory/foreshadowing_tracker.md"

# 伏笔 ID 正则：F{卷号}-{序号}
_FORESHADOW_ID_RE = re.compile(r"^F(\d+)-(\d+)$")


# ── 伏笔检查 ──────────────────────────────────────────────────────────────────

def _parse_foreshadowing_table(text: str) -> Dict[str, List[Dict[str, str]]]:
    """解析 foreshadowing_tracker.md 中的三个状态表格。

    Returns:
        {
            "urgent":  [{"id": "F1-001", "content": "...", ...}, ...],
            "active":  [...],
            "long":    [...],
        }
    """
    sections: Dict[str, List[Dict[str, str]]] = {
        "urgent": [],
        "active": [],
        "long": [],
    }

    current_section: Optional[str] = None
    header_cols: List[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        # 识别区块标题
        if "紧急回收" in stripped or ("🔴" in stripped and "紧急" in stripped):
            current_section = "urgent"
            header_cols = []
            continue
        elif "活跃伏笔" in stripped or ("🟡" in stripped and "活跃" in stripped):
            current_section = "active"
            header_cols = []
            continue
        elif "长线伏笔" in stripped or ("🟢" in stripped and "长线" in stripped):
            current_section = "long"
            header_cols = []
            continue
        elif "已回收" in stripped or "✅" in stripped:
            current_section = None  # 已回收的不检查
            header_cols = []
            continue

        # 解析表头
        if current_section and stripped.startswith("|") and "ID" in stripped:
            header_cols = [c.strip() for c in stripped.split("|")[1:-1]]
            continue

        # 解析表格数据行
        if current_section and header_cols and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if len(cells) >= 2 and cells[0] and not cells[0].startswith("---"):
                row = {header_cols[i]: cells[i] for i in range(min(len(header_cols), len(cells)))}
                sections[current_section].append(row)

    return sections


def check_foreshadowing(
    project_root: Path,
    current_volumes: int,
) -> Dict[str, Any]:
    """检查伏笔追踪器中的伏笔是否与当前卷结构匹配。

    Returns:
        {
            "ok": true/false,
            "broken": [...],   # 断裂的伏笔列表
            "total_checked": N,
        }
    """
    tracker_path = project_root / FORESHADOWING_FILE
    if not tracker_path.exists():
        return {"ok": True, "broken": [], "total_checked": 0, "note": "foreshadowing_tracker.md 不存在，跳过检查"}

    text = read_text(tracker_path)
    sections = _parse_foreshadowing_table(text)

    broken: List[Dict[str, str]] = []
    total = 0

    # 检查所有活跃伏笔（urgent + active）
    for status in ("urgent", "active", "long"):
        for row in sections.get(status, []):
            total += 1
            fid = row.get("ID", "")
            m = _FORESHADOW_ID_RE.match(fid)
            if not m:
                continue

            vol_num = int(m.group(1))

            # 伏笔所属卷号超过当前卷结构 → 断裂
            if vol_num > current_volumes:
                broken.append({
                    "id": fid,
                    "content": row.get("伏笔内容", row.get("content", "")),
                    "issue": f"伏笔 ID 卷号 {vol_num} 超出当前总卷数 {current_volumes}",
                    "status": status,
                })

    return {
        "ok": len(broken) == 0,
        "broken": broken,
        "total_checked": total,
    }


# ── generate 子命令 ──────────────────────────────────────────────────────────

def _read_knowledge_base(project_root: Path) -> Dict[str, str]:
    """读取哲学内核、人物设定、母题计划三份文件。"""
    return {
        "philosophy": read_text(project_root / KB_PHILOSOPHY, "(文件不存在)"),
        "characters": read_text(project_root / KB_CHARACTERS, "(文件不存在)"),
        "motifs":     read_text(project_root / KB_MOTIFS, "(文件不存在)"),
    }


def _generate_outline_template(
    volumes: int,
    chapters_per_volume: int,
    kb: Dict[str, str],
) -> Tuple[str, List[Dict[str, Any]]]:
    """生成 outline.md 模板内容。

    返回：
        (markdown_text, volume_list)
        volume_list 结构：[{"volume": 1, "title": "第一卷", "chapter_range": [1, 120], ...}]
    """
    cn_nums = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
               "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十"]

    lines: List[str] = [
        "# 大纲",
        "",
        "> **定位：** 本书的情节结构——卷结构，每卷的核心冲突和转折。",
        "> **生成时间：** " + dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "> **卷数：** " + str(volumes),
        "> **每卷章数：** " + str(chapters_per_volume),
        "",
        "## 全书结构",
        "",
    ]

    volume_list: List[Dict[str, Any]] = []

    for i in range(1, volumes + 1):
        start_ch = (i - 1) * chapters_per_volume + 1
        end_ch   = i * chapters_per_volume
        cn_label = cn_nums[i] if i < len(cn_nums) else str(i)

        vol_entry = {
            "volume": i,
            "title": f"第{cn_label}卷",
            "chapter_range": [start_ch, end_ch],
            "core_conflict": "（待填充）",
            "philosophical_sub_theme": "（待填充）",
            "key_nodes": [],
        }
        volume_list.append(vol_entry)

        lines.extend([
            f"## 第{cn_label}卷（第{start_ch}-{end_ch}章）",
            "",
            "### 核心冲突",
            "（待填充——请根据 philosophy.md 中的子命题设计）",
            "",
            "### 哲学子命题",
            "（待填充——对应 philosophy.md 每卷子命题表格）",
            "",
            "### 关键节点",
            "| 章节 | 事件 | 意象 | 伏笔 |",
            "|------|------|------|------|",
            "| （待填充） | | | |",
            "",
        ])

    # 附加来源摘要
    lines.extend([
        "---",
        "",
        "## 参考来源摘要",
        "",
        "### 哲学内核",
        "```",
        kb["philosophy"][:2000] if kb["philosophy"] != "(文件不存在)" else kb["philosophy"],
        "```",
        "",
        "### 人物设定",
        "```",
        kb["characters"][:2000] if kb["characters"] != "(文件不存在)" else kb["characters"],
        "```",
        "",
        "### 母题计划",
        "```",
        kb["motifs"][:2000] if kb["motifs"] != "(文件不存在)" else kb["motifs"],
        "```",
    ])

    return "\n".join(lines) + "\n", volume_list


def cmd_generate(args: argparse.Namespace) -> Dict[str, Any]:
    """generate 子命令：生成大纲模板。"""
    project_root = Path(args.project_root).resolve()
    volumes = args.volumes
    chapters_per_volume = args.chapters_per_volume

    if not project_root.exists():
        return {"ok": False, "error": f"项目目录不存在: {project_root}"}

    # 读取知识库
    kb = _read_knowledge_base(project_root)

    # 生成大纲模板
    outline_md, volume_list = _generate_outline_template(
        volumes=volumes,
        chapters_per_volume=chapters_per_volume,
        kb=kb,
    )

    # 写入文件
    outline_path = project_root / OUTLINE_FILE
    ensure_dir(outline_path.parent)
    if not write_text(outline_path, outline_md):
        return {"ok": False, "error": f"写入大纲文件失败: {outline_path}"}

    return {
        "ok": True,
        "outline_file": str(outline_path),
        "volumes": volume_list,
        "volumes_count": len(volume_list),
        "chapters_per_volume": chapters_per_volume,
        "total_chapters": volumes * chapters_per_volume,
    }


# ── revise 子命令 ────────────────────────────────────────────────────────────

def _find_latest_outline_version(project_root: Path) -> int:
    """查找当前大纲的最大版本号。outline.md → 0，outline_v1.md → 1，以此类推。"""
    outline_dir = project_root / OUTLINE_FILE.rsplit("/", 1)[0] if "/" in OUTLINE_FILE else project_root / "02_knowledge_base"
    version = 0

    if outline_dir.exists():
        for f in outline_dir.iterdir():
            m = re.match(r"outline_v(\d+)\.md$", f.name)
            if m:
                ver = int(m.group(1))
                if ver > version:
                    version = ver

    return version


def _read_current_outline(project_root: Path) -> str:
    """读取当前大纲文件内容（优先读最新版本）。"""
    kb_dir = project_root / "02_knowledge_base"
    latest_ver = _find_latest_outline_version(project_root)

    if latest_ver > 0:
        path = kb_dir / f"outline_v{latest_ver}.md"
        if path.exists():
            return read_text(path)

    # 无版本化文件时读 outline.md
    path = kb_dir / "outline.md"
    if path.exists():
        return read_text(path)

    return ""


def cmd_revise(args: argparse.Namespace) -> Dict[str, Any]:
    """revise 子命令：检查伏笔断裂 + 生成版本化大纲。"""
    project_root = Path(args.project_root).resolve()
    changes = (args.changes or "").strip()
    check_foreshadow = args.check_foreshadowing

    if not project_root.exists():
        return {"ok": False, "error": f"项目目录不存在: {project_root}"}

    kb_dir = project_root / "02_knowledge_base"
    ensure_dir(kb_dir)

    # Step 1: 确定新版本号
    latest_version = _find_latest_outline_version(project_root)
    new_version = latest_version + 1

    # Step 2: 伏笔检查
    foreshadow_result: Optional[Dict[str, Any]] = None
    if check_foreshadow:
        # 从当前大纲推断卷数（基于 outline 模板的章节范围）
        current_outline = _read_current_outline(project_root)
        volumes_count = current_outline.count("## 第")  # 粗略计数
        if volumes_count == 0:
            volumes_count = 3  # 默认值

        foreshadow_result = check_foreshadowing(project_root, volumes_count)

    # Step 3: 备份当前大纲
    backup_info: Optional[str] = None
    current_path = kb_dir / "outline.md"
    if current_path.exists():
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = project_root / ".flow" / "outline_backups"
        ensure_dir(backup_dir)
        backup_path = backup_dir / f"outline_backup_{ts}.md"
        import shutil
        shutil.copy2(str(current_path), str(backup_path))
        backup_info = str(backup_path)

    # Step 4: 生成版本化大纲文件名
    new_outline_path = kb_dir / f"outline_v{new_version}.md"

    # Step 5: 读取当前大纲并添加版本头
    current_content = _read_current_outline(project_root)
    if not current_content:
        current_content = "# 大纲\n\n（待生成）\n"

    version_header = (
        f"---\n"
        f"版本: v{new_version}\n"
        f"变更时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"变更说明: {changes or '（未提供说明）'}\n"
        f"前一版本: v{latest_version}\n"
        f"---\n\n"
    )

    new_content = version_header + current_content

    if not write_text(new_outline_path, new_content):
        return {"ok": False, "error": f"写入版本化大纲失败: {new_outline_path}"}

    # Step 6: 构建输出
    result: Dict[str, Any] = {
        "ok": True,
        "outline_file": str(new_outline_path),
        "version": new_version,
        "previous_version": latest_version,
        "changes": changes,
        "backup_file": backup_info,
        "volumes": [],  # 由 LLM 后续填充
    }

    if foreshadow_result is not None:
        result["foreshadow_check"] = foreshadow_result
        if not foreshadow_result["ok"]:
            result["warning"] = (
                f"发现 {len(foreshadow_result['broken'])} 个伏笔断裂，请检查伏笔追踪器。"
            )

    return result


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outline_generator",
        description="大纲生成与修订脚本",
    )
    sub = parser.add_subparsers(dest="subcommand", help="子命令")

    # generate 子命令
    p_gen = sub.add_parser("generate", help="根据知识库生成大纲模板")
    p_gen.add_argument("--project-root", required=True, help="小说项目根目录")
    p_gen.add_argument("--volumes", type=int, default=3, help="卷数（默认 3）")
    p_gen.add_argument(
        "--chapters-per-volume", type=int, default=120,
        help="每卷章节数（默认 120）",
    )

    # revise 子命令
    p_rev = sub.add_parser("revise", help="修订大纲，检查伏笔断裂，生成版本化文件")
    p_rev.add_argument("--project-root", required=True, help="小说项目根目录")
    p_rev.add_argument("--changes", default="", help="变更说明")
    p_rev.add_argument(
        "--check-foreshadowing",
        type=lambda v: v.lower() in ("true", "1", "yes"),
        default=True,
        help="是否检查伏笔断裂（默认 true）",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    if args.subcommand == "generate":
        result = cmd_generate(args)
    elif args.subcommand == "revise":
        result = cmd_revise(args)
    else:
        result = {"ok": False, "error": f"未知子命令: {args.subcommand}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
