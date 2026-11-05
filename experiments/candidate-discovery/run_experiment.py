#!/usr/bin/env python3
"""Replay source-bound discovery and imported AI applicability reviews.

No model calls, prose generation or story-memory writes. Related passages remain
untrusted candidates until an independently supplied review is checked. Checking
coordinates and declared states cannot establish that an AI judgment is correct.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / 'scripts'))
from knowledge_discovery import build_index, discover, _validate_snapshot, _source_path
from semantic_review import _digest

METHODS = ('raw_prefix', 'abstract_queries', 'fused')
VERDICTS = {'supported', 'contradicted', 'insufficient_evidence'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), 'invalid_' + name)
    return value


def indexed(items):
    require(isinstance(items, list), 'cases_must_be_list')
    result = {}
    for item in items:
        require(isinstance(item, dict), 'invalid_case')
        cid = item.get('case_id')
        require(isinstance(cid, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', cid), 'invalid_case_id')
        require(cid not in result, 'duplicate_case')
        result[cid] = item
    require(bool(result), 'empty_cases')
    return result


def fresh_dir(path):
    destination = Path(path).expanduser().absolute()
    require(not any(p.is_symlink() for p in (destination, *destination.parents)), 'output_symlink')
    require(destination.resolve().is_relative_to((REPO / 'runtime-data').resolve()), 'output_outside_runtime')
    require(not destination.exists(), 'output_already_exists')
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def discover_cases(inputs, analyses, manifest, repo_root, limit=3):
    cases, by_analysis = indexed(inputs['cases']), indexed(analyses['cases'])
    require(set(cases) == set(by_analysis), 'analysis_case_mismatch')
    expected = manifest['documents']
    index = build_index(repo_root, [d['path'] for d in expected])
    current = {d['source_path']: d for d in index['documents']}
    require(all(current[d['path']]['source_sha256'] == d['sha256'] for d in expected), 'frozen_corpus_changed')
    output = []
    for cid, case in cases.items():
        result = discover(case['snapshot'], index, by_analysis[cid]['analysis'], limit=limit)
        union = {h['source_path'] for method in METHODS for h in result['methods'][method]}
        # Reviewers get full source documents, sorted independently of ranking.
        # Top chunks alone omit prerequisites and limitations found elsewhere.
        packet = {'schema_version': 1, 'snapshot': copy.deepcopy(case['snapshot']),
                  'retrieval_sha256': _digest(result),
                  'corpus_sha256': index['corpus_sha256'],
                  'documents': [{k: current[p][k] for k in ('source_path', 'title', 'kind', 'source_sha256', 'text')}
                                for p in sorted(union)]}
        packet['packet_sha256'] = _digest(packet)
        output.append({'case_id': cid, 'discovery': result, 'review_packet': packet})
    return {'schema_version': 1, 'limit': limit, 'corpus_manifest_sha256': _digest(manifest),
            'corpus_sha256': index['corpus_sha256'], 'cases': output}


def check_refs(refs, source, required):
    require(isinstance(refs, list) and (bool(refs) or not required), 'evidence_required')
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) == {'start', 'end', 'quote'}, 'invalid_evidence_fields')
        start, end = ref['start'], ref['end']
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(source), 'evidence_outside_source')
        require(source[start:end] == text(ref['quote'], 'quote'), 'evidence_quote_mismatch')
    return copy.deepcopy(refs)


def check_packet(packet):
    require(isinstance(packet, dict), 'invalid_packet')
    require(set(packet) == {'schema_version', 'snapshot', 'corpus_sha256', 'retrieval_sha256', 'documents', 'packet_sha256'}, 'invalid_packet_fields')
    require(type(packet['schema_version']) is int and packet['schema_version'] == 1, 'invalid_packet_schema')
    for key in ('corpus_sha256', 'retrieval_sha256', 'packet_sha256'):
        require(isinstance(packet[key], str) and re.fullmatch(r'[0-9a-f]{64}', packet[key]), 'invalid_packet_digest')
    expected = {k: v for k, v in packet.items() if k != 'packet_sha256'}
    require(_digest(expected) == packet.get('packet_sha256'), 'packet_changed')
    snapshot = packet['snapshot']
    _validate_snapshot(snapshot)
    docs = packet['documents']
    require(isinstance(docs, list) and all(isinstance(d, dict) for d in docs), 'invalid_documents')
    paths = []
    for d in docs:
        require(set(d) == {'source_path', 'title', 'kind', 'source_sha256', 'text'}, 'invalid_document_fields')
        paths.append(_source_path(d['source_path']))
        text(d['title'], 'document_title')
        require(isinstance(d['kind'], str) and d['kind'] in {'motif', 'technique', 'scenario', 'pacing', 'character', 'style'}, 'invalid_document_kind')
        require(isinstance(d['text'], str), 'invalid_knowledge_text')
        require(hashlib.sha256(d['text'].encode()).hexdigest() == d['source_sha256'], 'knowledge_changed')
    require(len(paths) == len(set(paths)), 'duplicate_document')


def apply_candidate_review(packet, review):
    """Gate declared condition/POV judgments; never infer their truth from quotes."""
    check_packet(packet)
    require(isinstance(review, dict), 'invalid_review')
    require(review.get('schema_version') == 1 and type(review.get('schema_version')) is int, 'invalid_review_schema')
    require(review.get('packet_sha256') == packet['packet_sha256'], 'review_binding_mismatch')
    require(isinstance(review.get('reviewer'), dict) and review['reviewer'].get('kind') == 'agent_review', 'invalid_reviewer')
    text(review['reviewer'].get('name'), 'reviewer_name')
    docs = {d['source_path']: d for d in packet['documents']}
    decisions = review.get('decisions')
    require(isinstance(decisions, list), 'invalid_decisions')
    by_path = {}
    for d in decisions:
        require(isinstance(d, dict), 'invalid_decision')
        path = d.get('source_path')
        require(isinstance(path, str) and path in docs and path not in by_path, 'unknown_or_duplicate_decision')
        by_path[path] = d
    story = packet['snapshot']['text']
    audit, proposals = [], []
    for path, document in docs.items():
        if path not in by_path:
            audit.append({'source_path': path, 'status': 'needs_evidence', 'assessment_scope': 'local_operation',
                          'reason': 'missing_review', 'conditions': []})
            continue
        d = by_path[path]
        reason = text(d.get('reason'), 'reason')
        operation = text(d.get('operation'), 'operation')
        source_refs = check_refs(d.get('knowledge_evidence'), document['text'], True)
        conditions = d.get('conditions')
        require(isinstance(conditions, list) and bool(conditions), 'conditions_required')
        states = []
        checked = []
        for c in conditions:
            require(isinstance(c, dict), 'invalid_condition')
            claim = text(c.get('claim'), 'condition_claim')
            verdict = c.get('verdict')
            require(isinstance(verdict, str) and verdict in VERDICTS, 'invalid_condition_verdict')
            ep = c.get('epistemic_type')
            require(isinstance(ep, str) and ep in {'established', 'reported', 'inferred', 'uncertain'}, 'invalid_epistemic_type')
            refs = check_refs(c.get('story_evidence'), story, verdict != 'insufficient_evidence')
            knowledge_refs = check_refs(c.get('knowledge_evidence'), document['text'], True)
            states.append(verdict if ep == 'established' else 'insufficient_evidence')
            checked.append({'claim': claim, 'verdict': verdict, 'epistemic_type': ep,
                            'story_evidence': refs, 'knowledge_evidence': knowledge_refs})
        pov = d.get('pov')
        require(isinstance(pov, dict) and isinstance(pov.get('verdict'), str) and pov['verdict'] in VERDICTS, 'invalid_pov')
        pov_reason = text(pov.get('reason'), 'pov_reason')
        pov_refs = check_refs(pov.get('evidence'), story, pov['verdict'] != 'insufficient_evidence')
        states.append(pov['verdict'])
        status = ('blocked' if 'contradicted' in states else 'eligible' if all(s == 'supported' for s in states) else 'needs_evidence')
        item = {'source_path': path, 'title': document['title'], 'kind': document['kind'], 'status': status,
                'assessment_scope': 'local_operation', 'motif_completion': 'not_assessed',
                'reason': reason, 'operation': operation, 'knowledge_evidence': source_refs, 'conditions': checked,
                'pov': {'verdict': pov['verdict'], 'reason': pov_reason, 'evidence': pov_refs}}
        audit.append(item)
        if status == 'eligible':
            # An eligible operation is a proposed creative action, never history.
            proposals.append({'source_path': path, 'kind': document['kind'], 'operation': operation,
                              'state': 'proposed_not_history', 'assessment_scope': 'local_operation', 'conditions': checked,
                              'knowledge_evidence': source_refs, 'pov_evidence': pov_refs})
    return {'snapshot_sha256': packet['snapshot']['snapshot_sha256'], 'packet_sha256': packet['packet_sha256'],
            'audit': audit, 'proposals': proposals}


def evaluate_cases(discovered, reviews):
    cases, judged = indexed(discovered['cases']), indexed(reviews['cases'])
    require(set(cases) == set(judged), 'review_case_mismatch')
    output = []
    for cid, case in cases.items():
        check_packet(case['review_packet'])
        require(_digest(case['discovery']) == case['review_packet'].get('retrieval_sha256'), 'ranking_changed')
        require(case['discovery']['snapshot_sha256'] == case['review_packet']['snapshot']['snapshot_sha256'], 'ranking_snapshot_mismatch')
        require(case['discovery']['corpus_sha256'] == case['review_packet']['corpus_sha256'] == discovered['corpus_sha256'], 'ranking_corpus_mismatch')
        result = apply_candidate_review(case['review_packet'], judged[cid]['review'])
        eligible = {d['source_path'] for d in result['audit'] if d['status'] == 'eligible'}
        by_method = {}
        for method in METHODS:
            hits = case['discovery']['methods'][method]
            paths = [h['source_path'] for h in hits]
            available = {d['source_path']: d for d in case['review_packet']['documents']}
            require(len(paths) == len(set(paths)) and set(paths) <= set(available), 'invalid_ranking_documents')
            require(all(h['source_sha256'] == available[h['source_path']]['source_sha256'] for h in hits), 'ranking_source_changed')
            by_method[method] = {'retrieved': len(hits), 'eligible': sum(h['source_path'] in eligible for h in hits),
                                 'paths': [h['source_path'] for h in hits]}
        output.append({'case_id': cid, 'result': result, 'methods': by_method})
    return output


def public_summary(results):
    """Projection intentionally excludes story text, names, reasoning and queries."""
    return {'schema_version': 1, 'method': 'bm25_source_retrieval_with_imported_ai_queries_and_independent_reviews',
            'assessment_unit': 'source_grounded_local_operation; not complete motif recognition or literary quality',
            'case_count': len(results), 'scope': 'union_of_top_3_only; no exhaustive recall or human gold labels',
            'cases': [{'case_id': c['case_id'], 'methods': c['methods'],
                       'decisions': [{'source_path': d['source_path'], 'status': d['status']} for d in c['result']['audit']]}
                      for c in results]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('discover')
    prepare.add_argument('--input', required=True)
    prepare.add_argument('--analysis', nargs='+', required=True)
    prepare.add_argument('--output', required=True)
    evaluate = sub.add_parser('evaluate')
    evaluate.add_argument('--input', required=True)
    evaluate.add_argument('--reviews', nargs='+', required=True)
    evaluate.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'discover':
            analyses = {'cases': [c for p in args.analysis for c in read(p)['cases']]}
            result = discover_cases(read(args.input), analyses, read(HERE / 'corpus.json'), REPO)
            output = fresh_dir(args.output)
            write(output / 'discovered.json', result)
            write(output / 'review-input.json', {'cases': [{'case_id': c['case_id'], 'packet': c['review_packet']} for c in result['cases']]})
            print(json.dumps({'cases': len(result['cases']), 'limit': result['limit'], 'output': str(output)}))
        else:
            reviews = {'cases': [c for p in args.reviews for c in read(p)['cases']]}
            results = evaluate_cases(read(args.input), reviews)
            output = fresh_dir(args.output)
            write(output / 'results.json', {'cases': results})
            write(output / 'summary.json', public_summary(results))
            print(json.dumps(public_summary(results), ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, UnicodeError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
