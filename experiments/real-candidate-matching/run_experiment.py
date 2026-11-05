#!/usr/bin/env python3
"""A fixed candidate-set experiment on source-verified prefixes and originals."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
import hashlib
import html
import json
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(REPO/'scripts'))
sys.path.insert(0,str(HERE))
from knowledge_candidate_preparer import prepare_candidates
from motif_matcher import match_motifs
from semantic_review import _digest
from recipes import instances

REAL_IDS={'review-old-lord-monitor','review-organs-forensic-inference'}
LABELS={'review-old-lord-monitor':'真实片段 A：监控观察',
        'review-organs-forensic-inference':'真实片段 B：验尸推断',
        'public-obstructed-inquiry':'原创对照：调查遭到阻挠',
        'public-confirmed-answer':'原创对照：答案已经确认'}

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def fresh_dir(value):
    p=Path(value).expanduser().absolute()
    if any(x.is_symlink() for x in (p,*p.parents)):
        raise ValueError('Output links are forbidden')
    if not p.resolve().is_relative_to((REPO/'runtime-data').resolve()) or p.exists():
        raise ValueError('Use a fresh directory under this repository runtime-data')
    p.mkdir(parents=True,exist_ok=False)
    return p

def public_prepared(catalog):
    return [{'case_id':p['project_id'],'base_fact_ids':[f['id'] for f in p['facts']],
             **prepare_candidates(p,catalog,instances(p),REPO)}
            for p in read(HERE/'public-fixtures.json')['projects']]

def frozen_real(source_dir):
    base=REPO/'runtime-data/semantic-review/2026-10-25-input-v1'
    manifest=read(base/'manifest.json')
    if sha(base/'projects.json')!=manifest['projects_sha256']:
        raise ValueError('Frozen project content changed')
    projects=[p for p in read(base/'projects.json')['projects'] if p['project_id'] in REAL_IDS]
    if len(projects)!=2 or {p['project_id'] for p in projects}!=REAL_IDS:
        raise ValueError('Missing or duplicate curated prefix')
    sources=[]
    expected={Path(p).name:h for p,h in manifest['source_books'].items()}
    directory=Path(source_dir).resolve()
    for p in projects:
        name=p['title']+'.txt'
        if Path(name).name!=name or name not in expected:
            raise ValueError('Invalid source filename')
        path=(directory/name).resolve()
        if not path.is_relative_to(directory):raise ValueError('Source path escapes supplied directory')
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=expected[name]:raise ValueError('Novel source hash changed')
        prefix=p['scenes'][0]['text'];text=raw.decode('utf-8')
        if len(p['scenes'])!=1 or text.count(prefix)!=1:raise ValueError('Prefix not uniquely located')
        start=text.index(prefix)
        sources.append(dict(project_id=p['project_id'],source_path=str(path),source_sha256=digest,
                            prefix_start=start,prefix_end=start+len(prefix)))
    return projects,sources

def prepare(args):
    date.fromisoformat(args.run_date)
    catalog=read(HERE/'catalog.json')
    cases=public_prepared(catalog);sources=[]
    if args.include_real:
        if not args.source_dir:raise ValueError('--source-dir required for real sources')
        projects,sources=frozen_real(args.source_dir)
        cases=[{'case_id':p['project_id'],'base_fact_ids':[f['id'] for f in p['facts']],
                **prepare_candidates(p,catalog,instances(p),REPO)} for p in projects]+cases
    output=fresh_dir(args.output)
    write(output/'prepared.json',dict(cases=cases,source_manifest=sources))
    for name,real in [('real',True),('public',False)]:
        write(output/f'review-input-{name}.json',{'cases':[{'case_id':c['case_id'],'packet':c['packet']}
              for c in cases if (c['case_id'] in REAL_IDS)==real]})
    write(output/'manifest.json',dict(run_date=args.run_date,prepared_sha256=sha(output/'prepared.json'),
        catalog_sha256=_digest(catalog),source_project='previous frozen prefix sample; no sealed continuation'))
    print(json.dumps(dict(cases=len(cases),output=str(output)),ensure_ascii=False))

def indexed(items):
    if not isinstance(items,list):raise ValueError('Cases must be a list')
    result={}
    for c in items:
        if not isinstance(c,dict) or c.get('case_id') not in LABELS or c['case_id'] in result:
            raise ValueError('Unknown or duplicate case')
        result[c['case_id']]=c
    return result

def evaluate_cases(prepared,reviews,catalog):
    cases=indexed(prepared['cases']);judged=indexed(reviews['reviews'])
    if set(cases)!=set(judged):raise ValueError('Missing or extra reviews')
    canonical_public={c['case_id']:c for c in public_prepared(catalog)}
    results=[]
    for cid,c in cases.items():
        if cid in canonical_public:
            trusted=canonical_public[cid]
            if c['project']!=trusted['project'] or c['packet']!=trusted['packet'] or c['base_fact_ids']!=trusted['base_fact_ids']:
                raise ValueError('Public sample differs from repository original')
        review=judged[cid]['review']
        result=match_motifs(c['project'],c['packet'],review,catalog,REPO)
        # Carry concrete, reviewed story facts alongside the verified conditions.
        # This supplies the actual observed content, not only "answer confirmed".
        base_ids=set(c['base_fact_ids'])
        if result['writer_packet']['proposals']:
            merged={f['id']:f for f in result['writer_packet']['facts']}
            for f in result['pov_view']['facts']:
                if f['id'] in base_ids:merged.setdefault(f['id'],f)
            result['writer_packet']['facts']=list(merged.values())
        result['writer_prompt']='只使用已审核且当前视角知情的事实；方案是待选创作行动。\n'+json.dumps(result['writer_packet'],ensure_ascii=False,indent=2)
        known={f['id'] for f in result['pov_view']['facts']}
        writer_ids={f['id'] for f in result['writer_packet']['facts']}
        kind_by={m['id']:m.get('knowledge_kind','motif') for m in catalog['motifs']}
        variant_kind={v['id']:kind_by[m['id']] for m in catalog['motifs'] for v in m['variants']}
        checks=dict(five_shared_candidates=len(result['author_audit'])==5,
                    writer_facts_pov_supported=writer_ids<=known,
                    writer_contains_exact_packet=json.dumps(result['writer_packet'],ensure_ascii=False,indent=2) in result['writer_prompt'],
                    kinds_preserved=all(v['knowledge_kind']==variant_kind[v['id']] for v in result['writer_packet']['proposals']))
        results.append(dict(case_id=cid,title=LABELS[cid],pov_character=c['project']['pov_character'],
                            prefix=c['packet']['scenes'],candidate_count=len(c['packet']['candidates']),
                            review=review,result=result,checks=checks))
    return results

def summary(results,run_date):
    # Explicit projection: no text, reasons, characters, prefixes, or source paths.
    verdicts=Counter(d['verdict'] for c in results for d in c['review']['decisions'])
    return dict(run_date=run_date,method='fixed_curated_candidate_set_current_ai_review_no_extra_api',
        case_count=len(results),real_prefixes=sum(c['case_id'] in REAL_IDS for c in results),
        candidate_judgments=sum(verdicts.values()),judgments=dict(verdicts),
        workflow_passed=sum(sum(c['checks'].values()) for c in results),workflow_total=sum(len(c['checks']) for c in results),
        cases=[dict(case_id=c['case_id'],title=LABELS[c['case_id']],checks=c['checks'],
            candidates=[{k:a[k] for k in ('motif_id','knowledge_kind','entry_status','applicability_status','supported_stage_ids','supported_condition_ids','unknown_condition_ids','contradicted_condition_ids')} for a in c['result']['author_audit']],
            proposals=[{k:v[k] for k in ('id','knowledge_kind')} for v in c['result']['writer_packet']['proposals']]) for c in results])

def render(results,stats):
    e=lambda v:html.escape(str(v),quote=True)
    states={'true':'有支持','false':'有反证','unknown':'证据不足','eligible':'条件满足','needs_evidence':'待补证据','blocked':'有反证'}
    kinds={'motif':'母题','technique':'技巧','situation':'情境'}
    sections=[]
    for c in results:
        cards=[]
        for a in c['result']['author_audit']:
            conditions=''.join('<li>'+e(x['question'])+'<br><span>前文：'+e(states[x['world']])+' · 视角可用：'+e(states[x['pov']])+'</span></li>' for x in a['conditions'])
            cards.append('<article><small>'+e(kinds[a['knowledge_kind']])+'</small><h3>'+e(a['title'])+'</h3><b>'+e(states[a['applicability_status']])+'</b><ul>'+conditions+'</ul></article>')
        proposals=''.join('<li><strong>'+e(kinds[v['knowledge_kind']]+' · '+v['title'])+'</strong><p>'+e(v['proposal'])+'</p></li>' for v in c['result']['writer_packet']['proposals']) or '<li>当前候选均缺少可执行依据；保留待核对状态。</li>'
        sequence_note=('本段主事件顺序审核有支持；本页仍只检验当前状态条件。' if c['review'].get('chronology_review',{}).get('verdict')=='supported' else '本例全局顺序尚未得到支持；仅检查当前状态，不作事件先后结论。')
        sections.append('<section><h2>'+e(c['title'])+'</h2><p>当前视角：'+e(c['pov_character'])+'</p><p class="note">'+e(sequence_note)+'</p><details><summary>允许前文</summary><p class="prose">'+e('\n\n'.join(s['text'] for s in c['prefix']))+'</p></details><h3>五项候选 · 作者核对视图</h3><div class="cards">'+''.join(cards)+'</div><h3>当前视角可用的方案</h3><ol>'+proposals+'</ol><details><summary>实际写作输入包</summary><pre>'+e(json.dumps(c['result']['writer_packet'],ensure_ascii=False,indent=2))+'</pre></details></section>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>novel-base · 真实前文候选核对</title><style>'
      'body{margin:0;background:#f4f2e9;color:#243831;font:16px/1.8 system-ui,-apple-system,"PingFang SC",sans-serif}main{max-width:1100px;margin:auto;padding:36px 24px}h1{font-size:34px;line-height:1.4}h2{font-size:24px}h3{font-size:17px}small,summary{color:#426e5d}section{background:#fffef9;border:1px solid #d7ddd3;border-radius:12px;padding:24px;margin:26px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}article{padding:18px;background:#f0f3eb;border-radius:9px}article h3{margin:8px 0}article ul{padding-left:20px;font-size:14px}article span{color:#805e2b}li{margin:10px 0}details{padding:12px;background:#f6f5ed;border-radius:6px}summary{cursor:pointer}.prose,pre{white-space:pre-wrap;overflow-wrap:anywhere}pre{font-size:12px}.note{border-left:3px solid #8ea797;padding-left:16px;color:#596b60}@media(max-width:600px){main{padding:24px 16px}section{padding:18px}.cards{grid-template-columns:1fr}h1{font-size:28px}}</style><main><small>NOVEL-BASE / '+e(stats['run_date'])+'</small><h1>真实前文适合哪些候选？</h1><p>固定同一组母题、情境和技巧，逐项核对已有证据。局部相似可以保留为候选，尚未满足的条件不能补写成小说事实。</p><p class="note">'+e(stats['case_count'])+' 个片段（含 '+e(stats['real_prefixes'])+' 个真实前文） · '+e(stats['candidate_judgments'])+' 项候选审核。候选集由本轮选定，尚未自动从全库召回；这里只检验条件与信息边界，不是文学质量排名。</p>'+''.join(sections)+'<footer>完整真实前文和审核仅保存在本机运行目录。共享摘要不包含小说原文。下一轮进入“导入—审核—选择—确认写回”的完整创作流程。</footer></main></html>')

def evaluate(args):
    date.fromisoformat(args.run_date)
    source=Path(args.input);manifest=read(source/'manifest.json');catalog=read(HERE/'catalog.json')
    if sha(source/'prepared.json')!=manifest['prepared_sha256'] or _digest(catalog)!=manifest['catalog_sha256']:
        raise ValueError('Prepared input or catalog changed')
    reviews={'reviews':[]}
    for path in args.reviews:reviews['reviews'].extend(read(path)['reviews'])
    results=evaluate_cases(read(source/'prepared.json'),reviews,catalog)
    stats=summary(results,args.run_date);out=fresh_dir(args.output)
    write(out/'results.json',dict(run_date=args.run_date,cases=results))
    write(out/'summary.json',stats)
    (out/'report.html').write_text(render(results,stats),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False))
    return 0 if stats['workflow_passed']==stats['workflow_total'] else 2

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for name in ('prepare','evaluate'):
        p=sub.add_parser(name);p.add_argument('--output',required=True);p.add_argument('--run-date',required=True)
        if name=='prepare':p.add_argument('--include-real',action='store_true');p.add_argument('--source-dir')
        else:p.add_argument('--input',required=True);p.add_argument('--reviews',nargs='+',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            prepare(args)
            return 0
        return evaluate(args)
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps(dict(ok=False,error=str(error)),ensure_ascii=False),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
