"""Replay both card budgets with the same prepared run and imported judgments."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNNER = runpy.run_path(str(ROOT / 'experiments/recommendation-vector/run_experiment.py'))
POLICIES = ('action_compatible', 'action_coverage')


def digest(value):
    return hashlib.sha256(RUNNER['encoded'](value)).hexdigest()


def assess(run_dir, pool, repo_root):
    manifest, snapshots = RUNNER['load_run'](run_dir)
    fixtures = {row['case_id']: row for row in snapshots['fixtures']['cases']}
    judgments = pool['reviews']
    seen = {}
    results = {}
    for method in RUNNER['METHODS']:
        results[method] = {}
        for policy in POLICIES:
            candidates = RUNNER['run'](run_dir, method, repo_root, candidate_policy=policy)
            by_case = {}
            requests = {}
            for case in candidates['cases']:
                cid, request = case['case_id'], case['request']
                requests[cid] = request
                by_case[cid] = {}
                for instance in request['instances']:
                    prepared = instance['prepared']
                    packet_id = prepared['packet']['packet_sha256']
                    binding = (digest(prepared['project']), digest(prepared['packet']))
                    if seen.setdefault(packet_id, binding) != binding:
                        raise ValueError('different_review_inputs_share_packet_id')
                    by_case[cid][instance['id']] = judgments[packet_id]
            replay = RUNNER['run'](run_dir, method, repo_root, candidate_reviews={'reviews': by_case},
                                   candidate_policy=policy)
            rows = []
            for row in replay['results']:
                cid = row['case_id']
                request = requests[cid]
                registry = fixtures[cid]['annotations']['registry']['actions']
                blocked = {action['action_id'] for action in request['blocked_actions']}
                pairs = [[i['action_id'], i['card_id']] for i in request['instances']]
                proposals = [[p['action_id'], p['card_id'], p['variant_id']] for p in row['proposals']]
                rows.append({'case_id': cid, 'revision': row['revision'],
                    'eligible_actions': sorted(a['id'] for a in registry if a['id'] not in blocked),
                    'cards': row['retrieved_cards'], 'review_pairs': pairs,
                    'covered_actions': sorted({action for action, card in pairs}),
                    'proposals': proposals, 'actions_with_proposal': sorted({p[0] for p in proposals}),
                    'accepted_action': row['accepted_action'], 'plan_count': row['plan_count'],
                    'action_states': row['action_states'], 'source_sha256': row['source_sha256'],
                    'state_sha256': row['state_sha256'], 'acceptance_preserved_facts': row['acceptance_preserved_facts'],
                    'old_revision_rejected': row['old_revision_acceptance_rejected']})
            results[method][policy] = {'metrics': replay['metrics'], 'cases': rows}
    if set(seen) != set(judgments):
        raise ValueError('review_pool_contains_unused_packets')
    return {'schema_version': 1, 'input_hashes': manifest['snapshot_sha256'], 'top_k': 2,
            'unique_packets': len(seen), 'condition_count': sum(len(r['decisions']) for r in judgments.values()),
            'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--reviews', type=Path, default=Path(__file__).with_name('candidate-reviews-public.json'))
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--expect', type=Path, help='Require identical summary JSON before printing the result.')
    args = parser.parse_args()
    try:
        summary = assess(args.run_dir, RUNNER['read'](args.reviews), args.repo_root)
        if args.expect and RUNNER['encoded'](summary) != RUNNER['encoded'](RUNNER['read'](args.expect)):
            raise ValueError('replay_differs_from_record')
        print(RUNNER['encoded'](summary).decode(), end='')
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
