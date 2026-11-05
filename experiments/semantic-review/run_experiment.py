#!/usr/bin/env python3
"""Prepare blinded source-bound packets; evaluate separately supplied AI reviews.

No API/model calls. Novel excerpts and complete reports stay under runtime-data.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))
from semantic_review import prepare_review, run_reviewed_pipeline
from narrative_prototype import run_pipeline


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def fresh_output(value):
    path = Path(value).expanduser().absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Output links are forbidden')
    if not path.resolve().is_relative_to((REPO/'runtime-data').resolve()) or path.exists():
        raise ValueError('Use a fresh directory under this repository runtime-data')
    path.mkdir(parents=True, exist_ok=False)
    return path


def anonymize(project):
    project = copy.deepcopy(project)
    mapping = {f['id']:f'f{i:03d}' for i,f in enumerate(project['facts'],1)}
    for f in project['facts']:
        f['id'] = mapping[f['id']]
        f['epistemic_status'] = 'unreviewed_candidate'
    for t in project['threads']:
        t['setup_fact_ids'] = [mapping[x] for x in t['setup_fact_ids']]
        if t['resolution_fact_id'] is not None:
            t['resolution_fact_id'] = mapping[t['resolution_fact_id']]
    return project, mapping


def real_projects(selection_path, source_dir):
    selection = read(selection_path)
    books = {b['book_id']:b for b in selection['books']}
    projects, sources = [], {}
    for case in selection['cases']:
        if case['id'] not in ('old-lord-monitor', 'organs-forensic-inference'):
            continue
        book = books[case['book_id']]
        source = Path(source_dir)/Path(book['source_path']).name
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != book['source_sha256']:
            raise ValueError('Novel source hash changed')
        prefix = case['prefix']
        if (raw.decode('utf-8')[case['prefix_start']:case['prefix_end']] != prefix
                or case['order_review']['eligible'] is not True):
            raise ValueError('Prefix or source ordering was not verified')
        sources[str(source.resolve())] = book['source_sha256']
        facts = [{k:copy.deepcopy(f[k]) for k in ('id','text','quote','known_by')} |
                 {'scene_id':'s1','start':f['start']-case['prefix_start'],'end':f['end']-case['prefix_start']}
                 for f in case['facts']]
        by = {f['id']:f for f in facts}
        if case['id'] == 'old-lord-monitor':
            facts += [dict(by['alarm'],id='alarm_absent',text='研究所的警报一直没有响过。'),
                      dict(by['searching'],id='purpose',text='五名来人已经明确告诉萧临，他们正在寻找一把铜钥匙。')]
            present, setup = ['萧临'], 'alarm'
        else:
            facts += [dict(by['next_coroner'],id='coroner_arrived',text='新的仵作已经在停尸房到场，并参与检查。'),
                      dict(by['copycat_hypothesis'],id='killer_identified',text='凶手的身份已经查明，确认为肖喆。')]
            by['copycat_hypothesis']['known_by'].append('梅先生')
            present, setup = ['殷阳','肖喆'], 'division_of_work'
        projects.append({'schema_version':1,'project_id':'review-'+case['id'],'title':case['title'],
            'pov_character':case['pov_character'],'characters':case['characters'],
            'goal':{'id':'recover_and_investigate','description':case['goal']},
            'scenes':[{'id':'s1','order':1,'text':prefix,'function':'investigation','tension':3,'present_characters':present}],
            'facts':facts,'threads':[{'id':'t1','description':'继续核对眼前的线索','status':'open',
                'setup_fact_ids':[setup],'resolution_fact_id':None,'reveal_allowed':False}]})
    if len(projects) != 2:
        raise ValueError('Expected exactly two curated local prefixes')
    return projects, sources


def prepare(args):
    public = read(Path(__file__).with_name('fixtures.json'))['projects']
    novels, sources = real_projects(args.selection, args.source_dir) if args.selection else ([], {})
    projects, packets, maps = [], [], {}
    for original in public + novels:
        project, mapping = anonymize(original)
        maps[project['project_id']] = mapping
        projects.append(project)
        packets.append(prepare_review(project))
    output = fresh_output(args.output)
    write(output/'projects.json', {'projects':projects})
    # The only judge input: no sealed continuations, expected answers, strategy ranks, or ID maps.
    write(output/'review-input.json', {'packets':packets})
    write(output/'local-probe-map.json', maps)
    write(output/'manifest.json', {'run_date':args.run_date,'project_count':len(projects),
        'candidate_count':sum(len(p['facts']) for p in projects),
        'public_project_ids':[p['project_id'] for p in public],
        'projects_sha256':sha(output/'projects.json'),'packets_sha256':sha(output/'review-input.json'),
        'source_books':sources})
    print(json.dumps({'output':str(output),'projects':len(projects),
        'candidates':sum(len(p['facts']) for p in projects)},ensure_ascii=False))


def public_review(review):
    """Project validated fields only; model-added metadata is never published."""
    def refs(items):
        return [{key:ref[key] for key in ('scene_id','start','end','quote','source_sha256') if key in ref}
                for ref in items]
    decisions=[]
    for item in review['decisions']:
        decision={key:item[key] for key in ('fact_id','verdict','epistemic_type','reason')}
        decision['evidence']=refs(item['evidence'])
        decision['knowledge']=[{**{key:k[key] for key in ('character_id','verdict','reason')},
                                'evidence':refs(k['evidence'])} for k in item['knowledge']]
        decisions.append(decision)
    return {**{key:review[key] for key in ('schema_version','project_id','project_sha256','packet_sha256')},
            'reviewer':{key:review['reviewer'][key] for key in ('kind','name')}, 'decisions':decisions}


def evaluate(args):
    source = Path(args.input)
    manifest = read(source/'manifest.json')
    if sha(source/'projects.json') != manifest['projects_sha256'] or sha(source/'review-input.json') != manifest['packets_sha256']:
        raise ValueError('Frozen input changed')
    reviews = read(args.reviews)['reviews']
    projects = read(source/'projects.json')['projects']
    packets = read(source/'review-input.json')['packets']
    expected = {p['project_id'] for p in projects}
    if len(reviews) != len(expected) or {x['project_id'] for x in reviews} != expected:
        raise ValueError('Missing, duplicate, or unknown project review')
    review_by = {r['project_id']:r for r in reviews}
    packet_by = {p['project_id']:p for p in packets}
    all_results, cases = [], []
    for project in projects:
        review = review_by[project['project_id']]
        result = run_reviewed_pipeline(project,packet_by[project['project_id']],review,REPO)
        before = run_pipeline(project,REPO)
        after = result['recommendation']
        by_id = {d['fact_id']:d for d in review['decisions']}
        eligible = {f['id'] for f in result['project']['facts'] if project['pov_character'] in f['known_by']}
        packet_ids = {f['id'] for item in after['recommendations'] for f in item['context_packet']['facts']}
        checks = {
            'positive_facts_survive':bool(eligible),
            'known_facts_match_gate':set(after['story_state']['known_fact_ids'])==eligible,
            'context_packet_facts_subset_of_gate':bool(packet_ids) and packet_ids <= eligible,
            'context_facts_supported_by_imported_review':all(by_id[x]['verdict']=='supported' and by_id[x]['epistemic_type']=='established' for x in packet_ids),
            'nonempty_recommendations':bool(after['recommendations']),
            'actual_prompt_contains_current_packets':json.dumps({'context_packets':[r['context_packet'] for r in after['recommendations']]},ensure_ascii=False,indent=2) in after['writer_prompt'],
        }
        if project['project_id']=='review-copper-key':
            checks['wrong_knowledge_reveal_was_available_before']=any(r['id']=='earned_reveal' for r in before['recommendations'])
            checks['wrong_knowledge_reveal_blocked_after']=not any(r['id']=='earned_reveal' for r in after['recommendations'])
        case={'project_id':project['project_id'],'candidate_count':len(project['facts']),
            'verdict_counts':dict(Counter(d['verdict'] for d in review['decisions'])),
            'epistemic_counts':dict(Counter(d['epistemic_type'] for d in review['decisions'])),
            'knowledge_verdict_counts':dict(Counter(k['verdict'] for d in review['decisions'] for k in d['knowledge'])),
            'known_before':before['story_state']['known_fact_ids'],'known_after':after['story_state']['known_fact_ids'],
            'recommendations_before':[r['id'] for r in before['recommendations']],
            'recommendations_after':[r['id'] for r in after['recommendations']],
            'checks':checks,'passed':all(checks.values())}
        cases.append(case)
        all_results.append({'case':case,'result':result})
    unchanged=all(Path(p).is_file() and sha(p)==h for p,h in manifest['source_books'].items())
    if not unchanged:
        raise ValueError('Source book changed; cannot declare preserved originals')
    output=fresh_output(args.output)
    summary={'run_date':args.run_date,'method':'Current Codex agent reviewed frozen packets; program validated and imported reviews; no extra model API',
        'project_count':len(cases),'candidate_count':sum(c['candidate_count'] for c in cases),
        'passed_projects':sum(c['passed'] for c in cases),'checks_passed':sum(sum(c['checks'].values()) for c in cases),
        'checks_total':sum(len(c['checks']) for c in cases),'source_books_unchanged':unchanged,
        'limitations':['AI review is not independent human gold or accuracy measurement.',
            'This imports explicit judgments; the default writer and old 20-check audit do not automatically acquire semantic understanding.',
            'Existing four strategy cards are used; motif/situation/variant applicability is not implemented.',
            'Scene functions, tension and author goals remain experiment annotations.'],
        'verdict_counts':dict(sum((Counter(c['verdict_counts']) for c in cases),Counter())),
        'knowledge_verdict_counts':dict(sum((Counter(c['knowledge_verdict_counts']) for c in cases),Counter())),
        'cases':cases}
    write(output/'results.json', {'summary':summary,'results':all_results})
    write(output/'public-summary.json',summary)
    # Never trust a mutable manifest's public/private classification on its own.
    public_hashes={p['project_id']:prepare_review(anonymize(p)[0])['project_sha256']
                   for p in read(Path(__file__).with_name('fixtures.json'))['projects']}
    public=[]
    for review in reviews:
        if review['project_id'] in public_hashes:
            if review['project_sha256'] != public_hashes[review['project_id']]:
                raise ValueError('Public fixture changed; cannot export its review')
            public.append(public_review(review))
    write(output/'public-reviews.json',{'reviews':public})
    lines=['# 事实审核与推荐小样','',f"{args.run_date}：{len(cases)} 个项目，{summary['candidate_count']} 条候选，{summary['checks_passed']}/{summary['checks_total']} 项流程检查通过。",'',
        '当前 AI 先阅读冻结前文并提交判断，程序再验证来源与引用，并运行原有推荐器。没有额外接口调用；下表不代表语义准确率。','',
        '| 项目 | 候选 | 视角可用（前→后） | 推荐（前→后） |','| --- | ---: | --- | --- |']
    for c in cases:
        lines.append(f"| {c['project_id']} | {c['candidate_count']} | {len(c['known_before'])} → {len(c['known_after'])} | {', '.join(c['recommendations_before'])} → {', '.join(c['recommendations_after'])} |")
    lines += ['', '## 每条判断与实际写作输入','', '完整理由、精确引文和实际推荐输入保存在同目录 results.json。被隔离的候选保留在审核区，不是世界事实。', '',
        '## 仍未完成','', '独立人工核验、程序自动调用语义模型、母题阶段与变体匹配尚未实现。旧20项自动能力审计仍保留18通过、2未实现的结论。']
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('project_count','candidate_count','passed_projects','checks_passed','checks_total','source_books_unchanged')},ensure_ascii=False))
    return 0 if all(c['passed'] for c in cases) else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--selection',type=Path);p.add_argument('--source-dir',type=Path)
    p.add_argument('--output',required=True);p.add_argument('--run-date',required=True)
    p=sub.add_parser('evaluate');p.add_argument('--input',required=True);p.add_argument('--reviews',required=True);p.add_argument('--output',required=True);p.add_argument('--run-date',required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        if args.selection and not args.source_dir:parser.error('--selection requires --source-dir')
        prepare(args);return 0
    return evaluate(args)


if __name__=='__main__':
    raise SystemExit(main())
