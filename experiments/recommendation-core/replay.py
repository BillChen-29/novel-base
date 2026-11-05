#!/usr/bin/env python3
"""Replay imported AI judgments through the public recommendation core.

No generation or automatic review: prepare-states/prepare-candidates emit review
requests, and replay consumes separately produced decisions. Output is JSON to
stdout; the caller chooses storage, keeping private inputs outside public files.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))
from recommendation_session import new_session, append_scene, source_token, canonical_digest
from recommendation_engine import (prepare_state, review_state, prepare_recommendations,
                                   review_recommendations, accept_current)


def read(path):
    def invalid(value):
        raise ValueError('nonfinite_json:' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid)


def advance(sessions, row):
    key = row['episode_id']
    if key not in sessions:
        session = new_session(row['source'])
    else:
        old = sessions[key]
        session = append_scene(old,row['new_scene'],source_token(old))
    if session['source'] != row['source']:
        raise ValueError('fixture_does_not_follow_append_order:' + row['case_id'])
    sessions[key] = session
    return session


def run(fixtures, catalog, repo_root, command, state_reviews=None, candidate_reviews=None):
    sessions, requests, results, seen = {}, [], [], set()
    for row in fixtures['cases']:
        cid = row['case_id']
        if cid in seen:
            raise ValueError('duplicate_case_id')
        seen.add(cid)
        previous = sessions.get(row['episode_id'])
        session = advance(sessions,row)
        state_request = prepare_state(session,row['annotations'])
        if command == 'prepare-states':
            requests.append({'case_id':cid,'request':state_request})
            continue
        session = review_state(session,state_request,state_reviews['reviews'][cid])
        request = prepare_recommendations(session,catalog,repo_root,top_k=2)
        if command == 'prepare-candidates':
            requests.append({'case_id':cid,'request':request})
            sessions[row['episode_id']] = session
            continue
        session = review_recommendations(session,request,candidate_reviews['reviews'][cid],catalog,repo_root)
        before_state = canonical_digest(session['current_state'])
        before_source = canonical_digest(session['source'])
        selected = next((p for p in session['current_batch']['proposals'] if p['action_id'] == row['accept_action']),None)
        if selected:
            session = accept_current(session,selected['id'],source_token(session),session['batch_sha256'],catalog,repo_root)
        unchanged = (before_state == canonical_digest(session['current_state']) and
                     before_source == canonical_digest(session['source']))
        stale_rejected = None
        if previous and previous['current_batch'] and previous['current_batch']['proposals']:
            p = previous['current_batch']['proposals'][0]
            try:
                accept_current(session,p['id'],source_token(previous),previous['batch_sha256'],catalog,repo_root)
            except ValueError:
                stale_rejected = True
            else:
                stale_rejected = False
        batch = session['current_batch']
        results.append({'case_id':cid,'episode_id':row['episode_id'],'revision':session['revision'],
            'source_sha256':session['source_sha256'],'state_sha256':session['state_sha256'],
            'batch_sha256':session['batch_sha256'],'retrieved_cards':[h['source_path'] for h in request['ranking']],
            'reviewed_instances':len(request['instances']),
            'action_states':{a:v['status'] for a,v in session['current_state']['actions'].items()},
            'proposals':copy.deepcopy(batch['proposals']), 'blocked_actions':request['blocked_actions'],
            'accepted_action':selected['action_id'] if selected else None,'plan_count':len(session['plans']),
            'acceptance_preserved_facts':unchanged,'old_revision_acceptance_rejected':stale_rejected})
        sessions[row['episode_id']] = session
    if command != 'replay':
        return {'schema_version':1,'cases':requests}
    return {'schema_version':1,'mode':'current-ai-imported-review-with-bm25',
        'catalog_sha256':canonical_digest(catalog),'results':results,'sessions':sessions,
        'limitations':['语义判断由本轮 AI 审阅导入；不是程序自动理解正文。',
            '样本和操作化目录用于机制验收，不是独立小说推荐准确率。',
            '未调用写作模型；新增正文来自预先编写的原创连续案例。']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare-states','prepare-candidates','replay'))
    parser.add_argument('--fixtures',type=Path,default=Path(__file__).with_name('fixtures-public.json'))
    parser.add_argument('--catalog',type=Path,default=REPO/'recommendation/action-catalog.json')
    parser.add_argument('--repo-root',type=Path,default=REPO)
    parser.add_argument('--state-reviews',type=Path)
    parser.add_argument('--candidate-reviews',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command != 'prepare-states' and not args.state_reviews:
            raise ValueError('state_reviews_required')
        if args.command == 'replay' and not args.candidate_reviews:
            raise ValueError('candidate_reviews_required')
        value=run(read(args.fixtures),read(args.catalog),args.repo_root,args.command,
                  read(args.state_reviews) if args.state_reviews else None,
                  read(args.candidate_reviews) if args.candidate_reviews else None)
        print(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
