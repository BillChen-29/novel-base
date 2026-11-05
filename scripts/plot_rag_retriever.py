#!/usr/bin/env python3
"""轻量剧情检索器（RAG 风格，零外部依赖）。

目标：将人物关系、剧情走向与章节内容建立可检索关联，
在写新剧情前自动给出“应回读哪些章节”的上下文建议。
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from common import ensure_dir, read_text, slugify, chapter_no_from_name, normalize_text
from config import get_retrieval_config
from performance import Tokenizer

# 从集中配置加载检索相关常量
_retrieval_config = get_retrieval_config()
STOPWORDS = _retrieval_config.stopwords
TRIGGER_KEYWORDS = _retrieval_config.trigger_keywords
LIGHT_SCENE_KEYWORDS = _retrieval_config.light_scene_keywords

# 全局分词器实例（带缓存，性能优于手写版本）
_tokenizer = Tokenizer(stopwords=STOPWORDS)

INDEX_SCHEMA_VERSION = 2


def _reject_output_link(path: Path) -> None:
    if path.is_symlink() or (path.is_file() and path.stat().st_nlink > 1):
        raise ValueError("unsafe_retrieval_output: symbolic and hard links are not allowed in derived outputs")


def _guard_retrieval_outputs(retrieval_dir: Path) -> Path:
    """Check parents and the complete existing output tree before any mutation."""
    directory = retrieval_dir.absolute()
    # Canonicalize only ancestors above the project; retain 00_memory/retrieval
    # so a pre-existing link cannot be erased by resolve() before validation.
    root = directory.parent.parent.resolve()
    if directory.name != "retrieval" or directory.parent.name != "00_memory":
        raise ValueError("unsafe_retrieval_output: expected project/00_memory/retrieval")
    directory = root / "00_memory" / "retrieval"
    for item in (root / "00_memory", directory):
        _reject_output_link(item)
        if item.exists() and not item.is_dir():
            raise ValueError("unsafe_retrieval_output: output parent is not a directory")
    if directory.exists():
        for item in directory.rglob("*"):
            _reject_output_link(item)
    return directory


def _atomic_output_text(path: Path, text: str) -> None:
    """Never follow an existing output link; replace an ordinary file atomically."""
    path = path.absolute()
    # Test each named ancestor before resolving the parent. The OS temp aliases
    # (/var and /tmp on macOS) are outside these already-canonical project paths.
    for ancestor in (path, *path.parents):
        _reject_output_link(ancestor)
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    try:
        _reject_output_link(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _emit_output_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser().absolute()
    for ancestor in (path, *path.parents):
        if ancestor == project_root or (ancestor.is_dir() and ancestor.resolve() == project_root):
            break
        # macOS exposes /var and /tmp as system aliases. Canonicalize those
        # only after checking every user-controlled descendant.
        if ancestor in (Path("/var"), Path("/tmp")) and ancestor.resolve() == Path("/private") / ancestor.name:
            continue
        _reject_output_link(ancestor)
    path = path.parent.resolve() / path.name
    if path.is_relative_to(project_root / "03_manuscript"):
        raise ValueError("unsafe_retrieval_output: JSON output cannot replace a manuscript")
    return path


def _source_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _chapter_path(project_root: Path, path: Path) -> Path:
    """Reject foreign paths and symlink escapes before opening a manuscript."""
    root = project_root.resolve()
    directory = root / "03_manuscript"
    resolved = path.resolve()
    if directory.resolve() != directory or resolved.parent != directory or path.is_symlink():
        raise ValueError("outside_manuscript: chapter must be an ordinary file in this project's 03_manuscript")
    return resolved


def _chapter_files(project_root: Path) -> List[Path]:
    root = project_root.resolve()
    directory = root / "03_manuscript"
    if directory.resolve() != directory:
        raise ValueError("outside_manuscript: manuscript directory must not be a symlink")
    return sorted((_chapter_path(root, p) for p in directory.glob("*.md")),
                  key=lambda p: (parse_chapter_no(p.name), p.name))


def _tracker_signature(project_root: Path) -> str:
    path = project_root / "00_memory/character_tracker.md"
    return _source_hash(path.read_bytes()) if path.exists() else _source_hash(b"")


def validate_cutoff(cutoff_chapter: Optional[int], cutoff_offset: Optional[int]) -> None:
    if cutoff_chapter is not None and (type(cutoff_chapter) is not int or cutoff_chapter < 0):
        raise ValueError("cutoff_chapter must be a nonnegative integer or None")
    if cutoff_offset is not None:
        if type(cutoff_offset) is not int or cutoff_offset < 0:
            raise ValueError("cutoff_offset must be a nonnegative integer or None")
        if cutoff_chapter is None or cutoff_chapter == 0:
            raise ValueError("cutoff_offset requires a positive cutoff_chapter")


def _validated_sources(index: Dict[str, object], project_root: Path) -> List[Tuple[dict, str, str]]:
    root = project_root.resolve()
    if not index.get("project_root") or Path(str(index["project_root"])).resolve() != root:
        raise ValueError("project_mismatch: index belongs to another project")
    docs = index.get("docs", [])
    if not isinstance(docs, list):
        raise ValueError("stale_index: invalid document list; rebuild index")
    actual = {p.name for p in _chapter_files(root)}
    indexed = set()
    sources = []
    for doc in docs:
        path = _chapter_path(root, Path(str(doc.get("chapter_path", ""))))
        if doc.get("chapter_file") != path.name or path.name in indexed:
            raise ValueError("stale_index: inconsistent chapter identity; rebuild index")
        indexed.add(path.name)
        if not path.is_file():
            raise ValueError("stale_index: chapter removed; rebuild index")
        raw = path.read_bytes()
        sha = _source_hash(raw)
        if doc.get("source_sha256") != sha or doc.get("chapter_no") != parse_chapter_no(path.name):
            raise ValueError("stale_index: chapter content changed; rebuild index")
        sources.append((doc, raw.decode("utf-8"), sha))
    if actual != indexed or index.get("tracker_sha256") != _tracker_signature(root):
        raise ValueError("stale_index: project sources changed; rebuild index")
    return sources


def _bounded_sources(sources: List[Tuple[dict, str, str]], cutoff_chapter: Optional[int],
                     cutoff_offset: Optional[int]) -> List[Tuple[dict, str, str]]:
    validate_cutoff(cutoff_chapter, cutoff_offset)
    if cutoff_offset is not None:
        matches = [text for doc, text, _ in sources if doc["chapter_no"] == cutoff_chapter]
        if len(matches) != 1 or cutoff_offset > len(matches[0]):
            raise ValueError("cutoff_offset requires one existing chapter and must not exceed its decoded length")
    selected = []
    for doc, text, sha in sources:
        number = doc["chapter_no"]
        if cutoff_chapter is not None and not (0 < number <= cutoff_chapter):
            continue
        if cutoff_chapter is not None and (
                "<!-- NOVEL_FLOW_STUB -->" in text or "<!-- BEAT_SHEET_STUB -->" in text
                or re.search(r"(?m)^\s*\[待写\]\s*$", text)):
            # Plans and generation instructions are not accepted story history.
            continue
        if cutoff_offset is not None and number == cutoff_chapter:
            text = text[:cutoff_offset]
        if text.strip():
            selected.append((doc, text, sha))
    return selected


def tokenize(text: str) -> List[str]:
    """中文 2~4 字 n-gram + 英文词分词，委托给优化的 Tokenizer 实现。"""
    return _tokenizer.tokenize(text)


def parse_chapter_no(filename: str) -> int:
    return chapter_no_from_name(filename)


def normalize_query(query: str) -> str:
    return normalize_text(query)


def analyze_query_trigger(query: str, names: List[str]) -> Dict[str, object]:
    q = normalize_query(query)
    q = normalize_query(query)
    entities = [n for n in names if n in q]
    keyword_hits = sorted([k for k in TRIGGER_KEYWORDS if k in q])
    light_hits = sorted([k for k in LIGHT_SCENE_KEYWORDS if k in q])
    long_query = len(q) >= 18
    short_but_meaningful = len(q) >= 8
    should = bool(entities or keyword_hits or (long_query and not light_hits) or short_but_meaningful)
    reason = []
    if entities:
        reason.append(f"命中角色:{','.join(entities)}")
    if keyword_hits:
        reason.append(f"命中剧情关键词:{','.join(keyword_hits[:4])}")
    if long_query and not light_hits:
        reason.append("查询描述较长，判定为复杂剧情")
    if short_but_meaningful and not entities and not keyword_hits:
        reason.append(f"查询长度({len(q)}字符)>=8，判定为有意义查询")
    if light_hits and not entities and not keyword_hits:
        reason.append(f"命中轻场景关键词:{','.join(light_hits)}")

    return {
        "should_trigger": should,
        "entities": entities,
        "keyword_hits": keyword_hits,
        "light_hits": light_hits,
        "query_length": len(q),
        "reason": reason,
    }


def load_character_names(project_root: Path) -> List[str]:
    p = project_root / "00_memory" / "character_tracker.md"
    if not p.exists():
        return []
    txt = read_text(p)

    names = set()

    # 1) 表格第一列
    for line in txt.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        candidate = cells[0]
        if candidate in {"人物", "角色", "姓名", "---", ""}:
            continue
        if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·]{2,20}", candidate):
            names.add(candidate)

    # 2) “姓名: xxx”形式
    for m in re.finditer(r"(?:姓名|角色)\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9_·]{2,20})", txt):
        names.add(m.group(1).strip())

    # 去噪
    bad = {"当前状态", "关系", "位置", "目标", "变化", "章节"}
    names = {n for n in names if n not in bad}
    return sorted(names)


def extract_relation_snippets(path: Path, terms: List[str], window: int = 2, max_hits: int = 8) -> List[str]:
    # 参数校验
    if window < 0:
        raise ValueError(f"window 必须非负，当前值: {window}")
    if max_hits < 0:
        raise ValueError(f"max_hits 必须非负，当前值: {max_hits}")
    if not path.exists() or not terms:
        return []
    lines = read_text(path).splitlines()
    hits: List[str] = []
    used = set()
    seen_blocks = set()
    last_end = -1
    for i, line in enumerate(lines):
        if not any(t in line for t in terms):
            continue
        if i <= last_end:
            continue
        start = max(0, i - window)
        end = min(len(lines), i + window + 1)
        key = (start, end)
        if key in used:
            continue
        used.add(key)
        block = "\n".join(lines[start:end]).strip()
        normalized_lines = []
        for ln in block.splitlines():
            s = ln.strip()
            if re.fullmatch(r"\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?", s):
                continue
            if s:
                normalized_lines.append(s)
        norm_key = " || ".join(normalized_lines)

        if block and norm_key and norm_key not in seen_blocks:
            hits.append(block)
            seen_blocks.add(norm_key)
            last_end = end - 1
        if len(hits) >= max_hits:
            break
    return hits


def split_passages(text: str, max_chars: int = 360) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not paragraphs:
        paragraphs = [normalize_text(text)]

    passages: List[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            passages.append(para)
            continue
        # 超长段落按句子切片，避免整段回读。
        pieces = [s.strip() for s in re.split(r"(?<=[。！？!?])", para) if s.strip()]
        buf = ""
        for piece in pieces:
            if len(buf) + len(piece) <= max_chars:
                buf += piece
            else:
                if buf:
                    passages.append(buf)
                buf = piece
        if buf:
            passages.append(buf)
    return passages


def extract_location_candidates(text: str, top_n: int = 6) -> List[str]:
    # 轻量地点抽取：匹配“在X/到X/从X”及“X站/港/城/街/村/馆”等后缀。
    hits = []
    for m in re.finditer(r"(?:在|到|从|回到)([\u4e00-\u9fff]{2,12}(?:站台|车站|港区|港|城|城北|街|巷|村|楼|馆|厂|桥|学校|医院))", text):
        hits.append(m.group(1))
    for m in re.finditer(r"([\u4e00-\u9fff]{2,10}(?:站台|车站|港区|港|城|街|巷|村|楼|馆|厂|桥|学校|医院))", text):
        hits.append(m.group(1))
    if not hits:
        return []
    counter = Counter(hits)
    return [x for x, _ in counter.most_common(top_n)]


def infer_conflict_level(text: str) -> str:
    high = {"决战", "追杀", "爆炸", "死亡", "复活", "背叛", "崩溃", "危机", "反转"}
    medium = {"冲突", "争执", "对峙", "潜入", "调查", "追踪", "怀疑", "联盟"}
    low = {"日常", "休整", "过渡", "闲聊", "铺垫"}
    if any(k in text for k in high):
        return "high"
    if any(k in text for k in medium):
        return "medium"
    if any(k in text for k in low):
        return "low"
    return "unknown"


def _text_metadata(text: str, names: List[str], keyword_top_n: int = 20) -> Dict[str, object]:
    tokens = tokenize(text)
    refs = []
    for match in re.finditer(r"(伏笔|线索|坐标|编号|暗号|名单)[^。！？\n]{0,32}", text):
        fragment = normalize_text(match.group(0))
        if fragment and fragment not in refs:
            refs.append(fragment)
        if len(refs) == 6:
            break
    return {
        "summary": re.sub(r"\s+", " ", text).strip()[:260],
        "entities": sorted(n for n in names if n in text),
        "keywords": [k for k, _ in Counter(tokens).most_common(keyword_top_n)],
        "events": [k for k in TRIGGER_KEYWORDS if k in text][:10],
        "locations": extract_location_candidates(text, top_n=6),
        "foreshadow_refs": refs,
        "conflict_level": infer_conflict_level(text),
    }


def build_chapter_meta(
    chapter_path: Path,
    text: str,
    chapter_no: int,
    names: List[str],
    retrieval_dir: Path,
    *, outputs_prevalidated: bool = False,
) -> Dict[str, object]:
    if not outputs_prevalidated:
        retrieval_dir = _guard_retrieval_outputs(retrieval_dir)
    meta_dir = retrieval_dir / "chapter_meta"
    ensure_dir(meta_dir)
    meta_path = meta_dir / f"{slugify(chapter_path.stem)}.meta.json"
    meta = {
        **_text_metadata(text, names),
        "chapter_file": chapter_path.name,
        "chapter_path": str(chapter_path),
        "chapter_no": chapter_no,
        "mtime": chapter_path.stat().st_mtime,
        "source_sha256": _source_hash(chapter_path.read_bytes()),
        "meta_file": str(meta_path),
    }
    _atomic_output_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def score_passage(passage: str, query_tokens: List[str], query_entities: List[str]) -> Tuple[float, Dict[str, int]]:
    p_tokens = set(tokenize(passage))
    token_overlap = len(set(query_tokens) & p_tokens)
    entity_overlap = sum(1 for e in query_entities if e in passage)
    score = entity_overlap * 3.0 + token_overlap * 1.0
    return score, {
        "token_overlap": token_overlap,
        "entity_overlap": entity_overlap,
    }


def _passage_spans(text: str, max_chars: int = 360) -> List[Tuple[int, int]]:
    """Return contiguous source spans, preserving original newlines and Unicode offsets."""
    spans = []
    cursor = 0
    for separator in list(re.finditer(r"\n\s*\n+", text)) + [None]:
        end = separator.start() if separator is not None else len(text)
        start = cursor
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        while start < end:
            stop = min(end, start + max_chars)
            if stop < end:
                last_sentence = max((m.end() for m in re.finditer(r"[。！？!?]", text[start:stop])), default=0)
                if last_sentence:
                    stop = start + last_sentence
            spans.append((start, stop))
            start = stop
            while start < end and text[start].isspace():
                start += 1
        if separator is not None:
            cursor = separator.end()
    return spans


def top_passages(
    chapter_path: Path,
    query_tokens: List[str],
    query_entities: List[str],
    per_chapter: int,
    passage_max_chars: int,
    *, text: Optional[str] = None, source_sha256: Optional[str] = None,
) -> List[Dict[str, object]]:
    if text is None:
        raw = chapter_path.read_bytes()
        text, source_sha256 = raw.decode("utf-8"), _source_hash(raw)
    scored = []
    for start, end in _passage_spans(text):
        score, reason = score_passage(text[start:end], query_tokens, query_entities)
        scored.append((score, reason, start, end))
    scored.sort(key=lambda row: row[0], reverse=True)
    selected = [row for row in scored if row[0] > 0][:per_chapter]
    if not selected:
        selected = scored[:per_chapter]
    result = []
    for score, reason, start, original_end in selected:
        end = min(original_end, start + passage_max_chars)
        result.append({
            "score": round(score, 3), "reason": reason, "text": text[start:end],
            "start": start, "end": end, "source_path": str(chapter_path),
            "source_sha256": source_sha256, "truncated": end < original_end,
            "offset_convention": "UTF-8 decoded Unicode characters; [start, end); no newline normalization",
        })
    return result


def index_signature(index: Dict[str, object]) -> str:
    docs = index.get("docs", [])
    fields = {"schema": INDEX_SCHEMA_VERSION, "root": index.get("project_root"),
              "keyword_top_n": index.get("keyword_top_n", 20),
              "tracker": index.get("tracker_sha256"),
              "docs": [(d.get("chapter_file"), d.get("source_sha256")) for d in docs]}
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{len(docs)}-{digest}"


def load_cache(path: Path) -> Dict[str, object]:
    path = _guard_retrieval_outputs(path.parent) / path.name
    if not path.exists():
        return {"entries": {}}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {"entries": {}}
        obj.setdefault("entries", {})
        return obj
    except json.JSONDecodeError:
        return {"entries": {}}
    except (IOError, OSError):
        return {"entries": {}}


def save_cache(path: Path, cache: Dict[str, object], max_entries: int = 200) -> None:
    path = _guard_retrieval_outputs(path.parent) / path.name
    entries = cache.get("entries", {})
    if isinstance(entries, dict) and len(entries) > max_entries:
        items = sorted(entries.items(), key=lambda kv: kv[1].get("saved_at", ""), reverse=True)
        cache["entries"] = dict(items[:max_entries])
    _atomic_output_text(path, json.dumps(cache, ensure_ascii=False, indent=2))


def make_cache_key(query: str, top_k: int, per_chapter: int, passage_max_chars: int, idx_sig: str,
                   *, candidate_k: int = 12, min_score: float = 0.0,
                   cutoff_chapter: Optional[int] = None, cutoff_offset: Optional[int] = None) -> str:
    raw = json.dumps([INDEX_SCHEMA_VERSION, query, top_k, candidate_k, per_chapter,
                      passage_max_chars, min_score, idx_sig, cutoff_chapter, cutoff_offset], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cleanup_stale_meta_files(retrieval_dir: Path, docs: List[Dict[str, object]]) -> int:
    retrieval_dir = _guard_retrieval_outputs(retrieval_dir)
    meta_dir = retrieval_dir / "chapter_meta"
    if not meta_dir.exists():
        return 0
    valid_files = set()
    for d in docs:
        mf = d.get("meta_file")
        if isinstance(mf, str) and mf:
            valid_files.add(Path(mf).resolve())
    removed = 0
    for p in meta_dir.glob("*.meta.json"):
        if p.resolve() not in valid_files:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def build_index(project_root: Path, keyword_top_n: int = 20, incremental: bool = True) -> Dict[str, object]:
    project_root = project_root.expanduser().resolve()
    chapters = _chapter_files(project_root)
    retrieval_dir = _guard_retrieval_outputs(project_root / "00_memory" / "retrieval")
    ensure_dir(retrieval_dir)
    index_file = retrieval_dir / "story_index.json"
    names = load_character_names(project_root)
    tracker_sha = _tracker_signature(project_root)
    existing_docs = {}
    if incremental and index_file.exists():
        try:
            old = json.loads(index_file.read_text(encoding="utf-8"))
            if (old.get("schema_version") == INDEX_SCHEMA_VERSION
                    and old.get("project_root") == str(project_root)
                    and old.get("tracker_sha256") == tracker_sha
                    and old.get("keyword_top_n") == keyword_top_n):
                existing_docs = {d["chapter_file"]: d for d in old.get("docs", [])}
        except (ValueError, KeyError, TypeError, OSError):
            existing_docs = {}
    docs, reused_docs, rebuilt_docs = [], 0, 0
    for path in chapters:
        raw = path.read_bytes()
        source_sha = _source_hash(raw)
        text = raw.decode("utf-8")
        cached = existing_docs.get(path.name)
        expected_meta = retrieval_dir / "chapter_meta" / f"{slugify(path.stem)}.meta.json"
        if (cached and cached.get("source_sha256") == source_sha
                and cached.get("chapter_path") == str(path)
                and cached.get("meta_file") == str(expected_meta) and expected_meta.is_file()):
            doc = dict(cached)
            doc["mtime"] = path.stat().st_mtime
            reused_docs += 1
        else:
            doc = build_chapter_meta(path, text, parse_chapter_no(path.name), names, retrieval_dir,
                                     outputs_prevalidated=True)
            doc.update(_text_metadata(text, names, keyword_top_n))
            doc["source_sha256"] = source_sha
            rebuilt_docs += 1
        docs.append(doc)
    entity_map = {n: [] for n in names}
    for doc in docs:
        for name in doc.get("entities", []):
            entity_map.setdefault(name, []).append(doc["chapter_file"])
    index = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(project_root), "chapter_count": len(docs),
        "reused_docs": reused_docs, "rebuilt_docs": rebuilt_docs,
        "cleaned_meta_files": cleanup_stale_meta_files(retrieval_dir, docs),
        "character_sig": hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:16],
        "tracker_sha256": tracker_sha, "keyword_top_n": keyword_top_n, "docs": docs,
    }
    _atomic_output_text(index_file, json.dumps(index, ensure_ascii=False, indent=2))
    _atomic_output_text(retrieval_dir / "entity_chapter_map.json", json.dumps(entity_map, ensure_ascii=False, indent=2))
    return index


def score_doc_coarse(
    doc: Dict[str, object],
    query_tokens: List[str],
    query_token_set: set,
    query_entities: List[str],
    query_text: str,
) -> Tuple[float, Dict[str, object]]:
    kw = set(doc.get("keywords", []))
    ent = set(doc.get("entities", []))
    evt = set(doc.get("events", []))
    loc = set(doc.get("locations", []))

    token_overlap = len(query_token_set & kw)
    entity_overlap = len(set(query_entities) & ent)
    event_overlap = sum(1 for e in evt if e and e in query_text)
    location_overlap = sum(1 for l in loc if l and l in query_text)

    score = entity_overlap * 4.0 + event_overlap * 2.0 + location_overlap * 1.5 + token_overlap * 1.0
    reason = {
        "token_overlap": token_overlap,
        "entity_overlap": entity_overlap,
        "event_overlap": event_overlap,
        "location_overlap": location_overlap,
    }
    return score, reason


def score_doc_fine(
    doc: Dict[str, object],
    query_tokens: List[str],
    query_token_set: set,
    query_entities: List[str],
    query_text: str,
    max_no: int,
) -> Tuple[float, Dict[str, object]]:
    kw = set(doc.get("keywords", []))
    ent = set(doc.get("entities", []))
    evt = set(doc.get("events", []))
    summary = str(doc.get("summary", ""))

    token_overlap = len(query_token_set & kw)
    summary_overlap = len(query_token_set & set(tokenize(summary)))
    entity_overlap = len(set(query_entities) & ent)
    event_overlap = sum(1 for e in evt if e and e in query_text)

    chapter_no = int(doc.get("chapter_no", 0))
    recency = (chapter_no / max_no) if max_no > 0 else 0.0
    conflict_bonus = 0.2 if doc.get("conflict_level") in {"high", "medium"} else 0.0

    score = (
        entity_overlap * 3.0
        + event_overlap * 1.8
        + token_overlap * 1.0
        + summary_overlap * 0.6
        + recency * 0.3
        + conflict_bonus
    )
    reason = {
        "token_overlap": token_overlap,
        "summary_overlap": summary_overlap,
        "entity_overlap": entity_overlap,
        "event_overlap": event_overlap,
        "recency": round(recency, 3),
        "conflict_bonus": conflict_bonus,
    }
    return score, reason


def retrieve(
    index: Dict[str, object],
    project_root: Path,
    query: str,
    top_k: int,
    candidate_k: int,
    per_chapter: int,
    passage_max_chars: int,
    min_score: float = 0.0,
    cutoff_chapter: Optional[int] = None,
    cutoff_offset: Optional[int] = None,
) -> Dict[str, object]:
    project_root = project_root.expanduser().resolve()
    validate_cutoff(cutoff_chapter, cutoff_offset)
    for value in (top_k, candidate_k, per_chapter, passage_max_chars):
        if type(value) is not int or value <= 0:
            raise ValueError("retrieval sizes must be positive integers")
    sources = _bounded_sources(_validated_sources(index, project_root), cutoff_chapter, cutoff_offset)
    # Historical queries cannot assume that current tracker names or relationships
    # were known at the cutoff. All scored fields come from the permitted prefix.
    names = load_character_names(project_root) if cutoff_chapter is None else []
    docs, source_texts = [], {}
    for original, text, sha in sources:
        doc = {key: original[key] for key in ("chapter_file", "chapter_path", "chapter_no")}
        doc.update(_text_metadata(text, names, int(index.get("keyword_top_n", 20))))
        doc.update({"source_sha256": sha, "visible_chars": len(text),
                    "visible_sha256": _source_hash(text.encode("utf-8"))})
        docs.append(doc)
        source_texts[doc["chapter_path"]] = text
    query_tokens = tokenize(query)
    query_token_set = set(query_tokens)
    query_entities = [n for n in names if n in query]

    max_no = max((int(d.get("chapter_no", 0)) for d in docs), default=0)
    coarse_scored = []
    for d in docs:
        s, reason = score_doc_coarse(d, query_tokens, query_token_set, query_entities, query)
        coarse_scored.append((s, reason, d))

    coarse_scored.sort(key=lambda x: x[0], reverse=True)
    candidate_pool = [x for x in coarse_scored if x[0] >= min_score][:candidate_k]
    if not candidate_pool:
        candidate_pool = coarse_scored[: min(candidate_k, len(coarse_scored))]

    fine_scored = []
    for _, _, d in candidate_pool:
        s, reason = score_doc_fine(d, query_tokens, query_token_set, query_entities, query, max_no)
        fine_scored.append((s, reason, d))
    fine_scored.sort(key=lambda x: x[0], reverse=True)

    picked = [x for x in fine_scored if x[0] >= min_score][:top_k]
    if not picked:
        picked = fine_scored[: min(top_k, len(fine_scored))]

    # BM25 token-only fallback: when all fine scores are 0, do a simple
    # token-overlap rerank across candidate_pool to avoid returning nothing.
    if not picked and candidate_pool:
        token_fallback = []
        for _, _, d in candidate_pool:
            kw = set(d.get("keywords", []))
            tok_overlap = len(query_token_set & kw)
            if tok_overlap > 0:
                token_fallback.append((float(tok_overlap), {"token_overlap": tok_overlap}, d))
        token_fallback.sort(key=lambda x: x[0], reverse=True)
        picked = token_fallback[:top_k]

    character_tracker = project_root / "00_memory" / "character_tracker.md"
    relation_snippets = extract_relation_snippets(character_tracker, query_entities) if cutoff_chapter is None else []

    total_chars = 0
    retrieved = []
    for s, reason, d in picked:
        passages = top_passages(
            Path(str(d.get("chapter_path", ""))),
            query_tokens,
            query_entities,
            per_chapter=per_chapter,
            passage_max_chars=passage_max_chars,
            text=source_texts[d["chapter_path"]],
            source_sha256=d["source_sha256"],
        )
        total_chars += sum(len(str(p.get("text", ""))) for p in passages)
        retrieved.append({
            "score": round(s, 3),
            "reason": reason,
            "chapter_file": d.get("chapter_file"),
            "chapter_path": d.get("chapter_path"),
            "chapter_no": d.get("chapter_no"),
            "source_sha256": d["source_sha256"],
            "visible_chars": d["visible_chars"],
            "visible_sha256": d["visible_sha256"],
            "summary": d.get("summary", ""),
            "entities": d.get("entities", []),
            "events": d.get("events", []),
            "locations": d.get("locations", []),
            "foreshadow_refs": d.get("foreshadow_refs", []),
            "passages": passages,
        })

    return {
        "query": query,
        "query_entities": query_entities,
        "index_signature": index_signature(index),
        "source_cutoff": {"chapter": cutoff_chapter, "offset": cutoff_offset},
        "memory_scope": "current_tracker" if cutoff_chapter is None else "manuscript_prefix_only",
        "retrieved": retrieved,
        "relation_snippets": relation_snippets,
        "retrieval_stats": {
            "docs_total": len(docs),
            "candidate_pool": len(candidate_pool),
            "rerank_topk": len(retrieved),
            "estimated_context_chars": total_chars,
        },
    }


def write_context_md(project_root: Path, result: Dict[str, object]) -> Path:
    retrieval_dir = _guard_retrieval_outputs(project_root.resolve() / "00_memory" / "retrieval")
    ensure_dir(retrieval_dir)
    out = retrieval_dir / "next_plot_context.md"

    lines = []
    lines.append("# 新剧情写作上下文建议（RAG）")
    lines.append("")
    lines.append(f"- 查询：{result.get('query', '')}")
    entities = result.get("query_entities", [])
    lines.append(f"- 命中角色：{', '.join(entities) if entities else '无'}")
    if result.get("cache_hit"):
        lines.append("- 缓存命中：是（复用历史检索结果）")
    if result.get("skipped"):
        lines.append(f"- 条件触发：跳过（{'; '.join(result.get('trigger_reason', []))}）")
    stats = result.get("retrieval_stats", {})
    if stats:
        lines.append(
            "- 检索统计：候选池={candidate_pool} / 总文档={docs_total} / 估算上下文字符={estimated_context_chars}".format(
                candidate_pool=stats.get("candidate_pool", 0),
                docs_total=stats.get("docs_total", 0),
                estimated_context_chars=stats.get("estimated_context_chars", 0),
            )
        )
    lines.append("")
    bounded = result.get("source_cutoff", {}).get("chapter") is not None
    if bounded:
        lines.append("## 本次前文边界")
        lines.append(f"- 截点：{result['source_cutoff']}；仅使用以下许可前缀片段。")
        lines.append("- 未使用无历史版本的角色关系表或最新故事状态；不要回读整章补全截点之后内容。")
    else:
        lines.append("## 建议先读（固定）")
        lines.append("- 00_memory/novel_plan.md")
        lines.append("- 00_memory/novel_state.md")
    lines.append("")
    if result.get("skipped"):
        lines.append("## 本次检索策略")
        lines.append("- 判定为轻场景或信息不足，本次跳过章节检索以节省上下文。")
        lines.append("- 如需强制检索，可使用 `--force`。")
        _atomic_output_text(out, "\n".join(lines).strip() + "\n")
        return out

    lines.append("## 建议回读章节（Top）")
    retrieved = result.get("retrieved", [])
    if not retrieved:
        lines.append("- 无可用章节")
    else:
        for i, r in enumerate(retrieved, 1):
            lines.append(f"{i}. `{r['chapter_file']}` | score={r['score']} | 命中={r['reason']}")
            lines.append(f"   摘要：{r['summary']}")
            meta_bits = []
            if r.get("events"):
                meta_bits.append("事件=" + ",".join(r["events"][:4]))
            if r.get("locations"):
                meta_bits.append("地点=" + ",".join(r["locations"][:3]))
            if r.get("foreshadow_refs"):
                meta_bits.append("伏笔=" + " / ".join(r["foreshadow_refs"][:2]))
            if meta_bits:
                lines.append("   元数据：" + "；".join(meta_bits))
            passages = r.get("passages", [])
            if passages:
                lines.append("   关键片段：")
                for p in passages:
                    lines.append(f"   - {p['text']} (reason={p['reason']}, score={p['score']})")
                    if "start" in p:
                        lines.append(f"     来源：{p['source_path']} [{p['start']},{p['end']}) SHA256={p['source_sha256']}")

    lines.append("")
    lines.append("## 角色关系相关片段")
    snippets = result.get("relation_snippets", [])
    if not snippets:
        lines.append("- 无命中（可补充 character_tracker）")
    else:
        for i, s in enumerate(snippets, 1):
            lines.append(f"### 片段 {i}")
            lines.append("```")
            lines.append(s)
            lines.append("```")

    lines.append("")
    lines.append("## 写作前执行建议")
    lines.append("1. 仅用上述截点前片段核对事实，未知信息保持未知。" if bounded else "1. 读取上述 Top 章节，确认人物关系与伏笔状态。")
    lines.append("2. 若发现冲突，先执行 /检查一致性 再写作。")
    lines.append("3. 写作后继续执行门禁链路。")

    _atomic_output_text(out, "\n".join(lines).strip() + "\n")
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="构建章节索引并按新剧情检索相关章节上下文")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="更新剧情索引")
    p_build.add_argument("--project-root", required=True)
    p_build.add_argument("--keyword-top-n", type=int, default=20)
    p_build.add_argument("--full-rebuild", action="store_true", help="禁用增量索引，强制全量重建")

    p_query = sub.add_parser("query", help="检索新剧情关联章节")
    p_query.add_argument("--project-root", required=True)
    p_query.add_argument("--query", required=True)
    p_query.add_argument("--cutoff-chapter", type=int, default=None, help="仅检索此章及之前；0 表示空历史")
    p_query.add_argument("--cutoff-offset", type=int, default=None, help="截点章原文的 Unicode 字符排他上界；不归一化换行")
    p_query.add_argument("--top-k", type=int, default=4)
    p_query.add_argument("--auto-build", action="store_true")
    p_query.add_argument("--full-rebuild", action="store_true", help="与 --auto-build 联用时强制全量重建")
    p_query.add_argument("--passages-per-chapter", type=int, default=2, help="每章返回片段数量")
    p_query.add_argument("--candidate-k", type=int, default=12, help="粗筛候选池大小（两级检索第一阶段）")
    p_query.add_argument("--passage-max-chars", type=int, default=220, help="单片段最大字符数")
    p_query.add_argument("--min-score", type=float, default=0.0, help="最低得分阈值，低于此分数的结果被过滤（默认0.0）")
    p_query.add_argument("--conditional", dest="conditional", action="store_true", default=True, help="启用条件触发，轻场景跳过检索")
    p_query.add_argument("--no-conditional", dest="conditional", action="store_false", help="关闭条件触发，每次都检索")
    p_query.add_argument("--force", action="store_true", help="强制检索，忽略条件触发判定")
    p_query.add_argument("--use-cache", dest="use_cache", action="store_true", default=True, help="启用查询缓存")
    p_query.add_argument("--no-cache", dest="use_cache", action="store_false", help="禁用查询缓存")
    p_query.add_argument("--emit-json")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    emit_path = _emit_output_path(args.emit_json, project_root) if getattr(args, "emit_json", None) else None

    if args.cmd == "build":
        index = build_index(
            project_root,
            keyword_top_n=args.keyword_top_n,
            incremental=not args.full_rebuild,
        )
        print(json.dumps({
            "ok": True,
            "cmd": "build",
            "chapter_count": index.get("chapter_count", 0),
            "reused_docs": index.get("reused_docs", 0),
            "rebuilt_docs": index.get("rebuilt_docs", 0),
            "index_file": str(project_root / "00_memory" / "retrieval" / "story_index.json"),
        }, ensure_ascii=False, indent=2))
        return 0

    retrieval_dir = project_root / "00_memory" / "retrieval"
    validate_cutoff(args.cutoff_chapter, args.cutoff_offset)
    # Fresh content hashes are required before any cache hit, including default query.
    # --auto-build remains accepted for compatibility.
    index = build_index(project_root, incremental=not args.full_rebuild)
    _bounded_sources(_validated_sources(index, project_root), args.cutoff_chapter, args.cutoff_offset)

    names = load_character_names(project_root) if args.cutoff_chapter is None else []
    trigger = analyze_query_trigger(args.query, names)

    if args.conditional and not args.force and not trigger["should_trigger"]:
        result = {
            "query": args.query,
            "query_entities": trigger.get("entities", []),
            "skipped": True,
            "cache_hit": False,
            "trigger_reason": trigger.get("reason", []),
            "retrieved": [],
            "relation_snippets": [],
            "source_cutoff": {"chapter": args.cutoff_chapter, "offset": args.cutoff_offset},
        }
        md_out = write_context_md(project_root, result)
        payload = {
            "ok": True,
            "cmd": "query",
            "context_file": str(md_out),
            "result": result,
        }
        if args.emit_json:
            _atomic_output_text(emit_path, json.dumps(payload, ensure_ascii=False, indent=2))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    cache_file = retrieval_dir / "query_cache.json"
    idx_sig = index_signature(index)
    cache_key = make_cache_key(
        args.query,
        args.top_k,
        args.passages_per_chapter,
        args.passage_max_chars,
        idx_sig,
        candidate_k=args.candidate_k,
        min_score=args.min_score,
        cutoff_chapter=args.cutoff_chapter,
        cutoff_offset=args.cutoff_offset,
    )

    if args.use_cache:
        cache = load_cache(cache_file)
        entry = cache.get("entries", {}).get(cache_key)
        if entry and isinstance(entry, dict) and "result" in entry:
            result = entry["result"]
            result["cache_hit"] = True
            md_out = write_context_md(project_root, result)
            payload = {
                "ok": True,
                "cmd": "query",
                "context_file": str(md_out),
                "cache_hit": True,
                "result": result,
            }
            if args.emit_json:
                _atomic_output_text(emit_path, json.dumps(payload, ensure_ascii=False, indent=2))
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

    result = retrieve(
        index,
        project_root,
        args.query,
        args.top_k,
        candidate_k=max(args.top_k, args.candidate_k),
        per_chapter=args.passages_per_chapter,
        passage_max_chars=args.passage_max_chars,
        min_score=args.min_score,
        cutoff_chapter=args.cutoff_chapter,
        cutoff_offset=args.cutoff_offset,
    )
    result["cache_hit"] = False
    result["skipped"] = False
    result["trigger_reason"] = trigger.get("reason", [])

    # Warn when retrieval returns 0 results
    if not result.get("retrieved"):
        import sys as _sys
        print(
            f"WARNING: RAG retrieval returned 0 results for query: {args.query!r}. "
            f"Trigger reasons: {trigger.get('reason', [])}. "
            f"Candidate pool size: {result.get('retrieval_stats', {}).get('candidate_pool', 0)}. "
            f"Try lowering --min-score or using --force.",
            file=_sys.stderr,
        )

    if args.use_cache:
        cache = load_cache(cache_file)
        cache.setdefault("entries", {})
        cache["entries"][cache_key] = {
            "saved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": result,
        }
        save_cache(cache_file, cache)

    md_out = write_context_md(project_root, result)

    payload = {
        "ok": True,
        "cmd": "query",
        "context_file": str(md_out),
        "cache_hit": False,
        "result": result,
    }

    if args.emit_json:
        _atomic_output_text(emit_path, json.dumps(payload, ensure_ascii=False, indent=2))

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        raise SystemExit(1)
