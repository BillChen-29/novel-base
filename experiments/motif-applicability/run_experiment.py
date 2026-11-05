#!/usr/bin/env python3
"""Replay source-bound AI judgments and show motif continuation proposals.

All shipped stories are original fixtures. No model/API call or memory mutation.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
import html
import json
import os
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))
from semantic_review import prepare_review, _emit, _safe_output, _read_json
from motif_matcher import match_motifs


def indexed(items, key):
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
        raise ValueError('invalid_records')
    values = {}
    for item in items:
        ident = item.get(key)
        if not isinstance(ident, str) or not ident.strip() or ident in values:
            raise ValueError('missing_or_duplicate_' + key)
        values[ident] = item
    return values


def evaluate(fixtures, catalog, reviews, repo_root, run_date):
    date.fromisoformat(run_date)
    projects = indexed(fixtures['projects'], 'project_id')
    cases = indexed(fixtures['cases'], 'id')
    by_review = indexed(reviews['reviews'], 'case_id')
    if set(cases) != set(by_review):
        raise ValueError('review_case_set_mismatch')
    results = []
    judgments = Counter()
    for ident, case in cases.items():
        if case['project_id'] not in projects:
            raise ValueError('unknown_project')
        project = projects[case['project_id']]
        packet = prepare_review(project, case['cutoff_scene_id'], case.get('cutoff_offset'))
        review = by_review[ident]['review']
        result = match_motifs(project, packet, review, catalog, repo_root)
        judgments.update(d['verdict'] for d in review['decisions'])
        allowed = {c['fact_id'] for c in packet['candidates']}
        # General software checks, independent from anticipated semantic labels.
        known = {a['fact_id'] for a in result['atom_view']
                 if a['world'] == 'true' and a['knowledge'].get(project['pov_character']) == 'true'}
        writer_facts = result['writer_packet']['facts']
        used = {f.get('id', f.get('fact_id')) for f in writer_facts}
        checks = {
            'review_bound_to_current_prefix': result['provenance']['packet_sha256'] == packet['packet_sha256'],
            'writer_facts_within_prefix': used <= allowed,
            'writer_facts_supported_for_pov': used <= known,
            'writer_prompt_contains_exact_packet': json.dumps(result['writer_packet'], ensure_ascii=False, indent=2) in result['writer_prompt'],
        }
        results.append({'case_id': ident, 'title': case['title'], 'project_id': project['project_id'],
                        'pov_character': project['pov_character'], 'cutoff': packet['cutoff'],
                        'prefix': packet['scenes'], 'candidate_count': len(packet['candidates']),
                        'checks': checks, 'result': result})
    return {'schema_version': 1, 'run_date': run_date,
            'method': 'replay_current_ai_reviews_no_external_api',
            'limits': ['原创小样检验结构与条件执行；不是语义准确率或续写质量评测。',
                       '母题条件、角色槽位和变体由本轮设计；当前AI判断实例命题，程序不做自由文本抽取。',
                       '母题资料的典型作品归属未作外部查证；新情节均为候选，不写回项目记忆。'],
            'summary': {'cases': len(results), 'candidate_judgments': sum(judgments.values()),
                        'judgments': dict(judgments),
                        'workflow_passed': sum(sum(c['checks'].values()) for c in results),
                        'workflow_total': sum(len(c['checks']) for c in results)},
            'cases': results}


def render_html(report):
    esc = lambda v: html.escape(str(v), quote=True)
    label = {'true': '有支持', 'false': '有反证', 'unknown': '证据不足',
             'eligible': '条件满足', 'blocked': '有反证', 'needs_evidence': '待补证据'}
    kind_label = {'content':'信息内容','carrier':'来源／载体','acquisition_event':'获取事件',
                  'communication_event':'传播事件','world_state':'状态或条件'}
    def state(value):
        return f'<span class="state {esc(value)}">{esc(label.get(value, value))}</span>'
    sections = []
    for i, case in enumerate(report['cases'], 1):
        result = case['result']
        rows = []
        for atom in result['atom_view']:
            rows.append('<tr><td>'+esc(atom['text'])+'</td><td>'+esc(kind_label.get(atom['kind'],atom['kind']))+'</td><td>'+state(atom['world'])+
                        '</td><td>'+state(atom['knowledge'].get(case['pov_character'], 'unknown'))+'</td></tr>')
        motifs = []
        for m in result['author_audit']:
            stage_rows = ''.join('<li>'+esc(s['title'])+' '+state(s['status'])+'</li>' for s in m['stages'])
            motifs.append('<div class="motif"><strong>'+esc(m['title'])+'</strong> '+state(m['entry_status'])+
                          '<ul>'+stage_rows+'</ul></div>')
        proposals = result['writer_packet']['proposals']
        proposal_html = ''.join('<li><strong>'+esc(p.get('title', p.get('variant_id', '方案')))+'</strong><br>'+esc(p.get('proposal', ''))+'</li>' for p in proposals)
        if not proposals:
            proposal_html = '<li>这两项母题当前没有可交给视角写作的承接方案。可继续收集证据；这不代表故事不能继续。</li>'
        prefix = '\n\n'.join(s['text'] for s in case['prefix'])
        sections.append(f'<section id="case-{i}"><p class="eyebrow">样例 {i:02d} · 视角：{esc(case["pov_character"])}</p>'
                        f'<h2>{esc(case["title"])}</h2><details><summary>阅读本次允许的前文</summary><p class="prose">{esc(prefix)}</p></details>'
                        '<h3>逐命题审核</h3><div class="scroll"><table><thead><tr><th>命题</th><th>分类标注</th><th>前文是否支持</th><th>视角是否知情</th></tr></thead><tbody>'+
                        ''.join(rows)+'</tbody></table></div><h3>母题阶段 · 作者核对视图</h3>'+''.join(motifs)+
                        '<h3>可交给当前视角的后续提案</h3><ol>'+proposal_html+'</ol>'+
                        '<details><summary>查看实际写作输入包</summary><pre>'+esc(json.dumps(result['writer_packet'],ensure_ascii=False,indent=2))+'</pre></details></section>')
    nav = ''.join(f'<a href="#case-{i}">{esc(c["title"])}</a>' for i,c in enumerate(report['cases'],1))
    s=report['summary']
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>novel-base · 信息如何变成后续</title><style>' + '''
    :root{color-scheme:light;--ink:#21312e;--muted:#586761;--paper:#f4f2e9;--line:#d7ddd3;--green:#245d50}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.8 system-ui,-apple-system,"PingFang SC",sans-serif}
    main{max-width:1120px;margin:auto;padding:56px 32px 96px}header{padding:12px 0 30px;border-bottom:1px solid var(--line)}
    .eyebrow{font-size:12px;letter-spacing:.12em;color:var(--green);margin:0}h1{font-size:40px;line-height:1.3;margin:12px 0 18px}h2{font-size:26px;line-height:1.5;margin:8px 0 22px}h3{font-size:17px;margin:26px 0 12px}
    .intro{max-width:800px;color:var(--muted)}.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}.steps div{background:#e6ebe1;padding:16px;border-radius:9px}.steps small{display:block;color:var(--muted)}
    .note{border-left:3px solid #92aa9b;padding:6px 18px;color:var(--muted)}nav{display:flex;flex-wrap:wrap;gap:8px;margin:26px 0}a{color:var(--green)}nav a{padding:5px 12px;border:1px solid var(--line);border-radius:20px;font-size:13px;text-decoration:none}
    section{background:#fffef9;padding:30px;border:1px solid var(--line);border-radius:12px;margin:24px 0;scroll-margin-top:18px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th{text-align:left;background:#eef1e9}th,td{padding:12px;border-bottom:1px solid var(--line);vertical-align:top}td:first-child{min-width:280px}td:nth-child(n+3){white-space:nowrap}.state{font-size:12px;border-radius:5px;padding:3px 7px;background:#f0f0ec;color:#63716a}.true,.eligible{background:#dfefe5;color:#215b3b}.false,.blocked{background:#f9e6df;color:#87422a}.unknown,.needs_evidence{background:#f5efd8;color:#7d652b}
    summary{cursor:pointer;color:var(--green);font-size:14px}details{background:#f7f7f1;border-radius:6px;padding:12px 16px}.prose{white-space:pre-wrap}.motif{border-bottom:1px dashed var(--line);padding:12px 0}li{margin-bottom:10px}pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}footer{color:var(--muted);font-size:13px} @media(max-width:650px){main{padding:24px 16px}h1{font-size:29px}.steps{grid-template-columns:1fr 1fr}section{padding:20px}.scroll table,.scroll tbody,.scroll tr,.scroll td{display:block}.scroll thead{display:none}.scroll tr{padding:10px 0;border-bottom:1px solid var(--line)}.scroll td{border:0;padding:3px 0}.scroll td:first-child{min-width:0;font-weight:600}.scroll td:nth-child(n+3){white-space:normal}.scroll td:nth-child(2)::before{content:"分类："}.scroll td:nth-child(3)::before{content:"前文支持："}.scroll td:nth-child(4)::before{content:"视角知情："}}
    ''' + '</style><main><header><p class="eyebrow">NOVEL-BASE / '+esc(report['run_date'])+'</p><h1>信息怎样变成可承接的情节</h1><p class="intro">同一句暗号可以被读到、转告或误听。内容、载体、获取事件与角色知情分别记录，才能判断前文走到了哪里，以及下一步还需要什么。</p>'+
        '<div class="steps"><div>内容命题<small>暗号是什么</small></div><div>来源与载体<small>内容记在哪里</small></div><div>获取与传播<small>怎样读到、听到</small></div><div>逐人知情<small>谁知道哪一项</small></div></div>'+
        f'<p class="note">{s["cases"]} 个前文截点 · {s["candidate_judgments"]} 项候选审核 · {s["workflow_passed"]}/{s["workflow_total"]} 项流程检查。实际 AI 判断已保存，本页重放不调用额外接口。结果用于检查条件执行，不是准确率。</p></header><nav>'+nav+'</nav>'+''.join(sections)+
        '<footer><p>作者核对视图可以看到全局审核结果；实际写作包只含当前视角可用事实和待写提案。未知不等于没发生，收到载体不等于读懂，模板结局不进入历史事实。</p><p>知识来源：assets/motif_library/weaving_story.md；assets/motif_library/forbidden-knowledge.md。条件与变体是本轮可修改的操作化标注。</p></footer></main></html>')


def emit_html(text, output, inputs, repo_root):
    target = _safe_output(Path(output), inputs, REPO, repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    _safe_output(target, inputs, REPO, repo_root)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,prefix='.motif-',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(text)
        os.replace(temporary,target)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    here=Path(__file__).resolve().parent
    parser.add_argument('--fixtures',type=Path,default=here/'fixtures.json')
    parser.add_argument('--catalog',type=Path,default=here/'catalog.json')
    parser.add_argument('--reviews',type=Path,default=here/'reviews.json')
    parser.add_argument('--repo-root',type=Path,default=REPO)
    parser.add_argument('--run-date',required=True)
    parser.add_argument('--output')
    parser.add_argument('--html')
    args=parser.parse_args(argv)
    inputs=[args.fixtures,args.catalog,args.reviews]
    try:
        if args.output: _safe_output(Path(args.output),inputs+([Path(args.html)] if args.html else []),REPO,args.repo_root)
        if args.html: _safe_output(Path(args.html),inputs+([Path(args.output)] if args.output else []),REPO,args.repo_root)
        result=evaluate(*[_read_json(p) for p in inputs],args.repo_root,args.run_date)
        _emit(result,args.output,inputs+([Path(args.html)] if args.html else []),REPO,args.repo_root)
        if args.html: emit_html(render_html(result),args.html,inputs+([Path(args.output)] if args.output else []),args.repo_root)
        return 0 if result['summary']['workflow_passed']==result['summary']['workflow_total'] else 2
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
