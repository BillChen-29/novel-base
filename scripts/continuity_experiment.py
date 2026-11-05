#!/usr/bin/env python3
"""Local prefix-only retrieval audit. Labels are reviewed annotations, not automatic extraction."""
from __future__ import annotations

import argparse
import copy
import html
import json
import math
import re
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import plot_rag_retriever as historical
from narrative_prototype import _validate_project
from retrieval_pilot import bm25_rank, build_chunks, cosine, digest, read_json, require, safe_output, write_json
from story_graph_builder import GraphConfig, cmd_context

VERSION = 'continuity-audit-v1'


def validate_case(case):
    require(isinstance(case.get('id'), str) and re.fullmatch(r'[a-zA-Z0-9_-]+', case['id']), 'Invalid case ID')
    require(isinstance(case.get('prefix'), str) and case['prefix'].strip(), 'Missing prefix')
    require(case.get('order_review', {}).get('eligible') is True, 'Sequence has not passed order review')
    require(bool(case['order_review'].get('reason')), 'Missing order-review evidence')
    require(type(case.get('prefix_start')) is int and type(case.get('prefix_end')) is int
            and 0 <= case['prefix_start'] < case['prefix_end'], 'Invalid prefix span')
    require(len(case['prefix']) == case['prefix_end'] - case['prefix_start'], 'Prefix length does not match span')
    require(type(case.get('next_start')) is int and case['next_start'] >= case['prefix_end'], 'Continuation overlaps prefix')
    require(isinstance(case.get('goal'), str) and case['goal'].strip(), 'Missing prefix-derived goal')
    require(isinstance(case.get('facts'), list) and case['facts'], 'Missing evidence annotations')
    characters = set(case.get('characters', []))
    require(bool(characters) and case.get('pov_character') in characters, 'Invalid character or viewpoint IDs')
    ids = set()
    for fact in case['facts']:
        require(isinstance(fact.get('id'), str) and fact['id'] not in ids, 'Duplicate or missing fact ID')
        ids.add(fact['id'])
        require(isinstance(fact.get('text'), str) and bool(fact['text'].strip()), 'Empty fact')
        require(isinstance(fact.get('quote'), str) and bool(fact['quote'].strip())
                and fact['quote'] in case['prefix'], 'Evidence quote is not in permitted prefix')
        require(set(fact.get('known_by', [])).issubset(characters), 'Unknown character in knowledge annotation')
        require(bool(fact.get('epistemic_status')), 'Missing epistemic status')


def query_variants(case):
    # Deliberately whitelist permitted fields. Sealed continuation is never read here.
    return {'raw': case['prefix'][-800:],
            'state': '当前目标：' + case['goal'] + '\n' + '\n'.join(
                '[' + fact['epistemic_status'] + '] ' + fact['text'] for fact in case['facts'])}


def source_ref(path, source, start, end):
    return {'source_path': path, 'start': start, 'end': end,
            'start_line': source.count('\n', 0, start) + 1,
            'end_line': source.count('\n', 0, max(start, end - 1)) + 1,
            'quote': source[start:end]}


def build_knowledge_records(root):
    records = []
    for path in sorted((root / 'assets/motif_library').glob('*.md')):
        source = path.read_bytes().decode('utf-8')
        name = path.relative_to(root).as_posix()
        title = source.splitlines()[0].lstrip('# ').strip()
        matches = list(re.finditer(r'^##\s+(.+)$', source, re.M))
        sections = [(m[1].strip(), m.start(), matches[i + 1].start() if i + 1 < len(matches) else len(source))
                    for i, m in enumerate(matches)]
        selected = [(h, a, b) for h, a, b in sections if h in ('一句话定义', '叙事结构模板', '不适用场景')]
        definition = next((source[a:b] for h, a, b in sections if h == '一句话定义'), '')
        constraints = next((source[a:b] for h, a, b in sections if h == '不适用场景'), '')
        parent = 'entry-' + path.stem
        base = {'source_path': name, 'source_sha256': digest(source), 'parent_title': title,
                'constraints_text': constraints, 'classification_status': 'structural_candidate_not_semantically_verified'}
        records.append({**base, 'id': parent, 'kind': 'pattern', 'parent_id': None, 'title': title,
                        'text': '\n'.join(source[a:b] for _, a, b in selected),
                        'source_refs': [source_ref(name, source, a, b) for _, a, b in selected]})
        for heading, start, end in sections:
            if heading not in ('常见情境原型', '经典情境原型'):
                continue
            blocks = list(re.finditer(r'^[-*]\s+', source[start:end], re.M))
            for i, block in enumerate(blocks):
                a = start + block.start()
                b = start + blocks[i + 1].start() if i + 1 < len(blocks) else end
                raw = source[a:b].rstrip()
                b = a + len(raw)
                records.append({**base, 'id': f'{parent}-context-{a}', 'kind': 'situation',
                    'parent_id': parent, 'title': title + ' / 情境或案例候选',
                    'text': definition + '\n' + raw,
                    'source_refs': [source_ref(name, source, a, b)]})
    return records


def read_source_case(case):
    validate_case(case)
    path = Path(case['source_path']).expanduser().resolve()
    require(path.suffix.lower() == '.txt', 'This pilot verifies plain-text novels only')
    raw = path.read_bytes()
    require(digest(raw) == case['source_sha256'], 'Novel source hash changed')
    source = raw.decode(case['encoding'])
    if case.get('normalized_newlines'):
        source = source.replace('\r\n', '\n').replace('\r', '\n')
    require(source[case['prefix_start']:case['prefix_end']] == case['prefix'], 'Prefix offsets do not match source')
    require(source[case['next_start']:case['next_end']] == case['actual_next'], 'Continuation offsets do not match source')
    return source


def prepare(root, selection, output):
    require(not output.exists() or not any(output.iterdir()), 'Use a fresh empty run directory')
    source_selection = read_json(selection)
    source_cases = source_selection['cases']
    require(bool(source_cases) and len({c['id'] for c in source_cases}) == len(source_cases), 'Missing or duplicate cases')
    cases, sealed = [], []
    for case in source_cases:
        read_source_case(case)
        # The model-facing dataset has no continuation text or continuation-derived labels.
        permitted = {key: copy.deepcopy(case[key]) for key in (
            'id', 'book_id', 'title', 'source_path', 'source_sha256', 'encoding', 'normalized_newlines',
            'prefix', 'prefix_start', 'prefix_end', 'facts', 'characters', 'character_metadata',
            'pov_character', 'goal', 'order_review') if key in case}
        permitted['queries'] = query_variants(permitted)
        cases.append(permitted)
        sealed.append({'case_id': case['id'], 'actual_next': case['actual_next'],
                       'next_start': case['next_start'], 'next_end': case['next_end']})
    records = build_knowledge_records(root)
    items, chunks = {}, []
    for record in records:
        for chunk in build_chunks(record['text'], record['source_path'], 'window', 800, 120):
            eid = digest('document\0' + record['title'] + '\0' + chunk['text'])
            items[eid] = {'id': eid, 'kind': 'document', 'title': record['title'], 'text': chunk['text']}
            chunks.append({'chunk_id': record['id'] + ':' + str(chunk['start']), 'record_id': record['id'],
                           'source_path': record['id'], 'title': record['title'], 'text': chunk['text'], 'embedding_id': eid})
    for case in cases:
        case['embedding_ids'] = {}
        for mode, query in case['queries'].items():
            eid = digest('query\0' + query)
            case['embedding_ids'][mode] = eid
            items[eid] = {'id': eid, 'kind': 'query', 'title': '', 'text': query}
    dataset = {'schema_version': 1, 'experiment_version': VERSION, 'run_date': '2026-10-19',
               'selection_path': str(selection), 'selection_sha256': digest(selection.read_bytes()),
               'cases': cases, 'records': records, 'chunks': chunks,
               'method': {'top_k_each_kind': 3, 'query_raw_chars': 800, 'state_annotation': 'agent_reviewed_not_auto_extraction',
                          'interpretation': 'No relevance gold or continuation-quality accuracy is claimed.'}}
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / 'dataset.json', dataset)
    write_json(output / 'sealed-comparison.json', {'cases': sealed})
    write_json(output / 'embedding-input.json', {'schema_version': 1,
        'dataset_sha256': digest((output / 'dataset.json').read_bytes()), 'items': list(items.values())})
    return {'cases': len(cases), 'books': len({c['book_id'] for c in cases}),
            'entries': sum(r['kind'] == 'pattern' for r in records),
            'context_candidates': sum(r['kind'] == 'situation' for r in records), 'embeddings': len(items)}


def historical_case(case, output):
    project = output / 'prefix-projects' / case['id']
    manuscript, memory = project / '03_manuscript', project / '00_memory'
    require(not project.exists(), 'Prefix snapshot already exists; evaluation must use a fresh snapshot name')
    manuscript.mkdir(parents=True)
    memory.mkdir()
    (manuscript / '第1章_审定连续片段.md').write_text(case['prefix'], encoding='utf-8')
    characters = case.get('characters') or [case.get('pov_character', '未指定人物')]
    (memory / 'character_tracker.md').write_text('|人物|\n|---|\n' + ''.join('|' + n + '|\n' for n in characters), encoding='utf-8')
    index = historical.build_index(project)
    retrievals = {}
    for mode, query in case['queries'].items():
        result = historical.retrieve(index, project, query, top_k=3, candidate_k=10, per_chapter=3, passage_max_chars=360)
        texts = [p['text'] for hit in result['retrieved'] for p in hit['passages']]
        result['quote_coverage'] = {f['id']: any(f['quote'] in t for t in texts) for f in case['facts']}
        result['scope_note'] = 'Only a local continuous excerpt exists in this project; this is not a long-book retrieval benchmark.'
        retrievals[mode] = result
    # The graph is explicitly seeded from reviewed prefix annotations; not extracted by production code.
    # Current graph exposes event nodes only. Keep epistemic status visible in the
    # description: a future arrangement or inference must not read as completed truth.
    nodes = [{'id': f['id'], 'type': 'event', 'chapter': 1,
              'description': '[' + f['epistemic_status'] + '] ' + f['text'],
              'epistemic_status': f['epistemic_status'],
              'known_by': f.get('known_by', []), 'evidence': {'quote': f['quote'], 'source': case['source_path']}}
             for f in case['facts']]
    graph = {'version': '1.0', 'nodes': nodes, 'edges': [], 'timeline': []}
    write_json(memory / 'story_graph.json', graph)
    graph_result = cmd_context(Namespace(project_root=str(project), chapter=1, max_events=20, max_foreshadows=10), GraphConfig())
    known_by = [f for f in case['facts'] if f.get('known_by')]
    pov = case.get('pov_character') or characters[0]
    fixture = {'schema_version': 1, 'project_id': case['id'], 'title': case['title'], 'pov_character': pov,
               'characters': characters, 'goal': {'id': 'recover_and_investigate', 'description': case['goal']},
               'scenes': [{'id': 'prefix', 'order': 1, 'function': 'audit', 'tension': 3,
                           'text': case['prefix'], 'present_characters': characters}],
               'facts': [{'id': f['id'], 'text': f['text'], 'quote': f['quote'], 'scene_id': 'prefix',
                          'known_by': f.get('known_by', [])} for f in case['facts']], 'threads': []}
    _validate_project(fixture)
    bad = copy.deepcopy(fixture)
    bad['facts'][0]['quote'] = 'AUDIT_INVALID_QUOTE_491a36b1'
    invalid_rejected = False
    try:
        _validate_project(bad)
    except ValueError:
        invalid_rejected = True
    return {'history': retrievals, 'graph': graph_result, 'graph_origin': 'manually_seeded_prefix_annotations',
            'citations': {'valid_quotes_accepted': len(case['facts']), 'absent_quote_rejected': invalid_rejected,
                          'semantic_entailment_checked': False, 'known_by_annotated_facts': len(known_by)}}


def evaluate(root, output):
    dataset = read_json(output / 'dataset.json')
    embeddings = read_json(output / 'embeddings.json')
    require(embeddings.get('complete') is True, 'Embedding index incomplete')
    require(embeddings['dataset_sha256'] == digest((output / 'dataset.json').read_bytes()), 'Dataset changed')
    require(digest(Path(dataset['selection_path']).read_bytes()) == dataset['selection_sha256'], 'Selection changed')
    for case in dataset['cases']:
        require(digest(Path(case['source_path']).read_bytes()) == case['source_sha256'], 'Novel changed')
    for record in dataset['records']:
        require(digest((root / record['source_path']).read_bytes()) == record['source_sha256'], 'Knowledge changed')
    require(not (output / 'prefix-projects').exists(), 'Evaluation snapshots already exist; preserve this run and use a new run directory')
    vectors = embeddings['vectors']
    required_ids = {c['embedding_id'] for c in dataset['chunks']} | {
        eid for c in dataset['cases'] for eid in c['embedding_ids'].values()}
    validate_vectors(vectors, required_ids, embeddings.get('dimensions'))
    records = {r['id']: r for r in dataset['records']}
    chunks = dataset['chunks']
    by_chunk = {c['chunk_id']: c for c in chunks}
    results = []
    for case in dataset['cases']:
        runs = []
        for mode, query in case['queries'].items():
            vector_ranking = sorted([{'chunk_id': c['chunk_id'], 'source_path': c['record_id'],
                'score': cosine(vectors[case['embedding_ids'][mode]], vectors[c['embedding_id']])} for c in chunks],
                key=lambda x: (-x['score'], x['source_path']))
            for method, ranked in (('bm25', bm25_rank(query, chunks)), ('vector', vector_ranking)):
                for kind in ('pattern', 'situation'):
                    seen, hits = set(), []
                    for hit in ranked:
                        rid = hit['source_path']
                        record = records[rid]
                        if record['kind'] != kind or rid in seen:
                            continue
                        seen.add(rid)
                        hits.append({**record, 'score': hit['score'], 'matched_text': by_chunk[hit['chunk_id']]['text']})
                        if len(hits) == 3:
                            break
                    runs.append({'query_mode': mode, 'method': method, 'kind': kind, 'hits': hits})
        results.append({'id': case['id'], 'title': case['title'], 'book_id': case['book_id'],
                        'prefix': case['prefix'], 'goal': case['goal'], 'facts': case['facts'],
                        'queries': case['queries'], 'order_review': case['order_review'],
                        'source_path': case['source_path'], 'prefix_start': case['prefix_start'], 'prefix_end': case['prefix_end'],
                        'runs': runs, 'runtime': historical_case(case, output)})
    output_data = {'schema_version': 1, 'experiment_version': VERSION, 'run_date': dataset['run_date'],
        'dataset_sha256': embeddings['dataset_sha256'], 'selection_sha256': dataset['selection_sha256'],
        'counts': {'cases': len(results), 'books': len({c['book_id'] for c in results}),
                   'entries': sum(r['kind'] == 'pattern' for r in records.values()),
                   'context_candidates': sum(r['kind'] == 'situation' for r in records.values())},
        'embedding': {k: v for k, v in embeddings.items() if k not in ('vectors', 'query_embedding_ms')},
        'cases': results}
    write_json(output / 'results.json', output_data)
    write_html(output / 'report.html', render_report(output_data))
    return output_data['counts']


def validate_vectors(vectors, required_ids, dimensions):
    require(type(dimensions) is int and dimensions > 0, 'Invalid vector dimensions')
    require(set(vectors) == required_ids, 'Missing or extra embedding IDs')
    for vector in vectors.values():
        require(isinstance(vector, list) and len(vector) == dimensions
                and all(type(v) in (int, float) and math.isfinite(v) for v in vector)
                and any(v != 0 for v in vector), 'Invalid embedding vector')


def write_html(path, content):
    require(not path.is_symlink() and (not path.exists() or path.stat().st_nlink == 1),
            'HTML output must not be a symbolic or hard link')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def render_report(result):
    esc = lambda s: html.escape(str(s), quote=True)
    body = []
    for case in result['cases']:
        rows = []
        for run in case['runs']:
            hits = ''.join('<details><summary>' + esc(h['title']) + '</summary><small>'
                + esc(h['source_path']) + ' · score=' + esc(round(h['score'], 4))
                + '</small><pre>' + esc(h['matched_text']) + '</pre><p>源文适用限制（待审，不作为硬规则）：</p><pre>'
                + esc(h['constraints_text']) + '</pre></details>' for h in run['hits'])
            rows.append('<tr><td>' + esc(run['query_mode']) + '</td><td>' + esc(run['method'])
                        + '</td><td>' + ('原条目' if run['kind'] == 'pattern' else '情境／案例段候选') + '</td><td>' + hits + '</td></tr>')
        fact_rows = ''.join('<li>[' + esc(f['epistemic_status']) + '] ' + esc(f['text'])
            + '<blockquote>' + esc(f['quote']) + '</blockquote></li>' for f in case['facts'])
        history = ''.join('<h4>' + esc(mode) + ' 历史召回</h4><p>标注引文逐条覆盖：'
            + esc(row['quote_coverage']) + '</p>' + ''.join('<pre>' + esc(p['text']) + '</pre>' for h in row['retrieved'] for p in h['passages'])
            for mode, row in case['runtime']['history'].items())
        body.append('<section><h2>' + esc(case['id'] + ' · ' + case['title']) + '</h2><p>'
            + esc(case['order_review'].get('reason', '')) + '</p><p>前缀目标（标注）：' + esc(case['goal']) + '</p>'
            + '<details><summary>已审定前文与原文位置</summary><p>' + esc(case['source_path'])
            + ' · 字符区间 [' + str(case['prefix_start']) + ',' + str(case['prefix_end']) + ')</p><pre>' + esc(case['prefix'])
            + '</pre></details><details><summary>前文状态与引文（人工标注输入）</summary><ul>' + fact_rows + '</ul></details>'
            + '<table><thead><tr><th>查询</th><th>检索</th><th>数据层</th><th>实际 Top-3</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table><details><summary>检查原有历史检索／图谱／引用的实际输出</summary>' + history
            + '<h4>图谱上下文（由标注种入图谱）</h4><pre>' + esc(case['runtime']['graph']['context_prompt'])
            + '</pre><p>' + esc(case['runtime']['citations']) + '</p></details></section>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Novel Base · 真实前文实验</title>
<style>body{max-width:1180px;margin:36px auto;padding:0 24px;background:#f6f4ee;color:#203747;font:15px/1.8 system-ui}h1{font-size:30px}section{margin:32px 0;padding:20px;background:#fffefa;border:1px solid #d7dcd7}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}small{display:block;color:#647278;overflow-wrap:anywhere}details{padding:12px;background:#eef2ee;margin:12px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;font:13px/1.8 monospace}blockquote{border-left:3px solid #8ca2a7;padding-left:12px}.note{background:#e5eeef;padding:16px}</style>
<p>NOVEL BASE / CONTINUITY AUDIT</p><h1>从真实小说前文出发，检查检索与记忆</h1><p>''' + esc(
        f"{result['counts']['books']} 本小说 · {result['counts']['cases']} 个截点 · {result['counts']['entries']} 个原条目 · {result['counts']['context_candidates']} 个情境／案例候选") + '''</p>
<div class="note">raw：截点前最后 800 字符；state：只根据截点前原文标注的目标与状态。后续原文单独封存，不进入检索、图谱或向量输入。本轮没有调用正文生成模型。</div>
<p>本轮按来源结构提取全部原条目与情境／案例候选，没有把所有条目都认定为纯母题。状态由代理阅读标注，不代表已实现自动抽取。两种查询长度不同；无独立相关性金标，排名变化不能直接当准确率提升。</p>
<p>原有历史检索只在隔离的前缀快照运行；这避免了未来文本进入本次实验，但不证明主写作流程已有截点隔离。图谱被人工种入状态，引用检查只证明引文存在，不证明解释正确。同书截点相关，不能当独立泛化样本。</p>''' + ''.join(body) + '</html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'evaluate'))
    parser.add_argument('--selection', default='runtime-data/continuity-audit/source-selection.json')
    parser.add_argument('--output-dir', default='runtime-data/continuity-audit/run-v1')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = safe_output(args.output_dir, root)
    try:
        result = prepare(root, Path(args.selection).resolve(), output) if args.command == 'prepare' else evaluate(root, output)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('Continuity experiment failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
