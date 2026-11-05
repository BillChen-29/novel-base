#!/usr/bin/env python3
"""Small, reproducible Chinese retrieval experiment; no network or story generation."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path, PurePosixPath

from narrative_prototype import build_catalog

VERSION = "retrieval-pilot-v1"
MODES = ("window", "structure")
METHODS = ("bm25", "vector", "hybrid")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def asset_path(root, value):
    require(isinstance(value, str), "资料路径必须是字符串")
    part = PurePosixPath(value)
    require(not part.is_absolute() and part.parts and part.parts[0] == "assets"
            and ".." not in part.parts and "\\" not in value and str(part) == value,
            "非法资料路径")
    path = root / value
    require(path.resolve().is_relative_to((root / "assets").resolve())
            and (root / "assets").resolve().is_relative_to(root.resolve()), "资料路径越界")
    require(path.is_file() and path.suffix == ".md", "试验只接收 Markdown 创作资料")
    return path


def load_fixture(path: Path, repo_root: Path) -> dict:
    fixture = read_json(path)
    require(isinstance(fixture, dict) and fixture.get("schema_version") == 1, "未知样本格式")
    documents, queries = fixture.get("documents"), fixture.get("queries")
    require(isinstance(documents, list) and documents, "缺少文档样本")
    require(isinstance(queries, list) and queries, "缺少查询样本")
    eligible = {item["path"] for item in build_catalog(repo_root) if item["eligible"]}
    texts = {}
    for doc in documents:
        require(isinstance(doc, dict), "文档记录必须为对象")
        name = doc.get("path")
        source = asset_path(repo_root, name)
        require(name not in texts and name in eligible, "资料重复或不属于可检索资料")
        texts[name] = source.read_bytes().decode("utf-8")
    seen = set()
    for query in queries:
        require(isinstance(query, dict), "查询必须为对象")
        ident = query.get("id")
        require(isinstance(ident, str) and ident and ident not in seen, "查询 ID 重复或缺失")
        seen.add(ident)
        require(isinstance(query.get("text"), str) and query["text"].strip(), "查询为空")
        require(query.get("split") in {"development", "holdout"}, "未知查询分组")
        relevant = query.get("relevant_paths")
        require(isinstance(relevant, list) and all(isinstance(p, str) for p in relevant)
                and len(set(relevant)) == len(relevant) and set(relevant) <= set(texts),
                "相关文档不在样本中或重复")
        evidence = query.get("evidence")
        require(isinstance(evidence, list), "证据必须是列表")
        covered = set()
        for ref in evidence:
            require(isinstance(ref, dict) and ref.get("path") in relevant, "证据路径不在相关文档中")
            quote = ref.get("quote")
            require(isinstance(quote, str) and quote.strip() and quote in texts[ref["path"]],
                    "证据引文不在原资料中")
            covered.add(ref["path"])
        require(covered == set(relevant), "每份相关资料必须有原文证据")
    return fixture


def _heading_boundaries(text):
    boundaries, headings, offset, stack = [0], [], 0, []
    fence = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if marker:
            mark = marker.group(1)
            if fence is None:
                fence = (mark[0], len(mark))
            elif mark[0] == fence[0] and len(mark) >= fence[1]:
                fence = None
        elif fence is None:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            bold = re.match(r"^\*\*([^*]+)\*\*", line)
            if match or bold:
                level, label = (len(match[1]), match[2]) if match else (2, bold[1])
                stack = [item for item in stack if item[0] < level] + [(level, label)]
                headings.append((offset, [item[1] for item in stack]))
                if offset:
                    boundaries.append(offset)
        offset += len(line)
    return sorted(set(boundaries + [len(text)])), headings


def build_chunks(text: str, source_path: str, mode: str, max_chars=800, overlap=120) -> list[dict]:
    require(mode in MODES, "未知分块模式")
    require(type(max_chars) is int and type(overlap) is int and max_chars > 0
            and 0 <= overlap < max_chars, "分块长度或重叠无效")
    require(isinstance(text, str), "正文必须是字符串")
    boundaries, headings = _heading_boundaries(text)
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match[1].strip() if title_match else Path(source_path).stem
    version = digest(text)
    docid = "asset-" + digest(source_path)[:20]
    spans = list(zip(boundaries, boundaries[1:])) if mode == "structure" else [(0, len(text))]
    chunks = []
    for lower, upper in spans:
        start = lower
        while start < upper:
            end = min(start + max_chars, upper)
            if mode == "structure" and end < upper:
                # Prefer a paragraph or line break, but always make forward progress.
                cut = text.rfind("\n\n", start + max(max_chars // 2, overlap + 1), end)
                if cut < 0:
                    cut = text.rfind("\n", start + max(max_chars // 2, overlap + 1), end)
                if cut >= 0:
                    end = cut + 1
            raw = text[start:end]
            if raw.strip():
                heading = next((labels for pos, labels in reversed(headings) if pos <= start), [])
                chunks.append({"chunk_id": f"{docid}@{version[:12]}:{mode}:{start}:{end}",
                    "document_id": docid, "source_path": source_path, "source_sha256": version,
                    "start": start, "end": end, "start_line": text.count("\n", 0, start) + 1,
                    "end_line": text.count("\n", 0, max(start, end - 1)) + 1,
                    "title": title, "heading_path": heading, "text": raw,
                    "scope": "shared", "project_id": None, "chunker_version": VERSION})
            if end == upper:
                break
            start = end - overlap
    return chunks


def tokens(text):
    result = re.findall(r"[a-z0-9]+", text.lower())
    for run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]+", text):
        result.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            result.append(run)
    return result


def bm25_rank(query: str, chunks: list) -> list:
    # Stable accumulation is needed when rankings are bound to review hashes.
    terms = sorted(set(tokens(query)))
    if not terms or not chunks:
        return []
    counts = [Counter(tokens(c.get("title", "") + "\n" + c["text"])) for c in chunks]
    sizes = [sum(c.values()) for c in counts]
    avg = sum(sizes) / len(sizes) or 1
    freq = Counter(term for c in counts for term in c)
    result = []
    for chunk, count, size in zip(chunks, counts, sizes):
        score = 0.0
        for term in terms:
            tf = count[term]
            if tf:
                idf = math.log(1 + (len(chunks) - freq[term] + 0.5) / (freq[term] + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * size / avg))
        if score > 0:
            result.append({"chunk_id": chunk["chunk_id"], "source_path": chunk["source_path"], "score": score})
    return sorted(result, key=lambda hit: (-hit["score"], hit["source_path"], hit["chunk_id"]))


def collapse_documents(hits, limit=5):
    require(type(limit) is int and limit >= 0, "返回数量无效")
    found, result = set(), []
    for hit in hits:
        if hit["source_path"] not in found:
            found.add(hit["source_path"])
            result.append(dict(hit))
    return result[:limit]


def rrf_fuse(rankings, k=60):
    require(type(k) is int and k > 0, "RRF k 必须为正整数")
    merged = {}
    for ranking in rankings:
        for rank, hit in enumerate(collapse_documents(ranking, len(ranking)), 1):
            key = hit["source_path"]
            weight = 1 / (k + rank)
            if key not in merged:
                merged[key] = {"source_path": key, "chunk_id": hit["chunk_id"], "score": 0.0,
                               "best_contribution": weight}
            if weight > merged[key]["best_contribution"]:
                merged[key]["chunk_id"] = hit["chunk_id"]
                merged[key]["best_contribution"] = weight
            merged[key]["score"] += weight
    return sorted(merged.values(), key=lambda hit: (-hit["score"], hit["source_path"]))


def score_ranking(ranked_paths, relevant_paths, k=5):
    require(type(k) is int and k > 0, "评估 k 必须为正整数")
    relevant = set(relevant_paths)
    if not relevant:
        return {"recall_at_k": None, "mrr_at_k": None, "hit_at_k": None}
    ranked = list(dict.fromkeys(ranked_paths))[:k]
    first = next((i for i, p in enumerate(ranked, 1) if p in relevant), None)
    return {"recall_at_k": len(set(ranked) & relevant) / len(relevant),
            "mrr_at_k": 1 / first if first else 0.0, "hit_at_k": float(first is not None)}


def score_evidence(hits, evidence):
    """Exact quote coverage is a diagnostic, not a semantic answer-quality score."""
    expected = {(ref["path"], ref["quote"]) for ref in evidence}
    if not expected:
        return {"evidence_recall_at_k": None, "complete_evidence_at_k": None}
    covered = {(path, quote) for path, quote in expected
               if any(hit["source_path"] == path and quote in hit["excerpt"] for hit in hits)}
    return {"evidence_recall_at_k": len(covered) / len(expected),
            "complete_evidence_at_k": float(covered == expected)}


def safe_output(value, root):
    requested = Path(value).expanduser().absolute()
    for parent in (requested, *requested.parents):
        require(not parent.is_symlink(), "输出路径不得包含符号链接")
    output = requested.resolve()
    require(not output.is_relative_to(root) or output.is_relative_to(root / "runtime-data"),
            "仓库内只允许写入 runtime-data")
    return output


def write_json(path, data):
    require(not path.is_symlink() and (not path.exists() or path.stat().st_nlink == 1),
            "输出文件不得是符号链接或硬链接")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(fixture_path, root, output):
    fixture = load_fixture(fixture_path, root)
    require(not output.exists() or not any(output.iterdir()), "试验目录必须为空；请另选运行目录")
    variants, embedding_items, docs = {}, {}, []
    for doc in fixture["documents"]:
        raw = (root / doc["path"]).read_bytes().decode("utf-8")
        docs.append({"path": doc["path"], "sha256": digest((root / doc["path"]).read_bytes()),
                     "characters": len(raw)})
        for mode in MODES:
            for chunk in build_chunks(raw, doc["path"], mode):
                eid = digest("document\0" + chunk["title"] + "\0" + chunk["text"])
                chunk["embedding_id"] = eid
                embedding_items[eid] = {"id": eid, "kind": "document", "title": chunk["title"], "text": chunk["text"]}
                variants.setdefault(mode, []).append(chunk)
    queries = []
    for q in fixture["queries"]:
        eid = digest("query\0" + q["text"])
        embedding_items[eid] = {"id": eid, "kind": "query", "title": "", "text": q["text"]}
        queries.append({**q, "embedding_id": eid})
    payload = {"schema_version": 1, "experiment_version": VERSION,
        "fixture_path": str(fixture_path.relative_to(root)), "fixture_sha256": digest(fixture_path.read_bytes()),
        "annotation": fixture.get("annotation", {}), "documents": docs, "queries": queries,
        "parameters": {"max_chars": 800, "overlap": 120, "bm25_k1": 1.2, "bm25_b": 0.75,
                       "rrf_k": 60, "k": 5, "scope": "shared", "query_expansion": False, "reranking": False},
        "variants": variants}
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "dataset.json", payload)
    write_json(output / "embedding-input.json", {"schema_version": 1,
        "dataset_sha256": digest((output / "dataset.json").read_bytes()), "items": list(embedding_items.values())})
    return {"documents": len(docs), "queries": len(queries),
            "chunks": {m: len(c) for m, c in variants.items()}, "unique_embedding_inputs": len(embedding_items)}


def cosine(left, right):
    require(len(left) == len(right), "向量维度不一致")
    a, b = math.sqrt(sum(x*x for x in left)), math.sqrt(sum(x*x for x in right))
    require(a > 0 and b > 0, "零向量无效")
    return sum(x*y for x, y in zip(left, right)) / (a*b)


def evaluate(root, output):
    dataset = read_json(output / "dataset.json")
    embeddings = read_json(output / "embeddings.json")
    require(embeddings.get("complete") is True, "向量索引尚未完成")
    require(embeddings.get("dataset_sha256") == digest((output / "dataset.json").read_bytes()), "向量索引与样本不一致")
    require(digest((root / dataset["fixture_path"]).read_bytes()) == dataset["fixture_sha256"], "查询标注已变化，需重建试验")
    for doc in dataset["documents"]:
        require(digest(asset_path(root, doc["path"]).read_bytes()) == doc["sha256"], "资料已变化，需重建试验")
    vectors = embeddings["vectors"]
    dim = embeddings["dimensions"]
    require(type(dim) is int and dim > 0, "向量维度无效")
    for vector in vectors.values():
        require(isinstance(vector, list) and len(vector) == dim and
                all(type(n) in (float, int) and math.isfinite(n) for n in vector), "向量内容无效")
    details, aggregate = [], []
    for mode, chunks in dataset["variants"].items():
        by_id = {c["chunk_id"]: c for c in chunks}
        for query in dataset["queries"]:
            started = time.perf_counter()
            lexical = collapse_documents(bm25_rank(query["text"], chunks), len(chunks))
            lexical_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            vector = sorted([{"source_path": c["source_path"], "chunk_id": c["chunk_id"],
                "score": cosine(vectors[query["embedding_id"]], vectors[c["embedding_id"]])} for c in chunks],
                key=lambda hit: (-hit["score"], hit["source_path"], hit["chunk_id"]))
            vector = collapse_documents(vector, len(vector))
            vector_ms = (time.perf_counter() - started) * 1000
            hybrid = rrf_fuse([lexical, vector])
            for method, ranking in (("bm25", lexical), ("vector", vector), ("hybrid", hybrid)):
                top = ranking[:5]
                hits = [{**hit, "start_line": by_id[hit["chunk_id"]]["start_line"],
                         "end_line": by_id[hit["chunk_id"]]["end_line"],
                         "excerpt": by_id[hit["chunk_id"]]["text"],
                         "heading_path": by_id[hit["chunk_id"]]["heading_path"],
                         "labelled_relevant": hit["source_path"] in query["relevant_paths"]} for hit in top]
                metrics = score_ranking([h["source_path"] for h in top], query["relevant_paths"])
                metrics.update(score_evidence(hits, query["evidence"]))
                details.append({"mode": mode, "method": method, "query_id": query["id"],
                    "query": query["text"], "category": query["category"], "split": query["split"],
                    "relevant_paths": query["relevant_paths"], "labelled_evidence": query["evidence"],
                    "metrics": metrics, "hits": hits,
                    "returned_characters": sum(len(h["excerpt"]) for h in hits),
                    "ranking_ms_excludes_embedding": lexical_ms if method == "bm25" else vector_ms if method == "vector" else lexical_ms + vector_ms})
        for method in METHODS:
            for split in ("development", "holdout", "all"):
                group = [d for d in details if d["mode"] == mode and d["method"] == method and (split == "all" or d["split"] == split)]
                positive = [d for d in group if d["relevant_paths"]]
                absent = [d for d in group if not d["relevant_paths"]]
                aggregate.append({"mode": mode, "method": method, "split": split,
                    "answerable_queries": len(positive), "no_answer_queries": len(absent),
                    **{name: sum(d["metrics"][name] for d in positive) / len(positive) if positive else None
                       for name in ("recall_at_k", "mrr_at_k", "hit_at_k", "evidence_recall_at_k", "complete_evidence_at_k")},
                    "no_answer_return_rate": sum(bool(d["hits"]) for d in absent) / len(absent) if absent else None,
                    "mean_returned_characters": sum(d["returned_characters"] for d in group) / len(group) if group else 0})
    result = {"schema_version": 1, "experiment_version": VERSION, "scorer_version": "unique-quotes-v2",
        "fixture_sha256": dataset["fixture_sha256"],
        "annotation": dataset["annotation"], "parameters": dataset["parameters"],
        "embedding": {key: value for key, value in embeddings.items() if key != "vectors"},
        "counts": {"documents": len(dataset["documents"]), "queries": len(dataset["queries"]),
                   "chunks": {key: len(value) for key, value in dataset["variants"].items()}},
        "aggregate": aggregate, "details": details}
    write_json(output / "results.json", result)
    report_path = output / "report.html"
    require(not report_path.is_symlink() and (not report_path.exists() or report_path.stat().st_nlink == 1), "报告路径不安全")
    report_path.write_text(render_report(result), encoding="utf-8")
    return result


def render_report(result):
    esc = lambda value: html.escape(str(value), quote=True)
    pct = lambda value: "—" if value is None else f"{value:.1%}"
    rows, absent_rows = [], []
    for row in result["aggregate"]:
        if row["split"] == "all":
            absent_rows.append("<tr>" + "".join("<td>" + esc(value) + "</td>" for value in (
                row["mode"], row["method"], row["no_answer_queries"], pct(row["no_answer_return_rate"]))) + "</tr>")
            continue
        rows.append("<tr>" + "".join("<td>" + esc(value) + "</td>" for value in (
            row["split"], row["mode"], row["method"], row["answerable_queries"], pct(row["recall_at_k"]),
            pct(row["mrr_at_k"]), pct(row["evidence_recall_at_k"]), pct(row["complete_evidence_at_k"]),
            round(row["mean_returned_characters"]))) + "</tr>")
    queries = []
    for item in result["details"]:
        cards = "".join("<li><b>" + ("命中已标注资料 · " if hit["labelled_relevant"] else "未标为相关 · ")
            + esc(hit["source_path"]) + "</b><small>原文行 " + str(hit["start_line"]) + "–" + str(hit["end_line"])
            + " · 本方法分数 " + f"{hit['score']:.4f}" + "</small><pre>" + esc(hit["excerpt"]) + "</pre></li>" for hit in item["hits"])
        evidence = "".join("<li><b>" + ("已包含 · " if any(
            hit["source_path"] == ref["path"] and ref["quote"] in hit["excerpt"] for hit in item["hits"])
            else "未逐字包含 · ") + esc(ref["path"]) + "</b><blockquote>" + esc(ref["quote"])
            + "</blockquote></li>" for ref in item["labelled_evidence"])
        queries.append('<details id="' + esc(f"{item['query_id']}-{item['mode']}-{item['method']}") + '"><summary>'
            + esc(f"{item['query_id']} · {item['split']} · {item['mode']} / {item['method']} — {item['query']}")
            + "</summary><p>标注相关资料：" + esc(", ".join(item["relevant_paths"]) or "此样本库无答案")
            + "</p><p>逐条标注引文（精确匹配诊断）：</p><ul>" + evidence
            + "</ul><p>本次实际返回片段：</p><ol>" + cards + "</ol></details>")
    counts = result["counts"]
    count_text = f"{counts['documents']} 篇资料 · {counts['queries']} 条查询 · 固定窗口 {counts['chunks']['window']} 个片段 / 结构分块 {counts['chunks']['structure']} 个片段"
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Novel Base · 检索小实验</title><style>body{max-width:1240px;margin:40px auto;padding:0 24px;background:#f5f3ed;color:#203747;font:15px/1.8 system-ui,sans-serif}h1{font-size:32px}h2{margin-top:32px}.note{background:#e7eeee;border-left:3px solid #365e73;padding:16px}table{border-collapse:collapse;width:100%;background:#fffefa;font-size:13px}th,td{border-bottom:1px solid #d7dcd7;text-align:left;padding:10px}details{background:#fffefa;border:1px solid #d7dcd7;border-radius:6px;padding:14px;margin:10px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f3ef;padding:12px;max-height:320px;overflow:auto;font:12px/1.8 monospace}small{display:block;color:#607079}b{overflow-wrap:anywhere}.scroll{overflow-x:auto}</style>
<p>NOVEL BASE / RETRIEVAL PILOT</p><h1>先检验检索，再确定数据格式</h1><p>""" + esc(count_text) + """</p>
<div class="note">同一资料、同一查询与固定标注；比较 800 字符固定窗口及结构分块。关键词基线为中文双字 BM25，向量为本地 EmbeddingGemma，混合为文档去重后的 RRF。未使用查询扩展、重排或正文生成。</div>
<p>相关性标签由代理依据原文编写，尚未经作者独立复核；少量样本用于发现问题。文档命中不等于返回片段可直接使用，更不等于续写质量。不同方法的原始分数不可互相比大小。</p>
<h2>结果对比</h2><p>development 为开发题，holdout 为本轮保留题；window 为固定窗口，structure 为结构分块。Recall@5 是已标注相关文档的召回率；MRR@5 衡量第一份相关文档的排名。每份文档只返回一个片段。</p>
<p>引文覆盖率按唯一的「来源＋引文」逐条计算后按题平均；引文齐备率是全部标注引文都被取回的题目比例。缺少某条引文，不等于片段没有用；引文全部出现，也不保证回答完整。无答案题不进入这些平均值。字符数包含所有题的返回正文，并非 token 数；Top-5 也并非固定上下文预算。</p><div class="scroll"><table><thead><tr><th>查询组</th><th>分块</th><th>检索</th><th>有答案数</th><th>Recall@5</th><th>MRR@5</th><th>引文覆盖率</th><th>引文齐备率</th><th>平均返回字符</th></tr></thead><tbody>""" + "".join(rows) + """</tbody></table></div>
<h2>无答案题的行为</h2><p>当前没有校准拒答机制：向量检索总会返回近邻。下表统计“仍返回至少一个片段”的比例，是系统行为观察，不是模型错误率，也不证明故事项目隔离已实现。</p><table><thead><tr><th>分块</th><th>检索</th><th>无答案题数</th><th>仍返回片段</th></tr></thead><tbody>""" + "".join(absent_rows) + """</tbody></table>
<h2>逐条检查实际返回内容</h2><p>展开后对照标注引文与原文位置。混合检索融合文档排名，展示片段取单路排名更高的那个，平局优先 BM25；没有合并各路证据。不同方法的分数不能直接横向比较。</p>""" + "".join(queries) + "</html>"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "evaluate"))
    parser.add_argument("--fixture", default="experiments/retrieval-pilot/fixture.json")
    parser.add_argument("--output-dir", default="runtime-data/retrieval-pilot/pilot-v1")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        output = safe_output(args.output_dir, root)
        if args.command == "prepare":
            path = Path(args.fixture).resolve()
            require(path.is_relative_to(root), "样本定义须保存在本仓库")
            print(json.dumps(prepare(path, root, output), ensure_ascii=False))
        else:
            result = evaluate(root, output)
            print(json.dumps({"counts": result["counts"], "report": str(output / "report.html")}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("检索试验未完成：" + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
