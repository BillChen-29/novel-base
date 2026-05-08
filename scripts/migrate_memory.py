#!/usr/bin/env python3
"""
迁移脚本：将 00_memory/*.md 转为 00_memory/truth/*.json

用法：
    python3 migrate_memory.py --project-root <dir> [--force]

错误处理：
    - 解析失败 → 跳过
    - 无匹配 schema → 跳过
    - 已有 truth 目录且未传 --force → 中止
    - 项目没有 00_memory/ 目录 → 创建空目录 + 从 templates/truth/ 复制空模板
"""

from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

# 确保脚本所在目录在 sys.path 中，以便导入 schemas / truth_manager
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import schemas  # noqa: E402
from truth_manager import ensure_truth_dir, get_truth_dir, get_truth_path  # noqa: E402


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _schema_name_from_filename(md_filename: str) -> str:
    """从 .md 文件名推断 schema 名称（去掉后缀、转下划线、小写）"""
    stem = Path(md_filename).stem
    return stem.replace("-", "_").lower()


def _copy_empty_templates(project_root: str) -> dict:
    """从 templates/truth/ 复制空 JSON 模板到项目的 00_memory/truth/"""
    result = {"success": [], "errors": []}
    truth_dir = ensure_truth_dir(project_root)

    template_dir = _SCRIPT_DIR.parent / "templates" / "truth"
    if not template_dir.exists():
        result["errors"].append(f"模板目录不存在: {template_dir}")
        return result

    for template_file in template_dir.glob("*.json"):
        target = truth_dir / template_file.name
        if not target.exists():
            try:
                shutil.copy2(template_file, target)
                result["success"].append(template_file.name)
            except OSError as e:
                result["errors"].append(f"复制 {template_file.name} 失败: {e}")

    return result


# ---------------------------------------------------------------------------
# 主迁移逻辑
# ---------------------------------------------------------------------------

def migrate(project_root: str, force: bool = False) -> dict:
    """
    执行迁移。

    Returns:
        {"success": [...], "skipped": [...], "errors": [...]}
    """
    result: dict[str, list] = {"success": [], "skipped": [], "errors": []}
    memory_dir = Path(project_root) / "00_memory"
    truth_dir = get_truth_dir(project_root)

    # ---- 1. 处理 00_memory/ 目录不存在的情况 ----
    if not memory_dir.exists():
        memory_dir.mkdir(parents=True, exist_ok=True)
        print(f"[info] 00_memory/ 目录不存在，已创建: {memory_dir}")
        # 复制空模板
        tpl_result = _copy_empty_templates(project_root)
        if tpl_result["success"]:
            print(f"[info] 已复制 {len(tpl_result['success'])} 个空模板到 truth/")
            result["success"].extend(tpl_result["success"])
        if tpl_result["errors"]:
            result["errors"].extend(tpl_result["errors"])
        result["skipped"].append("没有找到 markdown 文件（目录刚创建）")
        return result

    # ---- 2. 检查 truth 目录是否已存在 ----
    if truth_dir.exists() and not force:
        result["skipped"].append(
            f"truth 目录已存在: {truth_dir}，使用 --force 覆盖"
        )
        return result

    # ---- 3. 确保 truth 目录存在 ----
    ensure_truth_dir(project_root)

    # ---- 4. 遍历 markdown 文件 ----
    md_files = sorted(memory_dir.glob("*.md"))
    if not md_files:
        result["skipped"].append("没有找到 markdown 文件")
        return result

    for md_file in md_files:
        file_name = md_file.name
        schema_name = _schema_name_from_filename(file_name)

        # 4a. 查找匹配的 schema
        schema_cls = schemas.get_schema(schema_name)
        if not schema_cls:
            result["skipped"].append(f"跳过 {file_name}（无匹配 schema）")
            continue

        # 4b. 读取 markdown
        try:
            md_content = md_file.read_text(encoding="utf-8")
        except OSError as e:
            result["errors"].append(f"读取 {file_name} 失败: {e}")
            continue

        # 4c. 解析为 dict
        try:
            data = schema_cls.from_markdown(md_content)
        except Exception as e:
            result["errors"].append(f"解析 {file_name} 失败: {e}")
            continue

        # 4d. 校验
        valid, validation_errors = schema_cls.validate(data)
        if not valid:
            result["errors"].append(f"校验 {file_name} 失败: {validation_errors}")
            continue

        # 4e. 保存 JSON
        json_path = truth_dir / f"{schema_name}.json"
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            result["success"].append(f"{file_name} → {schema_name}.json")
        except OSError as e:
            result["errors"].append(f"写入 {schema_name}.json 失败: {e}")

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="将 00_memory/*.md 迁移为 00_memory/truth/*.json"
    )
    parser.add_argument(
        "--project-root", required=True,
        help="小说项目根目录路径"
    )
    parser.add_argument(
        "--force", action="store_true", default=False,
        help="强制覆盖已存在的 truth 目录"
    )
    args = parser.parse_args()

    project_root = str(Path(args.project_root).resolve())
    print(f"[migrate_memory] project_root={project_root}, force={args.force}")

    result = migrate(project_root, force=args.force)

    # 输出结果摘要
    print(f"\n  成功: {len(result['success'])} 个")
    for s in result["success"]:
        print(f"    ✓ {s}")

    print(f"  跳过: {len(result['skipped'])} 个")
    for s in result["skipped"]:
        print(f"    - {s}")

    print(f"  失败: {len(result['errors'])} 个")
    for e in result["errors"]:
        print(f"    ✗ {e}")

    # 输出 JSON 结果供自动化调用
    print(f"\n{json.dumps(result, ensure_ascii=False, indent=2)}")

    # 非零退出码：有错误时
    if result["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
