"""Pure reviewed-state retrieval with exact, locally prepared embedding bindings.

The engine validates the source context and catalog before calling this module.
No file, model, network or knowledge-store operations occur here. Similarities
only order retrieval candidates; they confer no semantic or writing permission.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from itertools import islice

from retrieval_pilot import bm25_rank, rrf_fuse
from typed_knowledge_discovery import _validated_vectors


MODEL_SHA256 = 'b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63'
DIMENSIONS = 768
INPUT_FORMAT = 'qmd-format-functions-v1'
QMD_VERSION = '2.1.0'
RUNTIME_VERSION = '3.18.1'
RRF_K = 60


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    """Return the exact UTF-8 JSON bytes used by the local embedding workflow."""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def _document_id(card):
    return _sha('document\0' + card['title'] + '\0' + card['retrieval_text'])


def _project_cards(cards, for_embedding):
    _require(isinstance(cards, list), 'retrieval_cards_must_be_list')
    projected, seen = [], set()
    for card in cards:
        _require(isinstance(card, dict), 'retrieval_card_must_be_object')
        for name in ('id', 'title', 'retrieval_text'):
            _require(isinstance(card.get(name), str) and bool(card[name].strip()),
                     'invalid_retrieval_card_' + name)
            if for_embedding and name in ('title', 'retrieval_text'):
                _require('\0' not in card[name], 'nul_in_retrieval_card_' + name)
        _require(card['id'] not in seen, 'duplicate_retrieval_card_id')
        seen.add(card['id'])
        projected.append({name: card[name] for name in ('id', 'title', 'retrieval_text')})
    projected.sort(key=lambda card: card['id'])
    return projected


def prepare_embedding_bundle(context, query, cards):
    """Bind full reviewed context and exact texts to the local encoder format.

    Equal title/text content shares a vector; each card remains a candidate.
    Document fields reject the NUL separator used by the existing encoder ID
    scheme. Query text is a single field and preserves all its characters.
    """
    _require(isinstance(context, dict), 'retrieval_context_must_be_object')
    _require(isinstance(query, str), 'retrieval_query_must_be_text')
    projected = _project_cards(cards, True)
    dataset = {'schema_version': 1, 'retrieval_version': 'recommendation-retrieval-v1',
               'context': copy.deepcopy(context), 'query': query, 'cards': projected,
               'embedding_contract': {'model_sha256': MODEL_SHA256, 'dimensions': DIMENSIONS,
                                      'input_format': INPUT_FORMAT, 'qmd_version': QMD_VERSION,
                                      'runtime_version': RUNTIME_VERSION}}
    items = {}
    for card in projected:
        identity = _document_id(card)
        items[identity] = {'id': identity, 'kind': 'document', 'title': card['title'],
                           'text': card['retrieval_text']}
    if query.strip():
        identity = _sha('query\0' + query)
        items[identity] = {'id': identity, 'kind': 'query', 'title': '', 'text': query}
    embedding_input = {'schema_version': 1, 'dataset_sha256': _sha(encoded(dataset)),
                       'items': list(items.values())}
    return {'dataset': dataset, 'embedding_input': embedding_input}


def _artifact_vectors(bundle, artifact):
    _require(isinstance(artifact, dict) and set(artifact) == {'dataset', 'embedding_input', 'embeddings'},
             'invalid_embedding_artifact')
    # Byte comparison also rejects JSON booleans substituted for integer fields.
    for key in ('dataset', 'embedding_input'):
        _require(encoded(artifact[key]) == encoded(bundle[key]), 'embedding_' + key + '_mismatch')
    payload = artifact['embeddings']
    _require(isinstance(payload, dict), 'embeddings_must_be_object')
    for field, expected in (('model_sha256', MODEL_SHA256), ('prefix', INPUT_FORMAT),
                            ('qmd_version', QMD_VERSION), ('runtime_version', RUNTIME_VERSION)):
        _require(payload.get(field) == expected, 'embedding_' + field + '_mismatch')
    _require(type(payload.get('dimensions')) is int and payload['dimensions'] == DIMENSIONS,
             'embedding_dimensions_mismatch')
    dataset_sha = _sha(encoded(bundle['dataset']))
    input_sha = _sha(encoded(bundle['embedding_input']))
    vectors, dimensions = _validated_vectors(payload, bundle['embedding_input']['items'],
                                             dataset_sha, input_sha)
    _require(dimensions == DIMENSIONS, 'embedding_dimensions_mismatch')
    provenance = {'embedding_sha256': _sha(encoded(payload)), 'dataset_sha256': dataset_sha,
                  'input_sha256': input_sha, 'model_sha256': MODEL_SHA256, 'dimensions': dimensions}
    return vectors, provenance


def _budget_hits(ranking, top_k, eligible_card_ids, action_ids_by_card):
    if action_ids_by_card is not None:
        # Keep eligible IDs in retrieval order: max() then breaks equal gains by rank.
        remaining = [hit['source_path'] for hit in ranking if hit['source_path'] in action_ids_by_card]
        selected, covered = set(), set()
        while remaining and len(selected) < top_k:
            best = max(remaining, key=lambda card_id: len(action_ids_by_card[card_id] - covered))
            if action_ids_by_card[best] <= covered:
                selected.update(remaining[:top_k - len(selected)])
                break
            selected.add(best)
            covered.update(action_ids_by_card[best])
            remaining.remove(best)
        # Coverage allocates membership only. Review retains original ranks and scores.
        return [hit for hit in ranking if hit['source_path'] in selected]
    if eligible_card_ids is None:
        return ranking[:top_k]
    return list(islice((hit for hit in ranking if hit['source_path'] in eligible_card_ids), top_k))


def rank_cards(context, query, cards, method='bm25', top_k=2, embedding_artifact=None, *,
               eligible_card_ids=None, action_ids_by_card=None):
    """Rank all candidate cards before applying the common 0..50 result budget.

    An optional set of eligible card IDs filters the complete ranking before
    truncation. Alternatively, a mapping of compatible card IDs to action ID
    sets allocates slots by uncovered action count, breaking ties by rank.
    Lexical statistics, embedding bindings and RRF rank positions always use
    the original catalog.
    A supplied artifact is always validated, including BM25 and zero budgets.
    Vector/hybrid nonempty queries require complete matching artifacts and never
    fall back to lexical search. BM25 returns only lexical hits, with no fill.
    """
    _require(isinstance(method, str) and method in ('bm25', 'vector', 'hybrid'), 'invalid_retrieval_method')
    _require(type(top_k) is int and 0 <= top_k <= 50, 'invalid_top_k')
    if eligible_card_ids is not None:
        _require(isinstance(eligible_card_ids, (set, frozenset))
                 and all(isinstance(card_id, str) and card_id.strip() for card_id in eligible_card_ids),
                 'invalid_eligible_card_ids')
    if action_ids_by_card is not None:
        _require(eligible_card_ids is None and isinstance(action_ids_by_card, dict)
                 and all(isinstance(card_id, str) and card_id.strip()
                         and isinstance(actions, (set, frozenset)) and actions
                         and all(isinstance(action, str) and action.strip() for action in actions)
                         for card_id, actions in action_ids_by_card.items()), 'invalid_action_ids_by_card')
    if method == 'bm25' and embedding_artifact is None:
        _require(isinstance(context, dict), 'retrieval_context_must_be_object')
        _require(isinstance(query, str), 'retrieval_query_must_be_text')
        projected = _project_cards(cards, False)
        chunks = [{'source_path':c['id'],'chunk_id':c['id'],'title':c['title'],
                   'text':c['retrieval_text']} for c in projected]
        ranking = bm25_rank(query, chunks) if query.strip() else []
        return {'ranking': _budget_hits(ranking, top_k, eligible_card_ids, action_ids_by_card), 'provenance': {}}
    bundle = prepare_embedding_bundle(context, query, cards)
    provenance, vectors = {}, None
    if embedding_artifact is not None:
        vectors, provenance = _artifact_vectors(bundle, embedding_artifact)
    if method != 'bm25' and query.strip():
        _require(vectors is not None, 'embedding_artifact_required')
    if method == 'bm25':
        provenance = {}
    elif vectors is not None:
        provenance = {'method': method, **provenance}
        if method == 'hybrid':
            provenance['rrf_k'] = RRF_K
    if not query.strip():
        return {'ranking': [], 'provenance': provenance}
    projected = bundle['dataset']['cards']
    chunks = [{'source_path': card['id'], 'chunk_id': card['id'], 'title': card['title'],
               'text': card['retrieval_text']} for card in projected]
    lexical = bm25_rank(query, chunks) if method in ('bm25', 'hybrid') else []
    vector_hits = []
    if method in ('vector', 'hybrid'):
        query_vector = vectors[_sha('query\0' + query)]
        vector_hits = [{'source_path': card['id'], 'chunk_id': card['id'],
                        'score': math.fsum(a * b for a, b in zip(query_vector, vectors[_document_id(card)]))}
                       for card in projected]
        vector_hits.sort(key=lambda hit: (-hit['score'], hit['source_path']))
    ranking = (lexical if method == 'bm25' else vector_hits if method == 'vector'
               else rrf_fuse([lexical, vector_hits], k=RRF_K))
    hits = _budget_hits(ranking, top_k, eligible_card_ids, action_ids_by_card)
    return {'ranking': [{'source_path': hit['source_path'], 'chunk_id': hit['chunk_id'],
                         'score': float(hit['score'])} for hit in hits],
            'provenance': provenance}
