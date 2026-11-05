"""Offline candidate discovery over an explicit, immutable prefix and asset corpus.

Relevance is not permission to execute a narrative move. Exact evidence offsets
establish provenance, not semantic correctness: abstract queries are supplied by
the current external AI (or another caller) and still require human/agent review.
Hashes bind serialized content for reproducibility; they are not signatures or
proof of authorship. This module neither calls a model nor reads story folders.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from narrative_prototype import _asset_path, build_catalog
from retrieval_pilot import bm25_rank, build_chunks, collapse_documents, rrf_fuse

_SNAPSHOT_KEYS = {'schema_version', 'project_id', 'pov_character', 'cutoff_offset',
                  'text', 'source_sha256', 'snapshot_sha256'}
_INDEX_KEYS = {'schema_version', 'documents', 'corpus_sha256'}
_DOCUMENT_KEYS = {'source_path', 'title', 'kind', 'source_sha256', 'text', 'chunks'}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: object, name: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f'{name}: nonempty string required')
    return value


def _object(value: object, keys: set[str], name: str) -> None:
    _require(isinstance(value, dict) and set(value) == keys, f'{name}: unexpected fields or missing fields')


def _version(value: object) -> None:
    _require(type(value) is int and value == 1, 'schema_version must be integer 1')


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _binding(value: dict, omitted: str) -> str:
    try:
        encoded = json.dumps({k: v for k, v in value.items() if k != omitted},
                             ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        return _sha(encoded)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError('content must be UTF-8 JSON serializable') from error


def _source_path(value: object) -> str:
    _text(value, 'source_path')
    relative = PurePosixPath(value)
    _require(not relative.is_absolute() and relative.parts and relative.parts[0] == 'assets'
             and '..' not in relative.parts and '\\' not in value and str(relative) == value
             and relative.suffix == '.md', 'source_path must be a normalized Markdown asset path')
    return value


def freeze_prefix(project_id: str, source_text: str, cutoff_offset: int,
                  pov_character: str) -> dict:
    """Freeze nonblank text before an exclusive Unicode-character offset.

    No suffix, suffix length, or full-source hash is retained. A changed project
    ID changes the binding, but cannot influence lexical retrieval ranking.
    """
    _text(project_id, 'project_id')
    _text(source_text, 'source_text')
    _text(pov_character, 'pov_character')
    _require(type(cutoff_offset) is int and 1 <= cutoff_offset <= len(source_text),
             'cutoff_offset must be an integer within the nonempty source')
    prefix = _text(source_text[:cutoff_offset], 'prefix')
    snapshot = {'schema_version': 1, 'project_id': project_id, 'pov_character': pov_character,
                'cutoff_offset': cutoff_offset, 'text': prefix, 'source_sha256': _sha(prefix)}
    snapshot['snapshot_sha256'] = _binding(snapshot, 'snapshot_sha256')
    return snapshot


def build_index(repo_root: Path, paths: list[str]) -> dict:
    """Read only explicitly selected eligible Markdown assets; never write files.

    The existing catalog supplies title/kind/eligibility. Corpus identity binds
    all embedded source text and structural chunks, sorted by asset path.
    """
    _require(isinstance(paths, list) and bool(paths), 'paths must be a nonempty list')
    for path in paths:
        _source_path(path)
    _require(len(set(paths)) == len(paths), 'paths must be unique')
    _require(isinstance(repo_root, (str, Path)), 'repo_root must be a path')
    root = Path(repo_root)
    catalog = {item['path']: item for item in build_catalog(root)}
    documents = []
    for name in sorted(paths):
        source = _asset_path(root, name)
        _require(source.suffix == '.md' and name in catalog and catalog[name]['eligible'],
                 f'ineligible Markdown asset: {name}')
        try:
            text = source.read_bytes().decode('utf-8')
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(f'cannot read UTF-8 source: {name}') from error
        source_hash = _sha(text)
        _require(source_hash == catalog[name]['sha256'], 'source changed while indexing')
        documents.append({'source_path': name, 'title': catalog[name]['title'],
                          'kind': catalog[name]['kind'], 'source_sha256': source_hash,
                          'text': text, 'chunks': build_chunks(text, name, mode='structure')})
    index = {'schema_version': 1, 'documents': documents}
    index['corpus_sha256'] = _binding(index, 'corpus_sha256')
    return index


def _validate_snapshot(snapshot: dict) -> None:
    _object(snapshot, _SNAPSHOT_KEYS, 'snapshot')
    _version(snapshot['schema_version'])
    for name in ('project_id', 'pov_character', 'text'):
        _text(snapshot[name], name)
    _require(type(snapshot['cutoff_offset']) is int
             and snapshot['cutoff_offset'] == len(snapshot['text']), 'snapshot cutoff mismatch')
    _require(snapshot['source_sha256'] == _sha(snapshot['text']), 'snapshot source hash mismatch')
    _require(snapshot['snapshot_sha256'] == _binding(snapshot, 'snapshot_sha256'),
             'snapshot binding mismatch')


def _validate_index(index: dict) -> None:
    _object(index, _INDEX_KEYS, 'index')
    _version(index['schema_version'])
    documents = index['documents']
    _require(isinstance(documents, list) and bool(documents), 'index documents must be nonempty')
    _require(index['corpus_sha256'] == _binding(index, 'corpus_sha256'), 'corpus binding mismatch')
    paths = []
    for document in documents:
        _object(document, _DOCUMENT_KEYS, 'document')
        name = _source_path(document['source_path'])
        paths.append(name)
        _text(document['title'], 'document title')
        _text(document['kind'], 'document kind')
        _require(isinstance(document['text'], str), 'document text must be a string')
        _require(document['source_sha256'] == _sha(document['text']), 'document source hash mismatch')
        _require(document['chunks'] == build_chunks(document['text'], name, mode='structure'),
                 'document chunks do not match source')
    _require(paths == sorted(set(paths)), 'document paths must be unique and sorted')


def _validate_analysis(analysis: dict, snapshot: dict) -> None:
    _object(analysis, {'schema_version', 'snapshot_sha256', 'queries'}, 'analysis')
    _version(analysis['schema_version'])
    _require(analysis['snapshot_sha256'] == snapshot['snapshot_sha256'], 'analysis binding mismatch')
    queries = analysis['queries']
    _require(isinstance(queries, list) and 1 <= len(queries) <= 4, 'analysis requires 1 to 4 queries')
    prefix = snapshot['text']
    for query in queries:
        _object(query, {'text', 'evidence'}, 'query')
        _text(query['text'], 'query text')
        evidence = query['evidence']
        _require(isinstance(evidence, list) and bool(evidence), 'query evidence must be nonempty')
        for reference in evidence:
            _object(reference, {'start', 'end', 'quote'}, 'evidence')
            start, end = reference['start'], reference['end']
            _require(type(start) is int and type(end) is int and 0 <= start < end <= len(prefix),
                     'evidence offsets outside prefix')
            quote = _text(reference['quote'], 'evidence quote')
            _require(prefix[start:end] == quote, 'evidence quote does not match prefix')


def discover(snapshot: dict, index: dict, analysis: dict | None = None, limit: int = 5) -> dict:
    """Return raw-prefix, abstract-query, and equal-group fused candidate ranks.

    Queries are BM25-ranked separately, then RRF-fused into one abstract group.
    Raw and abstract groups receive equal votes in a second RRF. Full document
    rankings are fused before applying ``limit``. Excerpts are original chunks.
    Inputs are validated without mutation or disk access; relevance and exact
    evidence positions do not establish semantic entailment or executability.
    """
    _require(type(limit) is int and limit >= 0, 'limit must be a nonnegative integer')
    _validate_snapshot(snapshot)
    _validate_index(index)
    if analysis is not None:
        _validate_analysis(analysis, snapshot)
    chunks = [chunk for document in index['documents'] for chunk in document['chunks']]
    chunk_map = {chunk['chunk_id']: chunk for chunk in chunks}
    documents = {document['source_path']: document for document in index['documents']}
    raw = collapse_documents(bm25_rank(snapshot['text'], chunks), len(documents))
    abstract = (rrf_fuse([bm25_rank(query['text'], chunks) for query in analysis['queries']])
                if analysis is not None else [])
    fused = rrf_fuse([raw, abstract]) if analysis is not None else raw

    def enrich(ranking: list[dict]) -> list[dict]:
        result = []
        for hit in collapse_documents(ranking, limit):
            document = documents[hit['source_path']]
            result.append({key: document[key] for key in ('source_path', 'title', 'kind', 'source_sha256')}
                          | {'score': hit['score'], 'matched_excerpt': chunk_map[hit['chunk_id']]['text']})
        return result

    return {'snapshot_sha256': snapshot['snapshot_sha256'], 'corpus_sha256': index['corpus_sha256'],
            'methods': {'raw_prefix': enrich(raw), 'abstract_queries': enrich(abstract), 'fused': enrich(fused)}}
