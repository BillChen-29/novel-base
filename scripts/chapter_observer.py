#!/usr/bin/env python3
"""
Chapter Observer - 从章节正文提取 9 类事实

Observer 角色：接收章节正文和当前真相状态，
组装 prompt 输入供 LLM 处理，并解析 LLM 输出为结构化 delta。

注意：Observer 不直接调用 LLM，只负责组装输入和解析输出。

路径：~/.hermes/skills/novel-creator-skill/scripts/chapter_observer.py
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Observer prompt 模板路径
_PROMPT_PATH = Path(__file__).resolve().parent / "observer_prompt.md"

# 9 个事实字段
DELTA_FIELDS = [
    "new_characters",
    "relationship_changes",
    "resource_changes",
    "power_level_changes",
    "emotion_changes",
    "hook_operations",
    "subplot_progress",
    "world_additions",
    "timeline_advance",
]


def load_observer_prompt() -> str:
    """
    读取 observer_prompt.md 模板。

    Returns:
        模板文本

    Raises:
        FileNotFoundError: 模板文件不存在时
    """
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Observer prompt 不存在: {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")


def assemble_observer_input(
    chapter_text: str,
    current_truth: str,
) -> str:
    """
    组装 Observer 完整 prompt。

    Args:
        chapter_text: 章节正文
        current_truth: 当前真相状态（JSON 字符串或可读文本）

    Returns:
        替换占位符后的完整 prompt
    """
    template = load_observer_prompt()
    prompt = template.replace("{chapter_text}", chapter_text)
    prompt = prompt.replace("{current_truth}", current_truth)
    return prompt


def _strip_code_block(text: str) -> str:
    """去除 markdown 代码块标记，提取 JSON 内容。"""
    text = text.strip()
    # 去除 ```json ... ``` 包裹
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _ensure_delta_schema(data: dict) -> dict:
    """
    确保 delta 包含所有必需字段，缺失的字段填默认空值。
    """
    defaults: Dict[str, Any] = {
        "new_characters": [],
        "relationship_changes": [],
        "resource_changes": [],
        "power_level_changes": [],
        "emotion_changes": [],
        "hook_operations": [],
        "subplot_progress": [],
        "world_additions": [],
        "timeline_advance": {},
    }
    for field in DELTA_FIELDS:
        if field not in data:
            data[field] = defaults.get(field, [])
    return data


def parse_observer_output(llm_output: str) -> Tuple[Optional[dict], List[str]]:
    """
    解析 Observer LLM 输出为结构化 delta。

    Args:
        llm_output: LLM 原始输出文本（应为 JSON）

    Returns:
        (delta_dict, errors):
        - 解析成功：delta_dict 为包含 9 个字段的字典，errors 为空列表
        - 解析失败：delta_dict 为 None，errors 包含错误描述
    """
    errors: List[str] = []

    if not llm_output or not llm_output.strip():
        return (None, ["LLM 输出为空"])

    # 去除可能的代码块标记
    cleaned = _strip_code_block(llm_output)

    # 尝试解析 JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # 尝试从文本中提取 JSON 片段
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                return (None, [f"JSON 解析失败: {e}"])
        else:
            return (None, [f"JSON 解析失败: {e}"])

    if not isinstance(data, dict):
        return (None, [f"期望 dict，实际得到 {type(data).__name__}"])

    # 补全缺失字段
    data = _ensure_delta_schema(data)

    # 基础校验
    for field in ["new_characters", "relationship_changes", "resource_changes",
                   "power_level_changes", "emotion_changes", "hook_operations",
                   "subplot_progress", "world_additions"]:
        if not isinstance(data.get(field), list):
            errors.append(f"字段 {field} 应为 list，实际为 {type(data.get(field)).__name__}")
            data[field] = []

    if not isinstance(data.get("timeline_advance"), dict):
        errors.append(f"字段 timeline_advance 应为 dict，实际为 {type(data.get('timeline_advance')).__name__}")
        data["timeline_advance"] = {}

    if errors:
        return (data, errors)

    return (data, [])


# =============================================================================
# CLI 入口
# =============================================================================

def main():
    """命令行入口：读取章节文件和真相文件，组装 prompt。"""
    import argparse

    parser = argparse.ArgumentParser(description="Chapter Observer - 组装观察者 prompt")
    parser.add_argument("--chapter-file", "-c", required=True, help="章节正文文件路径")
    parser.add_argument("--truth-file", "-t", required=True, help="当前真相文件路径")
    parser.add_argument("--output", "-o", help="输出 prompt 到文件（默认 stdout）")
    args = parser.parse_args()

    chapter_path = Path(args.chapter_file)
    truth_path = Path(args.truth_file)

    if not chapter_path.exists():
        print(f"[ERROR] 章节文件不存在: {chapter_path}")
        return 1
    if not truth_path.exists():
        print(f"[ERROR] 真相文件不存在: {truth_path}")
        return 1

    chapter_text = chapter_path.read_text(encoding="utf-8")
    truth_text = truth_path.read_text(encoding="utf-8")

    prompt = assemble_observer_input(chapter_text, truth_text)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(prompt, encoding="utf-8")
        print(f"[OK] Prompt 已保存到 {out_path}")
    else:
        print(prompt)

    return 0


if __name__ == "__main__":
    exit(main())
