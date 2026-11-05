#!/usr/bin/env python3
"""Verify real curated prefixes reach prepare-only prompts without suffix leakage.

This is an information-boundary test, not generation or semantic evaluation.
The input and detailed outputs contain local novel extracts and must stay ignored.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def guard_output(path: Path, protected=()) -> None:
    if path.resolve() in {p.resolve() for p in protected}:
        raise ValueError('output_overlaps_source: ' + str(path))
    for part in (path, *path.parents):
        if part.is_symlink() or (part.is_file() and part.stat().st_nlink != 1):
            raise ValueError('unsafe_output_link: ' + str(part))


def write_json(path: Path, value: object) -> None:
    guard_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.prefix-result-', delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def unique_next_sentence(case: dict) -> str:
    prefix = case['prefix']
    for line in case['actual_next'].splitlines():
        sentence = line.strip()
        if len(sentence) >= 12 and sentence not in prefix:
            return sentence
    raise ValueError('no unique withheld sentence: ' + case['id'])


def verify_case(case: dict, output: Path, source_text: str) -> dict:
    if not isinstance(case.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', case['id']):
        raise ValueError('invalid_case_id')
    prefix, suffix = case['prefix'], case['actual_next']
    assert prefix == source_text[case['prefix_start']:case['prefix_end']]
    assert suffix == source_text[case['next_start']:case['next_end']]
    assert case['prefix_end'] == case['next_start']
    assert case['order_review']['eligible']
    case_root = output / case['id']
    guard_output(case_root)
    case_root.mkdir(parents=True, exist_ok=False)
    manuscript_dir = case_root / '03_manuscript'
    manuscript_dir.mkdir()
    chapter = manuscript_dir / '第1章 截点验证.md'
    future_chapter = manuscript_dir / '第3章 未来验证.md'
    future_marker = 'FUTURE_CANARY_' + case['id']
    private_marker = 'POV_PRIVATE_CANARY_' + case['id']
    chapter.write_bytes((prefix + suffix + '\n\n' + future_marker).encode('utf-8'))
    future_chapter.write_text(future_marker + '_LATER_CHAPTER', encoding='utf-8')
    before_hashes = {p.name: sha(p.read_bytes()) for p in manuscript_dir.glob('*.md')}
    graph_nodes = []
    for fact in case['facts']:
        start, end = fact['start'] - case['prefix_start'], fact['end'] - case['prefix_start']
        assert 0 <= start < end <= len(prefix)
        assert prefix[start:end] == fact['quote']
        graph_nodes.append({'id': fact['id'], 'type': 'event', 'chapter': 1,
            'description': fact['text'], 'known_by': fact['known_by'],
            'epistemic_status': fact['epistemic_status'],
            'source_position': {'chapter': 1, 'end': end},
            'source_refs': [{'source_path': '03_manuscript/' + chapter.name,
                'chapter': 1, 'start': start, 'end': end, 'quote': fact['quote'],
                'source_sha256': before_hashes[chapter.name]}]})
    # Put negative controls first so a missing filter cannot hide behind max_events=5.
    graph_nodes = [
        {'id': 'future-control', 'type': 'event', 'chapter': 3,
         'source_position': {'chapter': 3, 'end': 1},
         'description': future_marker, 'known_by': [case['pov_character']]},
        {'id': 'private-control', 'type': 'event', 'chapter': 1,
         'source_position': {'chapter': 1, 'end': 1},
         'description': private_marker, 'known_by': ['CONTROL_OTHER_POV']},
    ] + graph_nodes
    write_json(case_root / '00_memory/story_graph.json',
        {'version': '1.0', 'nodes': graph_nodes, 'edges': [], 'timeline': []})
    command = [sys.executable, str(REPO / 'scripts/novel_flow_executor.py'),
        'continue-write', '--project-root', str(case_root), '--chapter-file', str(chapter),
        '--query', case['goal'], '--prepare-only', '--cutoff-chapter', '1',
        '--cutoff-offset', str(len(prefix)), '--pov-character', case['pov_character'],
        '--force-retrieval', '--no-research']
    proc = subprocess.run(command, capture_output=True, text=True, timeout=120,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    (case_root / 'command-stderr.txt').write_text(proc.stderr, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(f"{case['id']}: {proc.stdout[-2000:]} {proc.stderr[-1000:]}")
    result = json.loads(proc.stdout)
    write_json(case_root / 'prepare-result.json', result)
    if not result.get('ok'):
        raise RuntimeError(f"{case['id']}: {result}")
    prompt = Path(result['prepared_prompt_file']).read_text(encoding='utf-8')
    constraints = result['writing_constraints']
    graph = constraints['graph_context']
    retrieved = result['query_result']['result']['retrieved']
    passages = [p for doc in retrieved for p in doc['passages']]
    refs = graph['evidence_refs']
    selected_facts = [f for f in case['facts'] if case['pov_character'] in f['known_by']][:5]
    expected_quotes = {f['quote'] for f in selected_facts}
    withheld = unique_next_sentence(case)
    omissions = graph['omissions']
    after_hashes = {p.name: sha(p.read_bytes()) for p in manuscript_dir.glob('*.md')}
    checks = {
        'prepare_only_succeeded': result.get('prepared_only') is True,
        'declared_model_not_called': result.get('model_called') is False,
        'manuscripts_byte_identical': before_hashes == after_hashes,
        'complete_prefix_in_actual_prompt': prefix in prompt,
        'context_tail_exactly_prefix': constraints['continuity_context']['previous_ending'] == prefix,
        'withheld_unique_paragraph_absent': withheld not in prompt,
        'future_canaries_absent': future_marker not in prompt,
        'pov_private_canary_absent': private_marker not in prompt,
        'retrieval_nonempty': bool(passages),
        'retrieval_only_boundary_chapter': bool(retrieved) and all(
            d['chapter_no'] == 1 and d['visible_chars'] == len(prefix) for d in retrieved),
        'retrieved_quotes_match_allowed_prefix': bool(passages) and all(
            0 <= p['start'] < p['end'] <= len(prefix) and
            p['text'] == prefix[p['start']:p['end']] and
            Path(p['source_path']).resolve() == chapter.resolve() and
            p['source_sha256'] == before_hashes[chapter.name] for p in passages),
        'graph_has_expected_visible_events': graph['event_count'] == len(selected_facts),
        'graph_quotes_exactly_selected_source_facts': bool(refs) and {r['quote'] for r in refs} == expected_quotes,
        'graph_refs_match_allowed_prefix': bool(refs) and all(
            0 <= r['start'] < r['end'] <= len(prefix) and
            r['quote'] == prefix[r['start']:r['end']] and
            r['source_sha256'] == before_hashes[chapter.name] for r in refs),
        'graph_time_control_excluded': any(o['reason'] == 'no_state_at_cutoff' for o in omissions),
        'graph_pov_control_excluded': any(o['reason'] == 'knowledge_not_confirmed' for o in omissions),
        'returned_cutoff_matches': result['source_cutoff'] == {'chapter': 1, 'offset': len(prefix)},
    }
    return {'id': case['id'], 'title': case['title'], 'case_group': case['derived_case_group'],
        'prefix_chars': len(prefix), 'withheld_chars': len(suffix),
        'facts_seeded': len(case['facts']), 'graph_events_visible': graph['event_count'],
        'graph_reference_count': len(refs), 'retrieved_passage_count': len(passages),
        'prefix_sha256': sha(prefix.encode('utf-8')),
        'manuscript_sha256_before': before_hashes[chapter.name],
        'manuscript_sha256_after': after_hashes[chapter.name],
        'checks': checks, 'passed': all(checks.values()),
        'local_only': {'project_root': str(case_root), 'prompt_file': result['prepared_prompt_file'],
            'withheld_unique_paragraph': withheld, 'command': command}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, default=REPO/'runtime-data/continuity-audit/source-selection.json')
    parser.add_argument('--output', type=Path, default=REPO/'runtime-data/continuity-repair')
    parser.add_argument('--summary', type=Path, default=REPO/'experiments/continuity-audit/repair-prefix-summary.json')
    parser.add_argument('--run-date', default=dt.date.today().isoformat())
    parser.add_argument('--source-dir', type=Path, help='Optional relocated directory containing the exact two source filenames; hashes must still match')
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text(encoding='utf-8'))
    run_dir = args.output / 'real-cases' / dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    source_texts, source_paths, hashes = {}, {}, {}
    for book in selection['books']:
        path = (args.source_dir / Path(book['source_path']).name) if args.source_dir else Path(book['source_path'])
        raw = path.read_bytes()
        assert sha(raw) == book['source_sha256'], 'source changed: ' + book['book_id']
        source_paths[book['book_id']] = path
        source_texts[book['book_id']] = raw.decode('utf-8')
        hashes[book['book_id']] = sha(raw)
    protected = [args.selection, *source_paths.values()]
    for output_path in (args.output, run_dir, args.summary, args.output/'real-prefix-results.json',
                        args.output/'real-prefix-results.md'):
        guard_output(output_path, protected)
    case_ids = [case['id'] for case in selection['cases']]
    if not case_ids or len(case_ids) != len(set(case_ids)) or any(
            not isinstance(case_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', case_id)
            for case_id in case_ids):
        raise ValueError('invalid_case_ids: use unique nonempty single-component IDs')
    cases = [verify_case(c, run_dir, source_texts[c['book_id']]) for c in selection['cases']]
    sources_unchanged = all(sha(p.read_bytes()) == hashes[k] for k, p in source_paths.items())
    limitations = [
        'Two locally forward episodes from two novels, each with two overlapping cutpoints; four cases are not four independent samples.',
        'The 19 source facts and known_by labels were previously annotated by AI reading the source, not an independent human gold set.',
        'Checks establish prompt information boundaries and byte preservation, not entailment, automatic POV correctness, motif relevance, or generation quality.',
        'No novel generation or embedding API is invoked by prepare-only; model_called is the runtime-declared flag, not independent network telemetry.',
        'Full suffix remains on disk in the same manuscript; it is intentionally withheld from retrieved evidence and the final expansion prompt.',
        'Graph context is capped at five visible events per case; source facts beyond that cap remain in the graph but are not all injected.',
    ]
    detailed = {'schema_version': 1, 'run_date': args.run_date,
        'evaluation': 'real-prefix actual prepare-only pipeline boundary verification',
        'source_books_unchanged': sources_unchanged, 'case_count': len(cases),
        'passed_cases': sum(c['passed'] for c in cases),
        'checks_passed': sum(sum(c['checks'].values()) for c in cases),
        'checks_total': sum(len(c['checks']) for c in cases),
        'facts_seeded': sum(c['facts_seeded'] for c in cases),
        'limitations': limitations, 'cases': cases}
    write_json(args.output/'real-prefix-results.json', detailed)
    public = dict(detailed, cases=[{k:v for k,v in c.items() if k != 'local_only'} for c in cases])
    write_json(args.summary, public)
    lines = ['# 真实前文截点验证', '',
        f"日期：{args.run_date}。{detailed['passed_cases']}/{len(cases)} 个截点通过，"
        f"{detailed['checks_passed']}/{detailed['checks_total']} 项边界检查通过。", '',
        '将前文和真实后续放在同一文件，再由真实继续写入口按截点准备扩写提示。未生成小说。', '',
        '| 小说 / 截点 | 前文字符 | 隐藏后文字符 | 图谱事实（输入 / 可见） | 结果 |',
        '| --- | ---: | ---: | ---: | --- |']
    for c in cases:
        lines.append(f"| {c['title']} / {c['id']} | {c['prefix_chars']} | {c['withheld_chars']} | {c['facts_seeded']} / {c['graph_events_visible']} | {'通过' if c['passed'] else '未通过'} |")
    lines += ['', '## 检查范围', '',
        '实际扩写提示保留完整前文，排除抽查的后文段落及未来哨兵；正文检索与图谱引用均可回到截点前的原文字符位置；显式未向视角人物公开的图谱负对照被排除；试验正文和下载原书的字节散列保持不变。', '',
        '## 解释限制', '',
        '这是两本小说各一段局部顺叙事件的两个重叠截点，不是四部独立小说。19 条事实和知情范围沿用 AI 阅读标注；通过这些检查不代表系统能自动正确提取事实、判断引文含义或生成优质续写。图谱每次最多注入 5 个事件。', '',
        '“未调用模型”依据 prepare-only 入口的执行路径与返回标志；本脚本没有独立记录网络请求。', '',
        '## 本地详细结果', '']
    for c in cases:
        lines.append(f"- {c['id']}：[实际扩写提示]({c['local_only']['prompt_file']})。")
        for name, passed in c['checks'].items():
            if not passed:
                lines.append(f'  - 未通过：{name}')
    (args.output/'real-prefix-results.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    if any(sha(p.read_bytes()) != hashes[k] for k, p in source_paths.items()):
        raise ValueError('source_changed_during_verification')
    print(json.dumps({k: public[k] for k in ['run_date','case_count','passed_cases','checks_passed','checks_total','facts_seeded','source_books_unchanged']}, ensure_ascii=False))
    return 0 if all(c['passed'] for c in cases) and sources_unchanged else 1


if __name__ == '__main__':
    raise SystemExit(main())
