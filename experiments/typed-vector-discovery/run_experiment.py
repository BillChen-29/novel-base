#!/usr/bin/env python3
"""Replay frozen, typed retrieval and imported full-pool AI assessments.

This runner makes no model/API calls. Complete coordinate checks authenticate
references, not the semantic correctness of imported judgments. Whole arcs,
literary quality and unreviewed knowledge types are outside these measurements.
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
from knowledge_discovery import build_index
from typed_knowledge_discovery import prepare_embedding_dataset, rank_typed
from semantic_review import _digest

MODEL_SHA256 = 'b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63'
LEVELS = ('current_structure', 'specific_fragment', 'insufficient_evidence', 'contradicted')
POSITIVE = {'current_structure', 'specific_fragment'}
VERDICTS = {'supported', 'insufficient_evidence', 'contradicted'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def shape(value, keys, name):
    require(isinstance(value, dict) and set(value) == set(keys), 'invalid_' + name)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), 'invalid_' + name)
    return value


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def read(path):
    def reject_constant(value):
        raise ValueError('nonfinite_json_' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=reject_constant)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    """Exclusive creation also refuses pre-existing symlinks and hard links."""
    with Path(path).open('xb') as stream:
        stream.write(encoded(value))


def fresh_dir(path):
    destination = Path(path).expanduser().absolute()
    require(not any(p.is_symlink() for p in (destination, *destination.parents)), 'output_symlink')
    runtime = (REPO / 'runtime-data').resolve()
    require(destination.resolve() != runtime and destination.resolve().is_relative_to(runtime), 'output_outside_runtime')
    require(not destination.exists(), 'output_already_exists')
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValueError('output_already_exists') from error
    return destination


def indexed(envelope, field):
    shape(envelope, {'cases'}, 'case_envelope')
    cases = envelope['cases']
    require(isinstance(cases, list) and bool(cases), 'cases_required')
    result = {}
    for case in cases:
        shape(case, {'case_id', field}, 'case')
        cid = case['case_id']
        require(isinstance(cid, str) and re.fullmatch(r'(?:real|public|case)-[0-9]{2,3}', cid), 'anonymous_case_id_required')
        require(cid not in result, 'duplicate_case')
        result[cid] = case[field]
    return result


def validate_case_ids(cases):
    indexed({'cases': [{'case_id': c.get('case_id'), 'item': c} if isinstance(c, dict) else c
                       for c in cases]}, 'item')


def frozen_index(repo_root, manifest):
    require(isinstance(manifest, dict) and type(manifest.get('schema_version')) is int
            and manifest['schema_version'] == 1, 'invalid_corpus_manifest')
    documents = manifest.get('documents')
    require(isinstance(documents, list) and bool(documents)
            and all(isinstance(d, dict) for d in documents), 'invalid_corpus_documents')
    index = build_index(repo_root, [d.get('path') for d in documents])
    expected = {d['path']: d for d in documents}
    for document in index['documents']:
        frozen = expected[document['source_path']]
        require(all(document[k] == frozen.get(fk) for k, fk in (
            ('source_sha256', 'sha256'), ('title', 'title'), ('kind', 'kind'))), 'frozen_corpus_changed')
    return index


def make_review_input(dataset):
    prepared = prepare_embedding_dataset(dataset['index'], dataset['cases'])
    require(_digest(prepared['dataset']) == _digest(dataset), 'dataset_changed')
    validate_case_ids(dataset['cases'])
    protocol = read(HERE / 'assessment-protocol.json')
    documents = [{key: d[key] for key in ('source_path', 'title', 'kind', 'source_sha256', 'text')}
                 for d in dataset['index']['documents'] if d['kind'] in {'motif', 'scenario'}]
    require(bool(documents), 'plot_pool_required')
    pool_hash = _digest([{key: d[key] for key in ('source_path', 'kind', 'source_sha256')}
                         for d in documents])
    cases = []
    for case in dataset['cases']:
        packet = {'schema_version': 1, 'protocol': copy.deepcopy(protocol),
                  'snapshot': copy.deepcopy(case['snapshot']), 'documents': copy.deepcopy(documents),
                  'pool_sha256': pool_hash}
        packet['packet_sha256'] = _digest(packet)
        cases.append({'case_id': case['case_id'], 'packet': packet})
    return {'cases': cases}


def prepare_run(cases, repo_root, manifest, output):
    index = frozen_index(repo_root, manifest)
    prepared = prepare_embedding_dataset(index, cases)
    dataset = prepared['dataset']
    packets = make_review_input(dataset)
    dataset_hash = hashlib.sha256(encoded(dataset)).hexdigest()
    inputs = {'schema_version': 1, 'dataset_sha256': dataset_hash, 'items': prepared['items']}
    directory = fresh_dir(output)
    write_new(directory / 'dataset.json', dataset)
    write_new(directory / 'embedding-input.json', inputs)
    write_new(directory / 'review-input.json', packets)
    return directory


def check_refs(refs, source, required):
    require(isinstance(refs, list) and (bool(refs) or not required), 'evidence_required')
    for ref in refs:
        shape(ref, {'start', 'end', 'quote'}, 'evidence')
        start, end = ref['start'], ref['end']
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(source), 'evidence_outside_source')
        require(source[start:end] == text(ref['quote'], 'evidence_quote'), 'evidence_quote_mismatch')


def validate_review(packet, review):
    shape(review, {'schema_version', 'packet_sha256', 'reviewer', 'decisions'}, 'review')
    require(type(review['schema_version']) is int and review['schema_version'] == 1, 'invalid_review_schema')
    require(review['packet_sha256'] == packet['packet_sha256'], 'review_binding_mismatch')
    shape(review['reviewer'], {'kind', 'name'}, 'reviewer')
    require(review['reviewer']['kind'] == 'agent_review', 'invalid_reviewer_kind')
    text(review['reviewer']['name'], 'reviewer_name')
    decisions = review['decisions']
    require(isinstance(decisions, list), 'decisions_required')
    documents = {d['source_path']: d for d in packet['documents']}
    checked = {}
    story = packet['snapshot']['text']
    for decision in decisions:
        shape(decision, {'source_path', 'match_level', 'matched_structure', 'reason', 'story_evidence',
                         'knowledge_evidence', 'missing_conditions', 'pov', 'next_transition'}, 'decision')
        path = decision['source_path']
        require(isinstance(path, str) and path in documents and path not in checked, 'unknown_or_duplicate_decision')
        level = decision['match_level']
        require(isinstance(level, str) and level in LEVELS, 'invalid_match_level')
        text(decision['matched_structure'], 'matched_structure')
        text(decision['reason'], 'reason')
        check_refs(decision['story_evidence'], story, level != 'insufficient_evidence')
        check_refs(decision['knowledge_evidence'], documents[path]['text'], True)
        missing = decision['missing_conditions']
        require(isinstance(missing, list), 'invalid_missing_conditions')
        for condition in missing:
            text(condition, 'missing_condition')
        require(level != 'specific_fragment' or bool(missing), 'fragment_missing_conditions_required')
        pov = decision['pov']
        shape(pov, {'verdict', 'reason', 'evidence'}, 'pov')
        require(isinstance(pov['verdict'], str) and pov['verdict'] in VERDICTS, 'invalid_pov_verdict')
        text(pov['reason'], 'pov_reason')
        check_refs(pov['evidence'], story, pov['verdict'] != 'insufficient_evidence')
        fit = level in POSITIVE and pov['verdict'] == 'supported'
        transition = decision['next_transition']
        if transition is not None:
            text(transition, 'next_transition')
            require(fit, 'transition_requires_supported_fit')
        checked[path] = copy.deepcopy(decision) | {'positive': fit, 'proposal_ready': fit and transition is not None}
    require(set(checked) == set(documents), 'complete_plot_pool_review_required')
    return checked


def measure(hits, judgments):
    positive_paths = {p for p, d in judgments.items() if d['positive']}
    selected_paths = {h['source_path'] for h in hits}
    selected = []
    counts = {'slots': len(hits), 'reviewed_plot_count': 0, 'unassessed_count': 0,
              'current_structure_hits': 0, 'specific_fragment_hits': 0, 'positive_hits': 0,
              'proposal_ready_hits': 0, 'unknown_count': 0, 'contradicted_count': 0, 'pov_unusable_count': 0}
    for hit in hits:
        path = hit['source_path']
        decision = judgments.get(path)
        entry = {'source_path': path, 'kind': hit['kind']}
        if decision is None:
            counts['unassessed_count'] += 1
            entry.update(match_level='not_assessed', positive=None, proposal_ready=None)
        else:
            counts['reviewed_plot_count'] += 1
            level, fit = decision['match_level'], decision['positive']
            entry.update(match_level=level, positive=fit, proposal_ready=decision['proposal_ready'])
            counts['positive_hits'] += int(fit)
            counts['proposal_ready_hits'] += int(decision['proposal_ready'])
            counts['current_structure_hits'] += int(fit and level == 'current_structure')
            counts['specific_fragment_hits'] += int(fit and level == 'specific_fragment')
            counts['unknown_count'] += int(level == 'insufficient_evidence')
            counts['contradicted_count'] += int(level == 'contradicted')
            counts['pov_unusable_count'] += int(level in POSITIVE and not fit)
        selected.append(entry)
    return counts | {'selected': selected, 'positive_total': len(positive_paths),
                     'recall': len(positive_paths & selected_paths) / len(positive_paths) if positive_paths else None,
                     'missed_positive_paths': sorted(positive_paths - selected_paths)}


def summarize(rankings, judgments):
    cases = []
    for case in rankings['cases']:
        cid = case['case_id']
        assessment = judgments[cid]
        cases.append({'case_id': cid, 'reviewed_plot_count': len(assessment),
                      'assessment_counts': {level: sum(d['match_level'] == level for d in assessment.values()) for level in LEVELS},
                      'positive_count': sum(d['positive'] for d in assessment.values()),
                      'proposal_ready_count': sum(d['proposal_ready'] for d in assessment.values()),
                      'positive_paths': sorted(p for p, d in assessment.items() if d['positive']),
                      'methods': {name: {'global': measure(method['global'], assessment),
                                         'plot': measure(method['by_type']['plot'], assessment)}
                                  for name, method in case['methods'].items()}})
    totals = {}
    for name in cases[0]['methods']:
        totals[name] = {}
        for route in ('global', 'plot'):
            entries = [case['methods'][name][route] for case in cases]
            keys = ('slots', 'reviewed_plot_count', 'unassessed_count', 'current_structure_hits',
                    'specific_fragment_hits', 'positive_hits', 'proposal_ready_hits', 'unknown_count',
                    'contradicted_count', 'pov_unusable_count', 'positive_total')
            count = {key: sum(entry[key] for entry in entries) for key in keys}
            recalls = [entry['recall'] for entry in entries if entry['recall'] is not None]
            totals[name][route] = count | {'micro_recall': count['positive_hits'] / count['positive_total'] if count['positive_total'] else None,
                                           'macro_recall_nonempty': sum(recalls) / len(recalls) if recalls else None,
                                           'zero_positive_cases': len(entries) - len(recalls)}
    return {'schema_version': 1, 'assessment_scope': 'full_plot_pool_current_structure_and_specific_fragment',
            'whole_arc_completion': 'not_assessed', 'review_source': 'imported_current_ai_not_human_gold',
            'unreviewed_types': ['character', 'pacing', 'style', 'technique'],
            'case_count': len(cases), 'reviewed_pairs': sum(len(d) for d in judgments.values()),
            'positive_count': sum(case['positive_count'] for case in cases),
            'proposal_ready_count': sum(case['proposal_ready_count'] for case in cases),
            'corpus_sha256': rankings['corpus_sha256'], 'model_sha256': rankings['model_sha256'],
            'dimensions': rankings['dimensions'], 'limit': rankings['limit'], 'cases': cases, 'methods': totals}


def evaluate_run(run_dir, reviews, repo_root, manifest):
    directory = Path(run_dir)
    dataset = read(directory / 'dataset.json')
    shape(dataset, {'schema_version', 'index', 'cases', 'content_sha256'}, 'dataset')
    prepared = prepare_embedding_dataset(dataset['index'], dataset['cases'])
    require(_digest(dataset) == _digest(prepared['dataset']), 'dataset_changed')
    require(dataset['index'] == frozen_index(repo_root, manifest), 'frozen_corpus_changed')
    validate_case_ids(dataset['cases'])
    dataset_hash = file_sha(directory / 'dataset.json')
    inputs = read(directory / 'embedding-input.json')
    expected = {'schema_version': 1, 'dataset_sha256': dataset_hash, 'items': prepared['items']}
    require(_digest(inputs) == _digest(expected), 'embedding_input_does_not_match_dataset')
    packets = make_review_input(dataset)
    require(_digest(read(directory / 'review-input.json')) == _digest(packets), 'review_input_changed')
    review_map = indexed(reviews, 'review')
    packet_map = indexed(packets, 'packet')
    require(set(review_map) == set(packet_map), 'review_case_coverage_mismatch')
    judgments = {cid: validate_review(packet, review_map[cid]) for cid, packet in packet_map.items()}
    payload = read(directory / 'embeddings.json')
    require(isinstance(payload, dict) and payload.get('model_sha256') == MODEL_SHA256, 'embedding_model_mismatch')
    rankings = rank_typed(dataset, payload, dataset_hash, file_sha(directory / 'embedding-input.json'), limit=3)

    def proposals(assessment, paths):
        return [{'source_path': path, 'match_level': assessment[path]['match_level'],
                 'proposed_future': assessment[path]['next_transition'], 'memory_write_allowed': False}
                for path in paths if path in assessment and assessment[path]['proposal_ready']]

    # Exhaustive judgments are evaluation references, not candidates supplied by
    # a retrieval method. A method can propose only what it actually retrieved.
    retrieved = {}
    for case in rankings['cases']:
        cid = case['case_id']
        retrieved[cid] = {
            name: {route: proposals(judgments[cid], [hit['source_path'] for hit in hits])
                   for route, hits in (('global', method['global']), ('plot', method['by_type']['plot']))}
            for name, method in case['methods'].items()}
    return {'rankings': rankings, 'judgments': judgments, 'summary': summarize(rankings, judgments),
            'assessed_pool_proposals': {cid: proposals(ds, ds) for cid, ds in judgments.items()},
            'retrieved_proposals_by_method': retrieved}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--cases', required=True, type=Path)
    prepare.add_argument('--output', required=True, type=Path)
    evaluate = sub.add_parser('evaluate')
    evaluate.add_argument('--run-dir', required=True, type=Path)
    evaluate.add_argument('--reviews', required=True, type=Path)
    evaluate.add_argument('--output', required=True, type=Path)
    for command in (prepare, evaluate):
        command.add_argument('--repo-root', type=Path, default=REPO)
        command.add_argument('--manifest', type=Path, default=REPO / 'experiments/candidate-discovery/corpus.json')
    args = parser.parse_args(argv)
    manifest = read(args.manifest)
    if args.command == 'prepare':
        envelope = read(args.cases)
        shape(envelope, {'cases'}, 'case_envelope')
        output = prepare_run(envelope['cases'], args.repo_root, manifest, args.output)
    else:
        result = evaluate_run(args.run_dir, read(args.reviews), args.repo_root, manifest)
        output = fresh_dir(args.output)
        write_new(output / 'results.json', result)
        write_new(output / 'summary.json', result['summary'])
    print(json.dumps({'output': str(output), 'command': args.command}))


if __name__ == '__main__':
    main()
