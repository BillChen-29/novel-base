"""Pure document cache and context-bound private query snapshots.

Digests detect accidental modification; they are not signatures or proof of
model execution. Rows retain raw numbers and the hashes of their source job.
All persistence, locking, model execution and permissions belong to callers.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

from recommendation_retrieval import (DIMENSIONS, INPUT_FORMAT, MODEL_SHA256,
    QMD_VERSION, RUNTIME_VERSION, _artifact_vectors, encoded, prepare_embedding_bundle)
from typed_knowledge_discovery import _validated_vectors

_CONTRACT = {'model_sha256': MODEL_SHA256, 'dimensions': DIMENSIONS,
             'input_format': INPUT_FORMAT, 'qmd_version': QMD_VERSION,
             'runtime_version': RUNTIME_VERSION}
_ROW_KEYS = {'item', 'vector', 'item_sha256', 'vector_sha256', 'source_job', 'row_sha256'}
_SOURCE_KEYS = {'dataset_sha256', 'input_sha256', 'embedding_sha256'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _object(value, keys, name):
    _require(isinstance(value, dict) and set(value) == set(keys), 'invalid_' + name)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, OverflowError, UnicodeError) as error:
        raise ValueError('invalid_json_content') from error


def _digest(value):
    return _sha(_canonical(value))


def _without(value, field):
    return {key: val for key, val in value.items() if key != field}


def _clean(value):
    return json.loads(_canonical(value))


def _digest_string(value):
    _require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None, 'invalid_digest')


def _contract(value):
    _require(_canonical(value) == _canonical(_CONTRACT), 'embedding_contract_mismatch')


def _version(value):
    _require(type(value) is int and value == 1, 'invalid_schema_version')


def _context(value):
    _object(value, {'token', 'state_sha256', 'catalog_sha256'}, 'project_context')
    token = value['token']
    _object(token, {'project_id', 'revision', 'source_sha256'}, 'source_token')
    _require(isinstance(token['project_id'], str) and bool(token['project_id'].strip()), 'invalid_project_id')
    _require(type(token['revision']) is int and token['revision'] > 0, 'invalid_project_revision')
    for digest in (token['source_sha256'], value['state_sha256'], value['catalog_sha256']):
        _digest_string(digest)


def _bundle(bundle):
    _object(bundle, {'dataset', 'embedding_input'}, 'embedding_bundle')
    dataset = bundle['dataset']
    _object(dataset, {'schema_version', 'retrieval_version', 'context', 'query', 'cards', 'embedding_contract'}, 'dataset')
    _version(dataset['schema_version'])
    _contract(dataset['embedding_contract'])
    _context(dataset['context'])
    expected = prepare_embedding_bundle(dataset['context'], dataset['query'], dataset['cards'])
    _require(encoded(bundle) == encoded(expected), 'embedding_bundle_mismatch')
    return expected


def empty_index():
    """Create an independent empty pinned-profile document index."""
    return {'schema_version': 1, 'kind': 'recommendation-document-index-v1',
            'embedding_contract': copy.deepcopy(_CONTRACT), 'documents': {}}


def _row(item, vector, source):
    value = {'item': copy.deepcopy(item), 'vector': copy.deepcopy(vector),
             'item_sha256': _digest(item), 'vector_sha256': _digest(vector),
             'source_job': copy.deepcopy(source)}
    value['row_sha256'] = _digest(value)
    return value


def _validate_row(row, kind):
    _object(row, _ROW_KEYS, 'cache_row')
    item = row['item']
    _object(item, {'id', 'kind', 'title', 'text'}, 'cache_item')
    _require(item['kind'] == kind, 'cache_item_kind_mismatch')
    _require(isinstance(item['title'], str) and isinstance(item['text'], str)
             and bool(item['text'].strip()), 'invalid_cache_item_text')
    if kind == 'document':
        _require(bool(item['title'].strip()) and '\0' not in item['title'] and '\0' not in item['text'], 'invalid_cache_document')
        seed = 'document\0' + item['title'] + '\0' + item['text']
    else:
        _require(item['title'] == '', 'invalid_query_title')
        seed = 'query\0' + item['text']
    _require(item['id'] == _sha(seed.encode('utf-8')), 'cache_item_identity_mismatch')
    _object(row['source_job'], _SOURCE_KEYS, 'source_job')
    for value in row['source_job'].values():
        _digest_string(value)
    for field in ('item_sha256', 'vector_sha256', 'row_sha256'):
        _digest_string(row[field])
    _require(row['item_sha256'] == _digest(item), 'cache_item_digest_mismatch')
    _require(row['vector_sha256'] == _digest(row['vector']), 'cache_vector_digest_mismatch')
    _require(row['row_sha256'] == _digest(_without(row, 'row_sha256')), 'cache_row_digest_mismatch')
    # Reuse the retrieval validator while retaining the original vector values.
    _validated_vectors({'schema_version': 1, 'complete': True, 'dimensions': DIMENSIONS,
                        'total_inputs': 1, 'model_sha256': MODEL_SHA256,
                        'dataset_sha256': '0' * 64, 'input_sha256': '0' * 64,
                        'vectors': {item['id']: row['vector']}}, [item], '0' * 64, '0' * 64)


def _index(index):
    if index is None:
        return empty_index()
    _object(index, {'schema_version', 'kind', 'embedding_contract', 'documents'}, 'document_index')
    _version(index['schema_version'])
    _require(index['kind'] == 'recommendation-document-index-v1', 'invalid_index_kind')
    _contract(index['embedding_contract'])
    _require(isinstance(index['documents'], dict), 'invalid_index_documents')
    for identity, row in index['documents'].items():
        _validate_row(row, 'document')
        _require(identity == row['item']['id'], 'index_key_identity_mismatch')
    return _clean(index)


def _scope(bundle):
    dataset = bundle['dataset']
    return {'embedding_contract': copy.deepcopy(_CONTRACT), 'context': copy.deepcopy(dataset['context']),
            'query': dataset['query'], 'catalog_sha256': _digest(dataset['cards'])}


def _snapshot(snapshot):
    if snapshot is None:
        return None
    _object(snapshot, {'schema_version', 'kind', 'embedding_contract', 'context', 'query',
                       'catalog_sha256', 'scope_sha256', 'query_entry', 'snapshot_sha256'}, 'query_snapshot')
    _version(snapshot['schema_version'])
    _require(snapshot['kind'] == 'recommendation-query-snapshot-v1', 'invalid_snapshot_kind')
    _contract(snapshot['embedding_contract'])
    _context(snapshot['context'])
    _require(isinstance(snapshot['query'], str), 'invalid_snapshot_scope')
    for field in ('catalog_sha256', 'scope_sha256', 'snapshot_sha256'):
        _digest_string(snapshot[field])
    scope = {key: snapshot[key] for key in ('embedding_contract', 'context', 'query', 'catalog_sha256')}
    _require(snapshot['scope_sha256'] == _digest(scope), 'query_scope_digest_mismatch')
    _require(snapshot['snapshot_sha256'] == _digest(_without(snapshot, 'snapshot_sha256')), 'query_snapshot_digest_mismatch')
    if snapshot['query'].strip():
        _validate_row(snapshot['query_entry'], 'query')
        _require(snapshot['query_entry']['item']['text'] == snapshot['query'], 'query_snapshot_text_mismatch')
    else:
        _require(snapshot['query_entry'] is None, 'empty_query_phantom')
    return _clean(snapshot)


def _prepare(bundle, index, query_snapshot):
    bundle, index, snapshot = _bundle(bundle), _index(index), _snapshot(query_snapshot)
    query_row = (snapshot['query_entry'] if snapshot is not None and snapshot['scope_sha256'] == _digest(_scope(bundle)) else None)
    items = bundle['embedding_input']['items']
    missing = []
    docs = queries = reused_docs = reused_queries = 0
    for item in items:
        if item['kind'] == 'document':
            docs += 1
            row = index['documents'].get(item['id'])
            if row is not None:
                _require(_canonical(row['item']) == _canonical(item), 'document_content_conflict')
                reused_docs += 1
            else:
                missing.append(item)
        else:
            queries += 1
            if query_row is None:
                missing.append(item)
            else:
                _require(_canonical(query_row['item']) == _canonical(item), 'query_content_conflict')
                reused_queries += 1
    missing = sorted(missing, key=lambda item: (item['kind'], item['id']))
    # A delta job binds the full private target via a canonical digest. It is
    # consumable by retrieval_pilot_embed.mjs and never enters the shared index.
    dataset = {'schema_version': 1, 'retrieval_version': 'recommendation-embedding-delta-v1',
               'target_sha256': _digest(bundle['dataset']), 'embedding_contract': copy.deepcopy(_CONTRACT),
               'items': copy.deepcopy(missing)}
    inputs = {'schema_version': 1, 'dataset_sha256': _sha(encoded(dataset)), 'items': copy.deepcopy(missing)}
    stats = {'document_count': docs, 'query_count': queries, 'reused_documents': reused_docs,
             'reused_queries': reused_queries, 'new_documents': docs - reused_docs,
             'new_queries': queries - reused_queries, 'total_inputs': len(missing)}
    return bundle, index, query_row, {'dataset': dataset, 'embedding_input': inputs, 'stats': stats}


def plan_embeddings(bundle, index=None, query_snapshot=None):
    """Validate all inputs and prepare exactly the missing private encoder job.

    Zero-item plans are valid; callers must skip the encoder for those plans.
    Scope mismatches are query misses, while malformed snapshots always fail.
    """
    return _prepare(bundle, index, query_snapshot)[3]


def _source(artifact):
    return {'dataset_sha256': _sha(encoded(artifact['dataset'])),
            'input_sha256': _sha(encoded(artifact['embedding_input'])),
            'embedding_sha256': _sha(encoded(artifact['embeddings']))}


def _assemble(bundle, index, query_row, stats):
    scope = _scope(bundle)
    snapshot = {'schema_version': 1, 'kind': 'recommendation-query-snapshot-v1', **scope,
                'scope_sha256': _digest(scope), 'query_entry': copy.deepcopy(query_row)}
    snapshot['snapshot_sha256'] = _digest(snapshot)
    vectors, sources = {}, {}
    for item in bundle['embedding_input']['items']:
        row = index['documents'][item['id']] if item['kind'] == 'document' else query_row
        _require(row is not None, 'missing_assembled_query')
        vectors[item['id']] = copy.deepcopy(row['vector'])
        sources[_digest(row['source_job'])] = copy.deepcopy(row['source_job'])
    payload = {'schema_version': 1, 'complete': True, 'dimensions': DIMENSIONS,
               'model_sha256': MODEL_SHA256, 'prefix': INPUT_FORMAT,
               'qmd_version': QMD_VERSION, 'runtime_version': RUNTIME_VERSION,
               'dataset_sha256': _sha(encoded(bundle['dataset'])),
               'input_sha256': _sha(encoded(bundle['embedding_input'])),
               'total_inputs': len(vectors), 'vectors': dict(sorted(vectors.items())),
               'assembly': 'recommendation-cache-assembly-v1',
               'source_jobs': [sources[key] for key in sorted(sources)]}
    artifact = {**copy.deepcopy(bundle), 'embeddings': payload}
    _artifact_vectors(bundle, artifact)
    return {'index': _clean(index), 'query_snapshot': _clean(snapshot), 'artifact': artifact, 'stats': copy.deepcopy(stats)}


def complete_embeddings(bundle, index=None, query_snapshot=None, encoded_delta=None):
    """Validate an exact completed delta and assemble an old-compatible artifact."""
    bundle, index, query_row, plan = _prepare(bundle, index, query_snapshot)
    delta_bundle = {key: plan[key] for key in ('dataset', 'embedding_input')}
    if plan['stats']['total_inputs']:
        _require(encoded_delta is not None, 'encoded_delta_required')
        _artifact_vectors(delta_bundle, encoded_delta)
        source = _source(encoded_delta)
        for item in plan['embedding_input']['items']:
            row = _row(item, encoded_delta['embeddings']['vectors'][item['id']], source)
            if item['kind'] == 'document':
                _require(item['id'] not in index['documents'], 'document_overwrite_conflict')
                index['documents'][item['id']] = row
            else:
                query_row = row
    else:
        _require(encoded_delta is None, 'unexpected_encoded_delta')
    return _assemble(bundle, index, query_row, plan['stats'])


def import_artifact(bundle, artifact, index=None):
    """Import an exact legacy artifact; a divergent existing raw vector conflicts."""
    bundle, index, _, plan = _prepare(bundle, index, None)
    _artifact_vectors(bundle, artifact)
    source, query_row = _source(artifact), None
    imported_docs = 0
    for item in bundle['embedding_input']['items']:
        vector = artifact['embeddings']['vectors'][item['id']]
        row = _row(item, vector, source)
        if item['kind'] == 'query':
            query_row = row
        else:
            existing = index['documents'].get(item['id'])
            if existing is not None:
                _require(_canonical(existing['item']) == _canonical(item)
                         and _canonical(existing['vector']) == _canonical(vector), 'document_import_conflict')
            else:
                index['documents'][item['id']] = row
                imported_docs += 1
    stats = {**plan['stats'], 'new_documents': 0, 'new_queries': 0, 'total_inputs': 0,
             'imported_documents': imported_docs, 'imported_queries': int(query_row is not None)}
    return _assemble(bundle, index, query_row, stats)
