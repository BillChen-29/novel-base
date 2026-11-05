#!/usr/bin/env python3
"""Replay current-state cards using existing fact, POV and motif gates.

The runner imports AI judgments; it does not interpret source prose or invoke a
model. Retrieval queries built from state use only reviewed original story facts,
never the card-derived condition probes. All proposals remain future options.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / 'scripts'))
from knowledge_candidate_preparer import prepare_candidates
from motif_matcher import _validate_catalog, match_motifs
from retrieval_pilot import bm25_rank
from semantic_review import _digest
from typed_knowledge_discovery import _validated_vectors

MODEL_SHA256 = 'b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63'
METHODS = ('bm25_raw', 'bm25_state', 'vector_raw', 'vector_state')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def shape(value, fields, name):
    require(isinstance(value, dict) and set(value) == set(fields), 'invalid_' + name)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), 'invalid_' + name)
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', value), 'invalid_public_identifier')
    return value


def case_id(value):
    require(isinstance(value, str) and re.fullmatch(r'case-[0-9]{2,3}', value), 'invalid_case_id')
    return value


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def read(path):
    def invalid_constant(value):
        raise ValueError('nonfinite_json_' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid_constant)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encoded(value))


def fresh_dir(path):
    destination = Path(path).expanduser().absolute()
    require(not any(p.is_symlink() for p in (destination, *destination.parents)), 'output_symlink')
    runtime_path = (REPO / 'runtime-data').absolute()
    require(not any(p.is_symlink() for p in (runtime_path, *runtime_path.parents)), 'runtime_symlink')
    runtime = runtime_path.resolve()
    require(destination.resolve() != runtime and destination.resolve().is_relative_to(runtime), 'output_outside_runtime')
    require(not destination.exists(), 'output_already_exists')
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValueError('output_already_exists') from error
    return destination


def cards(catalog, repo_root):
    checked = _validate_catalog(catalog, repo_root)
    require(bool(checked), 'cards_required')
    variants = set()
    for card in checked.values():
        identifier(card['id'])
        require(card['roles'] == {'actor': 'character', 'focus': 'object'}, 'card_roles_must_be_actor_focus')
        text(card.get('retrieval_text'), 'retrieval_text')
        text(card.get('basis'), 'card_basis')
        for group in ('conditions', 'stages', 'variants'):
            for entry in card[group]:
                identifier(entry['id'])
                if group == 'variants':
                    require(entry['id'] not in variants, 'duplicate_variant_id')
                    variants.add(entry['id'])
    return checked


def prepare_cases(fixtures, catalog, repo_root):
    """Bind the same cards to every case; all anchors are review context only."""
    shape(fixtures, {'cases'}, 'fixtures')
    records = fixtures['cases']
    require(isinstance(records, list) and bool(records), 'cases_required')
    definitions = cards(catalog, repo_root)
    seen, result = set(), []
    for case in records:
        shape(case, {'case_id', 'project', 'bindings'}, 'case')
        cid = case_id(case['case_id'])
        require(cid not in seen, 'duplicate_case_id')
        seen.add(cid)
        project = case['project']
        require(isinstance(project, dict), 'invalid_project')
        scenes = project.get('scenes')
        require(isinstance(scenes, list) and len(scenes) == 1 and isinstance(scenes[0], dict), 'one_prefix_scene_required')
        scene = scenes[0]
        text(scene.get('text'), 'prefix')
        text(scene.get('id'), 'scene_id')
        bindings = case['bindings']
        shape(bindings, {'actor', 'focus'}, 'bindings')
        text(bindings['focus'], 'focus')
        require(bindings['actor'] == project.get('pov_character'), 'actor_must_be_pov')
        instances = [{'id': card['id'], 'motif_id': card['id'], 'bindings': copy.deepcopy(bindings),
                      'anchors': {condition['id']: {'scene_id': scene['id'], 'start': 0, 'end': len(scene['text'])}
                                  for condition in card['conditions']}} for card in definitions.values()]
        prepared = prepare_candidates(project, catalog, instances, repo_root)
        result.append({'case_id': cid, 'base_fact_ids': [fact['id'] for fact in project['facts']], **prepared})
    return {'schema_version': 1, 'fixtures': copy.deepcopy(fixtures), 'catalog_sha256': _digest(catalog), 'cases': result}


def validated_matches(prepared, reviews, catalog, repo_root):
    shape(prepared, {'schema_version', 'fixtures', 'catalog_sha256', 'cases'}, 'prepared')
    regenerated = prepare_cases(prepared['fixtures'], catalog, repo_root)
    require(_digest(prepared) == _digest(regenerated), 'prepared_changed')
    shape(reviews, {'reviews'}, 'reviews')
    require(isinstance(reviews['reviews'], list), 'invalid_reviews')
    by_review = {}
    for record in reviews['reviews']:
        shape(record, {'case_id', 'review'}, 'review_record')
        cid = case_id(record['case_id'])
        require(cid not in by_review, 'duplicate_review_case')
        by_review[cid] = record['review']
    require(set(by_review) == {case['case_id'] for case in prepared['cases']}, 'review_case_coverage')
    matches = {}
    for case in prepared['cases']:
        review = by_review[case['case_id']]
        require(isinstance(review, dict) and isinstance(review.get('decisions'), list), 'invalid_review')
        candidates = {candidate['fact_id']: candidate for candidate in case['packet']['candidates']}
        decisions = review['decisions']
        require(all(isinstance(d, dict) and isinstance(d.get('fact_id'), str) for d in decisions), 'invalid_decision')
        require(len(decisions) == len(candidates) and {d['fact_id'] for d in decisions} == set(candidates), 'review_fact_coverage')
        for decision in decisions:
            knowledge = decision.get('knowledge')
            require(isinstance(knowledge, list) and all(isinstance(k, dict) and isinstance(k.get('character_id'), str) for k in knowledge), 'invalid_knowledge')
            claimed = candidates[decision['fact_id']]['claimed_known_by']
            require(len(knowledge) == len(claimed) and {k['character_id'] for k in knowledge} == set(claimed), 'review_knowledge_coverage')
        # Existing engine validates source references, semantic/POV labels,
        # project/review bindings, templates, conditions and stage readiness.
        matches[case['case_id']] = match_motifs(case['project'], case['packet'], review, catalog, repo_root)
    return matches


def embedding_item(kind, value, title=''):
    key = 'query\0' + value if kind == 'query' else 'document\0' + title + '\0' + value
    return {'id': hashlib.sha256(key.encode('utf-8')).hexdigest(), 'kind': kind, 'title': title, 'text': value}


def prepare_embedding_inputs(prepared, reviews, catalog, repo_root):
    """Create full raw and separately reviewed base-state representations."""
    matches = validated_matches(prepared, reviews, catalog, repo_root)
    items, queries = {}, []
    for card in catalog['motifs']:
        item = embedding_item('document', card['retrieval_text'], card['title'])
        items[item['id']] = item
    for case in prepared['cases']:
        base_ids = set(case['base_fact_ids'])
        known = matches[case['case_id']]['pov_view']['facts']
        state = '\n'.join(fact['text'] for fact in known if fact['id'] in base_ids)
        raw = case['packet']['scenes'][0]['text']
        queries.append({'case_id': case['case_id'], 'raw': raw, 'state': state})
        for value in (raw, state):
            if value:
                item = embedding_item('query', value)
                items[item['id']] = item
    dataset = {'schema_version': 1, 'catalog_sha256': _digest(catalog), 'prepared_sha256': _digest(prepared),
               'reviews_sha256': _digest(reviews), 'queries': queries, 'items': list(items.values())}
    return {'dataset': dataset, 'embedding_input': {'schema_version': 1,
            'dataset_sha256': hashlib.sha256(encoded(dataset)).hexdigest(), 'items': list(items.values())}}


def rank_cards(catalog, queries, vectors):
    chunks = [{'source_path': card['id'], 'chunk_id': card['id'], 'title': card['title'], 'text': card['retrieval_text']}
              for card in catalog['motifs']]
    documents = {card['id']: embedding_item('document', card['retrieval_text'], card['title'])['id'] for card in catalog['motifs']}
    result = {}
    for name in METHODS:
        mode, representation = name.split('_')
        query = queries[representation]
        if not query:
            result[name] = []
        elif mode == 'bm25':
            result[name] = [{'card_id': hit['source_path'], 'score': hit['score']} for hit in bm25_rank(query, chunks)[:2]]
        else:
            q = vectors[embedding_item('query', query)['id']]
            hits = [{'card_id': cid, 'score': math.fsum(a * b for a, b in zip(q, vectors[identity]))}
                    for cid, identity in documents.items()]
            result[name] = sorted(hits, key=lambda h: (-h['score'], h['card_id']))[:2]
    return result


def evaluate_run(prepared, reviews, catalog, repo_root, run_dir):
    bundle = prepare_embedding_inputs(prepared, reviews, catalog, repo_root)
    directory = Path(run_dir)
    require(_digest(read(directory / 'dataset.json')) == _digest(bundle['dataset']), 'embedding_dataset_changed')
    dataset_hash = file_sha(directory / 'dataset.json')
    expected_input = bundle['embedding_input'] | {'dataset_sha256': dataset_hash}
    require(_digest(read(directory / 'embedding-input.json')) == _digest(expected_input), 'embedding_input_changed')
    payload = read(directory / 'embeddings.json')
    require(isinstance(payload, dict) and payload.get('model_sha256') == MODEL_SHA256, 'embedding_model_mismatch')
    vectors, dimensions = _validated_vectors(payload, expected_input['items'], dataset_hash, file_sha(directory / 'embedding-input.json'))
    matches = validated_matches(prepared, reviews, catalog, repo_root)
    variant_cards = {variant['id']: card['id'] for card in catalog['motifs'] for variant in card['variants']}
    by_query = {query['case_id']: query for query in bundle['dataset']['queries']}
    results, summaries = [], []
    for case in prepared['cases']:
        cid = case['case_id']
        matched = matches[cid]
        pool = matched['writer_packet']['proposals']
        pool_ready = {variant_cards[p['id']] for p in pool}
        rankings = rank_cards(catalog, by_query[cid], vectors)
        methods, metrics = {}, {}
        for name, ranking in rankings.items():
            selected = [hit['card_id'] for hit in ranking]
            proposals = [copy.deepcopy(p) for p in pool if variant_cards[p['id']] in selected]
            needed = {fact for p in proposals for fact in p['evidence_fact_ids']}
            if proposals:
                needed.update(case['base_fact_ids'])
            facts = [copy.deepcopy(f) for f in matched['pov_view']['facts'] if f['id'] in needed]
            methods[name] = {'ranked_card_ids': selected, 'ranking': ranking,
                             'writer_packet': {'facts': facts, 'proposals': proposals}, 'memory_write_allowed': False}
            metrics[name] = {'ranked_card_ids': selected, 'ready_variant_ids': [p['id'] for p in proposals],
                             'ready_cards_retrieved': len(pool_ready & set(selected)), 'pool_ready_cards': len(pool_ready),
                             'ready_card_recall': len(pool_ready & set(selected)) / len(pool_ready) if pool_ready else None}
        summaries.append({'case_id': cid, 'pool_ready_variant_ids': [p['id'] for p in pool],
                          'cards': [{'card_id': audit['motif_id'], 'supported_stage_ids': audit['supported_stage_ids'],
                                     'supported_condition_ids': audit['supported_condition_ids'],
                                     'contradicted_condition_ids': audit['contradicted_condition_ids'],
                                     'unknown_condition_ids': audit['unknown_condition_ids']}
                                    for audit in matched['author_audit']], 'methods': metrics})
        results.append({'case_id': cid, 'assessed_pool': matched, 'methods': methods})
    totals = {}
    for name in METHODS:
        rows = [c['methods'][name] for c in summaries]
        denominator = sum(row['pool_ready_cards'] for row in rows)
        numerator = sum(row['ready_cards_retrieved'] for row in rows)
        totals[name] = {'ready_cards_retrieved': numerator, 'pool_ready_cards': denominator,
                        'micro_ready_card_recall': numerator / denominator if denominator else None,
                        'zero_ready_cases': sum(row['pool_ready_cards'] == 0 for row in rows)}
    summary = {'schema_version': 1, 'scope': 'authored_cards_imported_ai_conditions_not_human_gold',
               'case_count': len(results), 'card_count': len(catalog['motifs']), 'top_k': 2,
               'model_sha256': MODEL_SHA256, 'dimensions': dimensions, 'cases': summaries, 'methods': totals}
    return {'schema_version': 1, 'summary': summary, 'cases': results,
            'catalog_sha256': _digest(catalog), 'prepared_sha256': _digest(prepared), 'reviews_sha256': _digest(reviews)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--fixtures', type=Path, default=HERE / 'fixtures-public.json')
    for name in ('inputs', 'evaluate'):
        command = sub.add_parser(name)
        command.add_argument('--prepared', required=True, type=Path)
        command.add_argument('--reviews', required=True, type=Path)
        if name == 'evaluate': command.add_argument('--run-dir', required=True, type=Path)
    for command in sub.choices.values():
        command.add_argument('--catalog', type=Path, default=HERE / 'catalog.json')
        command.add_argument('--repo-root', type=Path, default=REPO)
        command.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    catalog = read(args.catalog)
    if args.command == 'prepare':
        result = prepare_cases(read(args.fixtures), catalog, args.repo_root)
        files = {'prepared.json': result, 'review-input.json': {'reviews': [
            {'case_id': c['case_id'], 'packet': c['packet']} for c in result['cases']]}}
    elif args.command == 'inputs':
        result = prepare_embedding_inputs(read(args.prepared), read(args.reviews), catalog, args.repo_root)
        files = {'dataset.json': result['dataset'], 'embedding-input.json': result['embedding_input']}
    else:
        result = evaluate_run(read(args.prepared), read(args.reviews), catalog, args.repo_root, args.run_dir)
        files = {'results.json': result, 'summary.json': result['summary']}
    output = fresh_dir(args.output)
    for name, value in files.items():
        write_new(output / name, value)
    print(json.dumps({'command': args.command, 'output': str(output)}))


if __name__ == '__main__':
    main()
