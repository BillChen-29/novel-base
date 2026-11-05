"""Offline typed retrieval over one validated corpus and immutable query cases.

This module performs no I/O or model calls. Callers compute the two expected
SHA-256 values from the actual dataset/input files they loaded. Those byte hashes
are compared with embedding metadata; the dataset's independent content binding,
source hashes, prefix bindings, evidence offsets and exact embedding identities
are also validated. Hashes establish consistency, not authorship or trust.

Scores are ranking signals, not probabilities. Synthetic vectors are suitable
for contract tests only and say nothing about a real embedding model's quality.
"""
from __future__ import annotations

import copy
import math
import re

from knowledge_discovery import (_binding, _object, _require, _sha, _text,
                                 _validate_analysis, _validate_index,
                                 _validate_snapshot, _version)
from retrieval_pilot import bm25_rank, collapse_documents, rrf_fuse
from narrative_prototype import _classification


_TYPES = {'plot': ['motif', 'scenario'], 'craft': ['technique', 'style'],
          'pacing': ['pacing'], 'character': ['character']}
_DATASET_KEYS = {'schema_version', 'index', 'cases', 'content_sha256'}


def _validate_typed_index(index: dict) -> None:
    _validate_index(index)
    supported = {kind for kinds in _TYPES.values() for kind in kinds}
    for document in index['documents']:
        _, kind, eligible = _classification(document['source_path'])
        _require(eligible and kind in supported and document['kind'] == kind,
                 'document kind must match eligible source directory classification')


def _validate_cases(cases: object) -> None:
    _require(isinstance(cases, list) and bool(cases), 'cases must be a nonempty list')
    identities = set()
    for case in cases:
        _object(case, {'case_id', 'snapshot', 'analysis'}, 'case')
        identity = _text(case['case_id'], 'case_id')
        _require(identity not in identities, 'case_id must be unique')
        identities.add(identity)
        _validate_snapshot(case['snapshot'])
        _validate_analysis(case['analysis'], case['snapshot'])


def _document_id(chunk: dict) -> str:
    return _sha('document\0' + chunk['title'] + '\0' + chunk['text'])


def _query_id(text: str) -> str:
    return _sha('query\0' + text)


def _embedding_items(index: dict, cases: list[dict]) -> list[dict]:
    items = {}
    for document in index['documents']:
        for chunk in document['chunks']:
            identity = _document_id(chunk)
            items[identity] = {'id': identity, 'kind': 'document',
                               'title': chunk['title'], 'text': chunk['text']}
    for case in cases:
        for text in [case['snapshot']['text']] + [q['text'] for q in case['analysis']['queries']]:
            identity = _query_id(text)
            items[identity] = {'id': identity, 'kind': 'query', 'title': '', 'text': text}
    return list(items.values())


def prepare_embedding_dataset(index: dict, cases: list[dict]) -> dict:
    """Validate and copy all source/query content; emit unique embedding inputs.

    Full raw prefixes and every supplied abstraction remain untruncated. Equal
    text shares one vector, while repeated queries retain their separate votes.
    The caller writes ``dataset`` and creates an embedding-input envelope with
    ``schema_version=1``, ``dataset_sha256=<actual file hash>`` and ``items``.
    """
    _validate_typed_index(index)
    _validate_cases(cases)
    dataset = {'schema_version': 1, 'index': copy.deepcopy(index), 'cases': copy.deepcopy(cases)}
    dataset['content_sha256'] = _binding(dataset, 'content_sha256')
    return {'dataset': dataset, 'items': _embedding_items(index, cases)}


def _validate_sha(value: object, name: str) -> None:
    _require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None,
             f'{name} must be a lowercase SHA-256 digest')


def _validate_dataset(dataset: object) -> None:
    _object(dataset, _DATASET_KEYS, 'dataset')
    _version(dataset['schema_version'])
    _require(dataset['content_sha256'] == _binding(dataset, 'content_sha256'),
             'dataset content binding mismatch')
    _validate_typed_index(dataset['index'])
    _validate_cases(dataset['cases'])


def _validated_vectors(payload: object, items: list[dict], dataset_sha: str,
                       input_sha: str) -> tuple[dict, int]:
    _require(isinstance(payload, dict), 'embeddings must be an object')
    _version(payload.get('schema_version'))
    _require(payload.get('complete') is True, 'embeddings must be complete')
    _require(payload.get('dataset_sha256') == dataset_sha, 'embedding dataset hash mismatch')
    _require(payload.get('input_sha256') == input_sha, 'embedding input hash mismatch')
    _validate_sha(payload.get('model_sha256'), 'model_sha256')
    dimensions = payload.get('dimensions')
    _require(type(dimensions) is int and dimensions > 0, 'dimensions must be a positive integer')
    _require(type(payload.get('total_inputs')) is int and payload['total_inputs'] == len(items),
             'embedding total_inputs mismatch')
    vectors = payload.get('vectors')
    _require(isinstance(vectors, dict) and set(vectors) == {item['id'] for item in items},
             'embedding IDs must exactly match all prepared inputs')
    normalized = {}
    for identity, vector in vectors.items():
        _require(isinstance(vector, list) and len(vector) == dimensions,
                 'embedding vector dimensions mismatch')
        try:
            finite = all(type(n) in (float, int) and math.isfinite(n) for n in vector)
        except OverflowError:
            finite = False
        _require(finite, 'embedding values must be finite numbers, not booleans')
        # Scaling first avoids overflow/underflow in squares or a*b. It also
        # preserves cosine when callers provide very large/small finite values.
        scale = max(abs(n) for n in vector)
        _require(scale > 0, 'zero embedding vector is invalid')
        scaled = [n / scale for n in vector]
        norm = math.hypot(*scaled)
        normalized[identity] = [n / norm for n in scaled]
    return normalized, dimensions


def rank_typed(dataset: dict, embedding_payload: dict, expected_dataset_sha256: str,
               expected_input_sha256: str, limit: int = 3) -> dict:
    """Return six global and typed rankings, always filtering before truncation.

    BM25 statistics use the entire supplied corpus. Each query independently
    ranks chunks and collapses to documents; abstract queries receive equal RRF
    votes. Hybrid fusion gives the corresponding lexical/vector groups one vote
    each. All full rankings exist before applying the same per-group ``limit``.
    No relevance score grants permission to use or execute narrative material.
    """
    _require(type(limit) is int and limit >= 0, 'limit must be a nonnegative integer')
    _validate_sha(expected_dataset_sha256, 'expected_dataset_sha256')
    _validate_sha(expected_input_sha256, 'expected_input_sha256')
    _validate_dataset(dataset)
    index, cases = dataset['index'], dataset['cases']
    vectors, dimensions = _validated_vectors(embedding_payload, _embedding_items(index, cases),
                                             expected_dataset_sha256, expected_input_sha256)
    chunks = [chunk for document in index['documents'] for chunk in document['chunks']]
    chunk_map = {chunk['chunk_id']: chunk for chunk in chunks}
    documents = {document['source_path']: document for document in index['documents']}
    chunk_vectors = {chunk['chunk_id']: vectors[_document_id(chunk)] for chunk in chunks}

    def lexical(text: str) -> list[dict]:
        return collapse_documents(bm25_rank(text, chunks), len(documents))

    def vector(text: str) -> list[dict]:
        query = vectors[_query_id(text)]
        hits = [{'source_path': chunk['source_path'], 'chunk_id': chunk['chunk_id'],
                 'score': math.fsum(a * b for a, b in zip(query, chunk_vectors[chunk['chunk_id']]))}
                for chunk in chunks]
        hits.sort(key=lambda hit: (-hit['score'], hit['source_path'], hit['chunk_id']))
        return collapse_documents(hits, len(documents))

    def enrich(hits: list[dict]) -> list[dict]:
        result = []
        for hit in hits:
            document, chunk = documents[hit['source_path']], chunk_map[hit['chunk_id']]
            result.append({key: document[key] for key in ('source_path', 'title', 'kind', 'source_sha256')}
                          | {'score': hit['score'], 'chunk_id': hit['chunk_id'],
                             'start': chunk['start'], 'end': chunk['end'],
                             'matched_excerpt': chunk['text']})
        return result

    results = []
    for case in cases:
        raw = case['snapshot']['text']
        queries = [query['text'] for query in case['analysis']['queries']]
        rankings = {'lexical_raw': lexical(raw),
                    'lexical_abstract': rrf_fuse([lexical(text) for text in queries]),
                    'vector_raw': vector(raw),
                    'vector_abstract': rrf_fuse([vector(text) for text in queries])}
        for mode in ('raw', 'abstract'):
            rankings['hybrid_' + mode] = rrf_fuse([rankings['lexical_' + mode], rankings['vector_' + mode]])
        methods = {}
        for name, ranking in rankings.items():
            methods[name] = {'global': enrich(ranking[:limit]),
                             'by_type': {group: enrich([hit for hit in ranking
                                                      if documents[hit['source_path']]['kind'] in kinds][:limit])
                                         for group, kinds in _TYPES.items()}}
        results.append({'case_id': case['case_id'],
                        'snapshot_sha256': case['snapshot']['snapshot_sha256'], 'methods': methods})
    return {'schema_version': 1, 'corpus_sha256': index['corpus_sha256'],
            'dataset_sha256': expected_dataset_sha256, 'input_sha256': expected_input_sha256,
            'model_sha256': embedding_payload['model_sha256'], 'dimensions': dimensions,
            'limit': limit, 'types': copy.deepcopy(_TYPES), 'cases': results}
