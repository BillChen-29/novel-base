#!/usr/bin/env python3
"""共享工具模块 - 消除代码重复

该模块集中管理所有脚本共享的工具函数，避免在多个文件中重复定义。
主要用于支持百万字级别长篇小说的创作流程。
"""

import functools
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# =============================================================================
# C1: 章节元数据管理（chapter_info schema）
# =============================================================================

# chapter_info schema 定义
CHAPTER_INFO_SCHEMA = {
    "chapter_number": {"type": "int", "required": True},
    "chapter_title": {"type": "str", "required": True},
    "chapter_role": {"type": "str", "required": True, "enum": ["开场", "铺垫", "转折", "高潮", "收尾"]},
    "chapter_purpose": {"type": "str", "required": False, "default": ""},
    "suspense_level": {"type": "str", "required": False, "default": "低", "enum": ["低", "中", "高"]},
    "foreshadowing": {"type": "str", "required": False, "default": ""},
    "plot_twist_level": {"type": "int", "required": False, "default": 1, "min": 1, "max": 5},
    "characters_involved": {"type": "list", "required": False, "default": []},
    "key_items": {"type": "list", "required": False, "default": []},
    "scene_location": {"type": "str", "required": False, "default": ""},
    "time_constraint": {"type": "str", "required": False, "default": ""},
}

VALID_CHAPTER_ROLES = ["开场", "铺垫", "转折", "高潮", "收尾"]
VALID_SUSPENSE_LEVELS = ["低", "中", "高"]


def create_chapter_info(
    chapter_number: int,
    chapter_title: str,
    chapter_role: str,
    chapter_purpose: str = "",
    suspense_level: str = "低",
    foreshadowing: str = "",
    plot_twist_level: int = 1,
    characters_involved: Optional[List[str]] = None,
    key_items: Optional[List[str]] = None,
    scene_location: str = "",
    time_constraint: str = "",
) -> Dict[str, Any]:
    """创建章节元数据（chapter_info）。

    Args:
        chapter_number: 章节序号
        chapter_title: 章节标题
        chapter_role: 章节角色（开场|铺垫|转折|高潮|收尾）
        chapter_purpose: 章节目的
        suspense_level: 悬念等级（低|中|高）
        foreshadowing: 伏笔描述
        plot_twist_level: 情节反转强度（1-5）
        characters_involved: 涉及角色列表
        key_items: 关键道具列表
        scene_location: 场景地点
        time_constraint: 时间约束

    Returns:
        章节元数据字典
    """
    return {
        "chapter_number": chapter_number,
        "chapter_title": chapter_title,
        "chapter_role": chapter_role,
        "chapter_purpose": chapter_purpose,
        "suspense_level": suspense_level,
        "foreshadowing": foreshadowing,
        "plot_twist_level": plot_twist_level,
        "characters_involved": characters_involved or [],
        "key_items": key_items or [],
        "scene_location": scene_location,
        "time_constraint": time_constraint,
    }


def validate_chapter_info(info: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """校验 chapter_info 完整性与字段合法性。

    Args:
        info: 章节元数据字典

    Returns:
        (是否合法, 错误消息列表)
    """
    errors: List[str] = []

    # 必填字段检查
    for field, spec in CHAPTER_INFO_SCHEMA.items():
        if spec["required"] and field not in info:
            errors.append(f"缺少必填字段: {field}")

    # 类型检查
    type_map = {"int": int, "str": str, "list": list}
    for field, spec in CHAPTER_INFO_SCHEMA.items():
        if field in info and spec["type"] in type_map:
            expected = type_map[spec["type"]]
            if not isinstance(info[field], expected):
                errors.append(f"字段 {field} 类型错误: 期望 {spec['type']}, 实际 {type(info[field]).__name__}")

    # 枚举校验
    if "chapter_role" in info and info["chapter_role"] not in VALID_CHAPTER_ROLES:
        errors.append(f"chapter_role 值非法: {info['chapter_role']}，可选: {VALID_CHAPTER_ROLES}")

    if "suspense_level" in info and info["suspense_level"] not in VALID_SUSPENSE_LEVELS:
        errors.append(f"suspense_level 值非法: {info['suspense_level']}，可选: {VALID_SUSPENSE_LEVELS}")

    # 数值范围校验
    if "plot_twist_level" in info:
        val = info["plot_twist_level"]
        if isinstance(val, int) and not (1 <= val <= 5):
            errors.append(f"plot_twist_level 超出范围: {val}，应在 1-5 之间")

    return len(errors) == 0, errors


def save_chapter_info(info: Dict[str, Any], meta_dir: Path, filename: Optional[str] = None) -> bool:
    """保存章节元数据到 JSON 文件。

    Args:
        info: 章节元数据字典
        meta_dir: 元数据目录（如 retrieval/chapter_meta/）
        filename: 文件名（默认自动生成）

    Returns:
        是否保存成功
    """
    ok, errors = validate_chapter_info(info)
    if not ok:
        print(f"[WARN] chapter_info 校验失败: {'; '.join(errors)}")
        # 仍然允许保存，但打印警告

    ensure_dir(meta_dir)
    if filename is None:
        chapter_no = info.get("chapter_number", 0)
        title_slug = slugify(info.get("chapter_title", ""))
        filename = f"第{chapter_no}章-{title_slug}.meta.json" if title_slug else f"chapter_{chapter_no:03d}.meta.json"

    meta_path = meta_dir / filename
    return save_json(meta_path, info)


def load_chapter_info(meta_dir: Path, filename: str) -> Dict[str, Any]:
    """加载章节元数据。

    Args:
        meta_dir: 元数据目录
        filename: 元数据文件名

    Returns:
        章节元数据字典，加载失败返回空字典
    """
    meta_path = meta_dir / filename
    return load_json(meta_path, default={})


def load_chapter_info_by_number(meta_dir: Path, chapter_number: int) -> Dict[str, Any]:
    """按章节序号加载元数据（模糊匹配）。

    扫描 meta_dir 下所有 .meta.json 文件，返回 chapter_number 匹配的第一条。

    Args:
        meta_dir: 元数据目录
        chapter_number: 章节序号

    Returns:
        章节元数据字典，未找到返回空字典
    """
    if not meta_dir.exists():
        return {}

    for meta_file in sorted(meta_dir.glob("*.meta.json")):
        info = load_json(meta_file, default={})
        if info.get("chapter_number") == chapter_number:
            return info

    return {}


# =============================================================================
# C3: 场景触发加载（Scene Trigger Loading）
# =============================================================================

# 章节角色 → 场景文件映射
ROLE_TO_SCENARIO_MAP = {
    "开场": ["opening.md"],
    "铺垫": ["character-intro.md", "world-building.md"],
    "转折": ["revelation.md"],
    "高潮": ["climax.md", "fight-scene.md"],
    "收尾": ["cliffhanger.md"],
}

# 场景文件基准路径（相对于 skill 根目录）
_SCENARIO_REL_PATH = "assets/technique_library/_scenarios"


def _resolve_scenarios_dir() -> Path:
    """解析场景文件目录的绝对路径。

    查找顺序：
    1. SKILL_ROOT 环境变量（如有）
    2. common.py 所在目录的上级（即 skill 根目录）

    Returns:
        场景文件目录的 Path 对象
    """
    import os
    skill_root = os.environ.get("SKILL_ROOT")
    if skill_root:
        return Path(skill_root) / _SCENARIO_REL_PATH

    # 从 common.py 位置推算 skill 根目录
    # common.py → scripts/ → skill 根
    common_dir = Path(__file__).resolve().parent
    skill_root = common_dir.parent
    return skill_root / _SCENARIO_REL_PATH


def load_scenario_by_role(
    chapter_role: str,
    scenarios_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """根据章节角色加载对应的场景模板文件。

    Args:
        chapter_role: 章节角色（开场|铺垫|转折|高潮|收尾）
        scenarios_dir: 场景文件目录（默认自动解析）

    Returns:
        场景模板列表，每项包含：
        - role: 章节角色
        - scenario_file: 场景文件名
        - content: 场景文件内容（读取失败为空字符串）
        - path: 文件完整路径
        - exists: 文件是否存在
    """
    if scenarios_dir is None:
        scenarios_dir = _resolve_scenarios_dir()

    scenario_files = ROLE_TO_SCENARIO_MAP.get(chapter_role, [])
    results: List[Dict[str, Any]] = []

    for filename in scenario_files:
        file_path = scenarios_dir / filename
        exists = file_path.exists()
        content = read_text(file_path, default="") if exists else ""

        results.append({
            "role": chapter_role,
            "scenario_file": filename,
            "content": content,
            "path": str(file_path),
            "exists": exists,
        })

    return results


def load_scenario_content(chapter_role: str, scenarios_dir: Optional[Path] = None) -> str:
    """根据章节角色加载并合并所有场景模板内容。

    多个场景文件时用分隔线连接。

    Args:
        chapter_role: 章节角色（开场|铺垫|转折|高潮|收尾）
        scenarios_dir: 场景文件目录（默认自动解析）

    Returns:
        合并后的场景模板文本，未找到时返回空字符串
    """
    scenarios = load_scenario_by_role(chapter_role, scenarios_dir)
    if not scenarios:
        return ""

    contents = []
    for s in scenarios:
        if s["content"]:
            contents.append(s["content"])

    return "\n\n---\n\n".join(contents)


def get_role_for_chapter(chapter_number: int, total_chapters: int = 20) -> str:
    """根据章节序号推断章节角色（启发式默认值）。

    按典型小说结构自动分配：
    - 第1章 → 开场
    - 前20% → 铺垫
    - 中间60% → 转折
    - 最后20%前1章 → 高潮
    - 最后1章 → 收尾

    Args:
        chapter_number: 章节序号（从1开始）
        total_chapters: 预估总章节数

    Returns:
        章节角色字符串
    """
    if chapter_number <= 1:
        return "开场"

    if chapter_number >= total_chapters:
        return "收尾"

    if chapter_number >= total_chapters - 1:
        return "高潮"

    if chapter_number <= total_chapters * 0.2:
        return "铺垫"

    return "转折"


# =============================================================================
# 预编译的正则表达式（性能优化）
# =============================================================================

_CHAPTER_RE = re.compile(r"^第\d+章.*\.md$")
_SLUGIFY_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_-]+")
_CHARS_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_ENGLISH_RE = re.compile(r"[A-Za-z]{3,}")
_CHAPTER_NO_RE = re.compile(r"第(\d+)章")

# =============================================================================
# 文件系统操作
# =============================================================================


def ensure_dir(path: Path) -> None:
    """确保目录存在，不存在则递归创建。
    
    Args:
        path: 目录路径
    """
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path, default: str = "") -> str:
    """安全读取文本文件。

    Args:
        path: 文件路径
        default: 文件不存在时的默认值

    Returns:
        文件内容，或默认值
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        print(f"[WARN] 文件编码问题 {path}: {e}")
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PermissionError):
        return default


def write_text(path: Path, content: str) -> bool:
    """安全写入文本文件。
    
    Args:
        path: 文件路径
        content: 写入内容
        
    Returns:
        是否写入成功
    """
    try:
        ensure_dir(path.parent)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return True
    except (IOError, PermissionError) as e:
        # 使用 print 而非 logging，保持与现有代码一致
        print(f"[ERROR] 写入失败 {path}: {e}")
        return False


# =============================================================================
# JSON 操作
# =============================================================================


def load_json(
    path: Path,
    default: Optional[Dict[str, Any]] = None,
    required_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """安全加载 JSON 文件，支持默认值和键校验。
    
    Args:
        path: JSON 文件路径
        default: 加载失败时的默认值
        required_keys: 必须存在的键列表
        
    Returns:
        解析后的字典，或默认值
    """
    if default is None:
        default = {}

    if not path.exists():
        return default.copy()

    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)

        if not isinstance(obj, dict):
            return default.copy()

        # 校验必需字段
        if required_keys:
            missing = [k for k in required_keys if k not in obj]
            if missing:
                return default.copy()

        return obj

    except (json.JSONDecodeError, IOError, KeyError):
        return default.copy()


def save_json(
    path: Path, payload: Dict[str, Any], indent: int = 2
) -> bool:
    """安全保存 JSON 文件。
    
    Args:
        path: 文件路径
        payload: 要保存的字典
        indent: 缩进空格数
        
    Returns:
        是否保存成功
    """
    try:
        ensure_dir(path.parent)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=indent)
        return True
    except (IOError, TypeError) as e:
        print(f"[ERROR] 保存 JSON 失败 {path}: {e}")
        return False


# =============================================================================
# 文本处理
# =============================================================================


def slugify(text: str) -> str:
    """将文本转换为 URL/文件名友好的 slug。
    
    保留中文字符、字母、数字、下划线和连字符。
    
    Args:
        text: 原始文本
        
    Returns:
        转换后的 slug
    """
    s = _SLUGIFY_RE.sub("-", text).strip("-")
    return s or "chapter"


def normalize_text(text: str) -> str:
    """将连续空白替换为单个空格。"""
    return re.sub(r"\s+", " ", text).strip()


def count_chars(text: str, include_spaces: bool = False) -> int:
    """统计文本字符数（统一方法）。

    对于中文小说，通常统计中文字符数更准确。
    此方法同时支持：
    - 纯中文字符统计（默认）
    - 包含所有非空白字符统计

    Args:
        text: 输入文本
        include_spaces: 是否包含空格和标点

    Returns:
        字符数
    """
    if include_spaces:
        # 统计所有非空白字符
        return len(re.sub(r"\s+", "", text))
    else:
        # 仅统计中文字符（更适合中文小说）
        return len(re.findall(r'[\u4e00-\u9fff]', text))


def sha1_text(text: str) -> str:
    """计算文本的 SHA1 哈希值。
    
    Args:
        text: 输入文本
        
    Returns:
        SHA1 哈希字符串
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def file_sha1(path: Path) -> str:
    """计算文件的 SHA1 哈希值。
    
    Args:
        path: 文件路径
        
    Returns:
        文件内容的 SHA1 哈希，文件不存在返回空字符串
    """
    if not path.exists():
        return ""
    return sha1_text(path.read_text(encoding="utf-8", errors="ignore"))


# =============================================================================
# 章节相关工具
# =============================================================================


def is_chapter_file(filename: str) -> bool:
    """判断文件名是否为章节文件。
    
    章节文件名格式：第XX章[标题].md
    
    Args:
        filename: 文件名
        
    Returns:
        是否为章节文件
    """
    return bool(_CHAPTER_RE.match(filename))


def chapter_no_from_name(filename: str) -> int:
    """从章节文件名提取章节序号。
    
    Args:
        filename: 章节文件名，如 "第15章 突破.md"
        
    Returns:
        章节序号，提取失败返回0
    """
    match = _CHAPTER_NO_RE.search(filename)
    if match:
        return int(match.group(1))
    return 0


def normalize_chapter_filename(chapter_no: int, title: str = "") -> str:
    """生成标准化的章节文件名。
    
    Args:
        chapter_no: 章节序号
        title: 章节标题（可选）
        
    Returns:
        标准化文件名，如 "第15章 突破.md"
    """
    if title:
        # 清理标题中的非法字符
        clean_title = re.sub(r'[<>:"/\\|?*]', '', title).strip()
        return f"第{chapter_no}章 {clean_title}.md"
    return f"第{chapter_no}章.md"


# =============================================================================
# 缓存相关工具
# =============================================================================


def generate_cache_key(*components: str) -> str:
    """生成缓存键。
    
    Args:
        *components: 缓存键组成部分
        
    Returns:
        哈希后的缓存键
    """
    combined = "|".join(components)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


# =============================================================================
# 统一搜索（plot_rag + QMD）
# =============================================================================

# QMD collection → 结果分类映射
_QMD_COLLECTION_MAP = {
    'motif-library': 'motifs',
    'character-archetypes': 'archetypes',
    'technique-library': 'techniques',
    'style-library': 'styles',
    'pacing-template': 'pacing',
}


def qmd_search(query: str, collection: str = 'motif-library', top_k: int = 3) -> List[Dict]:
    """通过 subprocess 调 QMD CLI 执行检索，返回标准化结果列表。

    Args:
        query: 搜索关键词
        collection: QMD collection 名称
        top_k: 返回结果数量

    Returns:
        结果列表，每项包含 file, title, score, snippet 字段
    """
    import subprocess
    try:
        result = subprocess.run(
            ['qmd', 'search', query, '-c', collection, '-n', str(top_k), '--json'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return []
        items = json.loads(result.stdout) if result.stdout.strip() else []
        return [
            {
                'file': item.get('file', ''),
                'title': item.get('title', ''),
                'score': item.get('score', 0),
                'snippet': item.get('snippet', ''),
            }
            for item in items
        ]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, Exception):
        return []


def unified_search(
    query: str,
    project_root: Optional[str] = None,
    collections: Optional[List[str]] = None,
    top_k: int = 3,
) -> Dict[str, List[Dict]]:
    """统一搜索入口，返回按来源分组的结果。

    Args:
        query: 搜索关键词
        project_root: 项目根目录（用于 plot_rag 项目内搜索）
        collections: QMD collection 列表（默认全部）
        top_k: 每个 collection 返回结果数

    Returns:
        按来源分组的字典：
        {
            'plot_context': [...],  # 项目内上下文（来自 plot_rag）
            'motifs': [...],        # 母题建议（来自 QMD）
            'archetypes': [...],    # 角色原型建议
            'techniques': [...],    # 技法建议
            'styles': [...],        # 风格建议
            'pacing': [...],        # 节奏模板建议
        }
    """
    results: Dict[str, List[Dict]] = {
        'plot_context': [],
        'motifs': [],
        'archetypes': [],
        'techniques': [],
        'styles': [],
        'pacing': [],
    }

    # 项目级：plot_rag（Python 函数直接调用）
    if project_root:
        try:
            import sys
            script_dir = str(Path(__file__).parent)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            from plot_rag_retriever import retrieve
            rag_results = retrieve(query, top_k=top_k)
            if isinstance(rag_results, list):
                for r in rag_results:
                    r['source'] = 'project'
                results['plot_context'] = rag_results
        except Exception:
            pass  # plot_rag 不可用时静默降级

    # 通用级：QMD CLI（subprocess + timeout + 静默降级）
    if collections is None:
        collections = list(_QMD_COLLECTION_MAP.keys())

    for col in collections:
        hits = qmd_search(query, col, top_k)
        result_key = _QMD_COLLECTION_MAP.get(col, col)
        if result_key in results:
            for h in hits:
                h['source'] = 'universal'
                h['collection'] = col
            results[result_key] = hits

    return results


# =============================================================================
# B1: 知识库内容过滤（三阶段过滤）
# =============================================================================


def _extract_keywords(text: str) -> set:
    """从文本中提取中英文关键词（中文用 bigram，英文用单词）。

    Args:
        text: 输入文本

    Returns:
        关键词集合
    """
    keywords = set()
    # 提取中文字符序列，然后生成 bigram
    for m in _CHARS_RE.finditer(text):
        seq = m.group()
        if len(seq) == 1:
            # 单个中文字符单独作为一个词
            keywords.add(seq)
        else:
            # 生成 bigram（相邻两个字）
            for i in range(len(seq) - 1):
                keywords.add(seq[i:i+2])
    # 提取英文词（3字母以上）
    for m in _ENGLISH_RE.finditer(text):
        keywords.add(m.group().lower())
    return keywords


def check_conflict(item: Dict, chapter_summaries: List[Dict]) -> float:
    """用 Jaccard 相似度检测知识库条目与已写章节的冲突。

    Args:
        item: 搜索结果条目（需含 'snippet' 或 'title' 字段）
        chapter_summaries: 章节摘要列表，每项含 'summary' 或 'keywords' 字段

    Returns:
        冲突分数（0~1），> 0.4 视为冲突

    Raises:
        ValueError: 当 chapter_summaries 为空时抛出
    """
    if not chapter_summaries:
        raise ValueError("chapter_summaries 不能为空，请先跳过冲突检测")

    item_text = (item.get('snippet', '') or '') + ' ' + (item.get('title', '') or '')
    item_kw = _extract_keywords(item_text)
    if not item_kw:
        return 0.0

    max_similarity = 0.0
    for summary in chapter_summaries:
        summary_text = (summary.get('summary', '') or '') + ' ' + (summary.get('keywords', '') or '')
        summary_kw = _extract_keywords(summary_text)
        if not summary_kw:
            continue
        intersection = item_kw & summary_kw
        union = item_kw | summary_kw
        if union:
            similarity = len(intersection) / len(union)
            max_similarity = max(max_similarity, similarity)

    return max_similarity


def evaluate_value(item: Dict, current_chapter: int) -> str:
    """评估知识库条目对当前章节的价值。

    Args:
        item: 搜索结果条目（需含 'score' 字段）
        current_chapter: 当前章节号

    Returns:
        'critical'（关键参考）/ 'reference'（一般参考）/ 'low'（低价值）
    """
    score = item.get('score', 0)
    if score >= 0.8:
        return 'critical'
    elif score >= 0.5:
        return 'reference'
    else:
        return 'low'


def classify_content(item: Dict) -> str:
    """根据来源 collection 自动分类知识库条目。

    分类映射：
        motif-library → plot_fuel
        character-archetypes → character_dim
        technique-library → narrative_technique
        style-library → narrative_technique
        pacing-template → plot_fuel

    Args:
        item: 搜索结果条目（需含 'collection' 字段）

    Returns:
        内容分类标签
    """
    collection = item.get('collection', '')
    _COLLECTION_CLASSIFY = {
        'motif-library': 'plot_fuel',
        'character-archetypes': 'character_dim',
        'technique-library': 'narrative_technique',
        'style-library': 'narrative_technique',
        'pacing-template': 'plot_fuel',
    }
    return _COLLECTION_CLASSIFY.get(collection, 'unknown')


def filter_search_results(
    results: Dict[str, List[Dict]],
    current_chapter: int,
    chapter_summaries: Optional[List[Dict]] = None,
) -> Dict[str, List[Dict]]:
    """B1: 知识库内容过滤 - 三阶段过滤流水线。

    三阶段过滤：
    1. 冲突检测（Jaccard 相似度 > 0.4 跳过）
    2. 价值评估（critical/reference/low）
    3. 结构归类（按来源 collection 自动分类）

    Args:
        results: unified_search 返回的分组结果字典
        current_chapter: 当前章节号
        chapter_summaries: 已写章节摘要列表，为空时跳过冲突检测

    Returns:
        过滤后的结果字典，每个条目增加 conflict_score / value / category 字段
    """
    if chapter_summaries is None:
        chapter_summaries = []

    filtered: Dict[str, List[Dict]] = {}
    for category, items in results.items():
        kept = []
        for item in items:
            # 第一阶段：冲突检测
            try:
                conflict = check_conflict(item, chapter_summaries)
                if conflict > 0.4:
                    continue  # 冲突过高，跳过
            except ValueError:
                # chapter_summaries 为空时跳过冲突检测
                conflict = 0.0
            item['conflict_score'] = conflict

            # 第二阶段：价值评估
            item['value'] = evaluate_value(item, current_chapter)

            # 第三阶段：结构归类
            item['category'] = classify_content(item)

            kept.append(item)
        filtered[category] = kept

    return filtered


# =============================================================================
# B2: 章节距离规则
# =============================================================================


def apply_distance_rules(
    results: Dict[str, List[Dict]],
    current_chapter: int,
) -> List[Dict]:
    """B2: 章节距离规则 - 根据章节号距离调整权重。

    规则：
        距离 <= 2: weight=0.1, note='skip'（太近，跳过参考）
        距离 <= 5: weight=0.5, note='rewrite_40'（中等距离，40%重写）
        距离 > 5:  weight=1.0, note='ok'（足够远，直接参考）

    Args:
        results: unified_search 返回的分组结果字典
        current_chapter: 当前章节号

    Returns:
        平铺列表，每个条目增加 weight / distance_note 字段
    """
    all_items: List[Dict] = []
    for items in results.values():
        all_items.extend(items)

    enriched: List[Dict] = []
    for item in all_items:
        chapter_number = item.get('chapter_number')
        if chapter_number is None:
            # chapter_number 缺失时默认 weight=1.0
            item['weight'] = 1.0
            item['distance_note'] = 'ok'
        else:
            distance = abs(current_chapter - chapter_number)
            if distance <= 2:
                item['weight'] = 0.1
                item['distance_note'] = 'skip'
            elif distance <= 5:
                item['weight'] = 0.5
                item['distance_note'] = 'rewrite_40'
            else:
                item['weight'] = 1.0
                item['distance_note'] = 'ok'
        enriched.append(item)

    return enriched


# =============================================================================
# 版本信息
# =============================================================================

__version__ = "1.0.0"
__all__ = [
    # 文件系统
    "ensure_dir",
    "read_text",
    "write_text",
    # JSON
    "load_json",
    "save_json",
    # 文本处理
    "slugify",
    "normalize_text",
    "sha1_text",
    "file_sha1",
    # 章节相关
    "is_chapter_file",
    "chapter_no_from_name",
    "normalize_chapter_filename",
    # 缓存
    "generate_cache_key",
    # 统一搜索
    "qmd_search",
    "unified_search",
    # B1 知识库内容过滤
    "check_conflict",
    "evaluate_value",
    "classify_content",
    "filter_search_results",
    # B2 章节距离规则
    "apply_distance_rules",
    # C1 章节元数据管理
    "CHAPTER_INFO_SCHEMA",
    "VALID_CHAPTER_ROLES",
    "VALID_SUSPENSE_LEVELS",
    "create_chapter_info",
    "validate_chapter_info",
    "save_chapter_info",
    "load_chapter_info",
    "load_chapter_info_by_number",
    # C3 场景触发加载
    "ROLE_TO_SCENARIO_MAP",
    "load_scenario_by_role",
    "load_scenario_content",
    "get_role_for_chapter",
]
