#!/usr/bin/env python3
"""Prepare local vector inputs and replay separately imported AI judgments.

No models or APIs are invoked. Prepare exclusively creates a new runtime-data
run; candidates and replay only read files and print JSON to stdout.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))
from recommendation_session import new_session, append_scene, source_token, canonical_digest
from recommendation_engine import (prepare_state, review_state, prepare_retrieval_embeddings,
    prepare_recommendations, review_recommendations, accept_current)
from recommendation_retrieval import encoded

SNAPSHOTS = {'fixtures': 'fixtures.json', 'state_reviews': 'state-reviews.json', 'catalog': 'catalog.json'}
METHODS = ('bm25', 'vector', 'hybrid')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def invalid(value):
        raise ValueError('nonfinite_json:' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid)


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encoded(value))


def fresh_dir(path, repo_root):
    destination = Path(path).expanduser().absolute()
    runtime = Path(repo_root).expanduser().absolute() / 'runtime-data'
    for target in (destination, runtime):
        require(not any(p.is_symlink() for p in (target, *target.parents)), 'output_symlink')
    destination, runtime = destination.resolve(), runtime.resolve()
    require(destination != runtime and destination.is_relative_to(runtime), 'output_outside_runtime')
    require(not destination.exists(), 'output_already_exists')
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValueError('output_already_exists') from error
    return destination


def case_ids(fixtures):
    require(isinstance(fixtures, dict) and isinstance(fixtures.get('cases'), list)
            and bool(fixtures['cases']), 'cases_required')
    seen = set()
    for row in fixtures['cases']:
        require(isinstance(row, dict), 'invalid_case')
        require({'case_id', 'episode_id', 'source', 'new_scene', 'annotations', 'accept_action'} <= row.keys()
                and isinstance(row['episode_id'], str) and bool(row['episode_id'].strip())
                and (row['accept_action'] is None or isinstance(row['accept_action'], str)), 'invalid_case')
        cid = row.get('case_id')
        require(isinstance(cid, str) and re.fullmatch(r'[a-z0-9_]{1,80}', cid), 'invalid_case_id')
        require(cid not in seen, 'duplicate_case_id')
        seen.add(cid)
    return [row['case_id'] for row in fixtures['cases']]


def coverage(reviews, ids, label):
    require(isinstance(reviews, dict) and isinstance(reviews.get('reviews'), dict)
            and set(reviews['reviews']) == set(ids), label + '_review_coverage')


def advance(sessions, row):
    key = row['episode_id']
    session = (new_session(row['source']) if key not in sessions else
               append_scene(sessions[key], row['new_scene'], source_token(sessions[key])))
    require(session['source'] == row['source'], 'fixture_does_not_follow_append_order:' + row['case_id'])
    sessions[key] = session
    return session


def reviewed_state(sessions, row, state_reviews):
    session = advance(sessions, row)
    request = prepare_state(session, row['annotations'])
    session = review_state(session, request, state_reviews['reviews'][row['case_id']])
    sessions[row['episode_id']] = session
    return session


def prepare_run(fixtures, state_reviews, catalog, repo_root, output):
    ids = case_ids(fixtures)
    coverage(state_reviews, ids, 'state')
    sessions, bundles = {}, {}
    for row in fixtures['cases']:
        session = reviewed_state(sessions, row, state_reviews)
        bundles[row['case_id']] = prepare_retrieval_embeddings(session, catalog, repo_root)
    snapshots = {'fixtures': fixtures, 'state_reviews': state_reviews, 'catalog': catalog}
    manifest = {'schema_version': 1, 'repo_root': str(Path(repo_root).resolve()), 'case_ids': ids,
                'snapshot_sha256': {key: digest(value) for key, value in snapshots.items()}}
    # Serialize every file before creating the directory, including caller metadata.
    for value in [manifest, *snapshots.values(), *(v for b in bundles.values() for v in b.values())]:
        encoded(value)
    directory = fresh_dir(output, repo_root)
    for key, value in snapshots.items():
        write_new(directory / SNAPSHOTS[key], value)
    write_new(directory / 'manifest.json', manifest)
    for cid, bundle in bundles.items():
        case_dir = directory / cid
        case_dir.mkdir()
        write_new(case_dir / 'dataset.json', bundle['dataset'])
        write_new(case_dir / 'embedding-input.json', bundle['embedding_input'])
    return {'schema_version': 1, 'run_dir': str(directory), 'cases': [
        {'case_id': cid, 'dataset_path': str(directory / cid / 'dataset.json'),
         'embedding_input_path': str(directory / cid / 'embedding-input.json')} for cid in ids]}


def load_run(directory):
    manifest = read(directory / 'manifest.json')
    require(isinstance(manifest, dict) and type(manifest.get('schema_version')) is int and manifest['schema_version'] == 1,
            'invalid_run_manifest')
    snapshots = {key: read(directory / name) for key, name in SNAPSHOTS.items()}
    require(manifest.get('snapshot_sha256') == {key: digest(value) for key, value in snapshots.items()},
            'run_snapshot_changed')
    require(manifest.get('case_ids') == case_ids(snapshots['fixtures']), 'run_cases_changed')
    coverage(snapshots['state_reviews'], manifest['case_ids'], 'state')
    return manifest, snapshots


def run(run_dir, method, repo_root=None, top_k=2, candidate_reviews=None, *, candidate_policy='global'):
    require(method in METHODS, 'invalid_retrieval_method')
    require(type(top_k) is int and 0 <= top_k <= 50, 'invalid_top_k')
    require(candidate_policy in ('global', 'action_compatible', 'action_coverage'), 'invalid_candidate_policy')
    policy_metadata = {'candidate_policy': candidate_policy} if candidate_policy != 'global' else {}
    directory = Path(run_dir)
    manifest, inputs = load_run(directory)
    repo_root = Path(repo_root or manifest['repo_root'])
    if candidate_reviews is not None:
        coverage(candidate_reviews, manifest['case_ids'], 'candidate')
    sessions, requests, results = {}, [], []
    catalog = inputs['catalog']
    for row in inputs['fixtures']['cases']:
        cid, episode = row['case_id'], row['episode_id']
        previous = sessions.get(episode)
        session = reviewed_state(sessions, row, inputs['state_reviews'])
        artifact = None
        if method != 'bm25':
            artifact = {key: read(directory / cid / name) for key, name in (
                ('dataset', 'dataset.json'), ('embedding_input', 'embedding-input.json'),
                ('embeddings', 'embeddings.json'))}
        request = prepare_recommendations(session, catalog, repo_root, top_k=top_k,
            retrieval_method=method, embedding_artifact=artifact, candidate_policy=candidate_policy)
        if candidate_reviews is None:
            requests.append({'case_id': cid, 'request': request})
            continue
        session = review_recommendations(session, request, candidate_reviews['reviews'][cid],
            catalog, repo_root, embedding_artifact=artifact)
        before_state, before_source = canonical_digest(session['current_state']), canonical_digest(session['source'])
        selected = next((p for p in session['current_batch']['proposals']
                         if p['action_id'] == row['accept_action']), None)
        if selected:
            session = accept_current(session, selected['id'], source_token(session),
                                     session['batch_sha256'], catalog, repo_root)
        unchanged = (before_state == canonical_digest(session['current_state']) and
                     before_source == canonical_digest(session['source']))
        stale_rejected = None
        if previous and previous['current_batch'] and previous['current_batch']['proposals']:
            proposal = previous['current_batch']['proposals'][0]
            try:
                accept_current(session, proposal['id'], source_token(previous),
                               previous['batch_sha256'], catalog, repo_root)
            except ValueError as error:
                if str(error) != 'stale or cross-project source token':
                    raise
                stale_rejected = True
            else:
                stale_rejected = False
        results.append({'case_id': cid, 'episode_id': episode, 'revision': session['revision'],
            'source_sha256': session['source_sha256'], 'state_sha256': session['state_sha256'],
            'batch_sha256': session['batch_sha256'], 'ranking': copy.deepcopy(request['ranking']),
            'retrieved_cards': [h['source_path'] for h in request['ranking']],
            'reviewed_instances': len(request['instances']),
            'action_states': {a: v['status'] for a, v in session['current_state']['actions'].items()},
            'proposals': copy.deepcopy(session['current_batch']['proposals']),
            'blocked_actions': request['blocked_actions'],
            'accepted_action': selected['action_id'] if selected else None, 'plan_count': len(session['plans']),
            'acceptance_preserved_facts': unchanged, 'old_revision_acceptance_rejected': stale_rejected})
        if candidate_policy != 'global':
            results[-1]['compatible_card_ids'] = request['compatible_card_ids']
        sessions[episode] = session
    if candidate_reviews is None:
        return {'schema_version': 1, **policy_metadata, 'cases': requests}
    return {'schema_version': 1, 'mode': 'imported-review-with-' + method,
            **policy_metadata, 'catalog_sha256': canonical_digest(catalog), 'results': results, 'sessions': sessions,
            'metrics': {'cases': len(results), 'accepted': sum(r['accepted_action'] is not None for r in results),
                'acceptance_preserved_facts': all(r['acceptance_preserved_facts'] for r in results),
                'cross_revision_checks': sum(r['old_revision_acceptance_rejected'] is not None for r in results),
                'cross_revision_rejected': sum(r['old_revision_acceptance_rejected'] is True for r in results)}}


def main(argv=None, *, prepared_runs_only=False):
    description = 'Compare candidate policies on a prepared run using imported reviews.' if prepared_runs_only else __doc__
    parser = argparse.ArgumentParser(description=description)
    commands = parser.add_subparsers(dest='command', required=True)
    if not prepared_runs_only:
        prepare = commands.add_parser('prepare')
        prepare.add_argument('--fixtures', type=Path, default=REPO / 'experiments/recommendation-core/fixtures-public.json')
        prepare.add_argument('--state-reviews', type=Path, default=REPO / 'experiments/recommendation-core/state-reviews-public.json')
        prepare.add_argument('--catalog', type=Path, default=REPO / 'recommendation/action-catalog.json')
        prepare.add_argument('--repo-root', type=Path, default=REPO)
        prepare.add_argument('--output-dir', type=Path, required=True)
    for name in ('candidates', 'replay'):
        command = commands.add_parser(name)
        command.add_argument('--run-dir', type=Path, required=True)
        command.add_argument('--method', choices=METHODS, required=True)
        command.add_argument('--repo-root', type=Path)
        command.add_argument('--top-k', type=int, default=2)
        if prepared_runs_only:
            command.add_argument('--candidate-policy', choices=('global', 'action_compatible', 'action_coverage'), required=True)
        if name == 'replay':
            command.add_argument('--candidate-reviews', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            value = prepare_run(read(args.fixtures), read(args.state_reviews), read(args.catalog), args.repo_root, args.output_dir)
        else:
            reviews = None
            if args.command == 'replay':
                reviews = read(args.candidate_reviews)
                require(isinstance(reviews, dict), 'candidate_review_coverage')
            value = run(args.run_dir, args.method, args.repo_root, args.top_k,
                        reviews,
                        candidate_policy=getattr(args, 'candidate_policy', 'global'))
        print(encoded(value).decode('utf-8'), end='')
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
