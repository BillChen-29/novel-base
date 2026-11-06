#!/usr/bin/env python3
"""Prepare private encoding deltas and publish new immutable cache snapshots.

This CLI never invokes a model, mutates an existing index, or writes outside a
fresh runtime-data directory. The host selects which completed snapshot to use.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))
from recommendation_retrieval import encoded
from recommendation_embedding_cache import (
    empty_index, plan_embeddings, complete_embeddings, import_artifact,
)

JOB_FILES = ('target-bundle.json', 'index-snapshot.json', 'query-snapshot.json',
             'dataset.json', 'embedding-input.json', 'stats.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key:' + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('nonfinite_json:' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs, parse_constant=invalid)


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def bundle_at(directory, embeddings=False):
    directory = Path(directory)
    result = {'dataset': read(directory / 'dataset.json'),
              'embedding_input': read(directory / 'embedding-input.json')}
    if embeddings:
        result['embeddings'] = read(directory / 'embeddings.json')
    return result


def publish(files, output, repo_root, kind):
    """All content validated/serialized before exclusively claiming destination.

    Manifest is written last; incomplete directories cannot be consumed as jobs.
    A failed write is retained for diagnosis and never overwrites another run.
    """
    data = {name: encoded(value) for name, value in files.items()}
    manifest = {'schema_version': 1, 'kind': kind,
                'file_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in data.items()}}
    data['manifest.json'] = encoded(manifest)
    target = Path(output).expanduser().absolute()
    runtime = Path(repo_root).expanduser().absolute() / 'runtime-data'
    for path in (target, runtime):
        require(not any(p.is_symlink() for p in (path, *path.parents)), 'output_symlink')
    target, runtime = target.resolve(), runtime.resolve()
    require(target != runtime and target.is_relative_to(runtime), 'output_outside_runtime')
    require(not target.exists(), 'output_already_exists')
    try:
        target.mkdir(parents=True, exist_ok=False, mode=0o700)
    except FileExistsError as error:
        raise ValueError('output_already_exists') from error
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name, value in data.items():
            handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=descriptor)
            with os.fdopen(handle, 'wb') as stream:
                stream.write(value)
        current, opened = target.lstat(), os.fstat(descriptor)
        require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino), 'output_directory_changed')
    finally:
        os.close(descriptor)
    return {'output_dir': str(target), 'stats': files['stats.json']}


def prepare_job(bundle_dir, output, repo_root=REPO, index_path=None, query_path=None):
    bundle = bundle_at(bundle_dir)
    index = empty_index() if index_path is None else read(index_path)
    query = None if query_path is None else read(query_path)
    plan = plan_embeddings(bundle, index, query)
    files = {'target-bundle.json': bundle, 'index-snapshot.json': index, 'query-snapshot.json': query,
             'dataset.json': plan['dataset'], 'embedding-input.json': plan['embedding_input'],
             'stats.json': plan['stats']}
    return publish(files, output, repo_root, 'recommendation-embedding-job-v1')


def load_job(directory):
    directory = Path(directory)
    manifest = read(directory / 'manifest.json')
    require(isinstance(manifest, dict) and set(manifest) == {'schema_version', 'kind', 'file_sha256'},
            'invalid_job_manifest')
    require(type(manifest['schema_version']) is int and manifest['schema_version'] == 1
            and manifest['kind'] == 'recommendation-embedding-job-v1', 'invalid_job_manifest')
    require(isinstance(manifest['file_sha256'], dict) and set(manifest['file_sha256']) == set(JOB_FILES),
            'invalid_job_files')
    files = {name: read(directory / name) for name in JOB_FILES}
    require({name: digest(value) for name, value in files.items()} == manifest['file_sha256'],
            'job_snapshot_changed')
    plan = plan_embeddings(files['target-bundle.json'], files['index-snapshot.json'], files['query-snapshot.json'])
    for key, name in [('dataset', 'dataset.json'), ('embedding_input', 'embedding-input.json'), ('stats', 'stats.json')]:
        require(encoded(plan[key]) == encoded(files[name]), 'job_plan_changed')
    return files, plan


def save_result(result, output, repo_root):
    return publish({'knowledge-index.json': result['index'], 'query-snapshot.json': result['query_snapshot'],
                    'artifact.json': result['artifact'], 'stats.json': result['stats']},
                   output, repo_root, 'recommendation-embedding-completed-v1')


def complete_job(job_dir, output, repo_root=REPO):
    files, plan = load_job(job_dir)
    artifact = None
    if plan['embedding_input']['items']:
        artifact = bundle_at(job_dir, embeddings=True)
    else:
        require(not (Path(job_dir) / 'embeddings.json').exists(), 'unexpected_encoding_for_warm_job')
    result = complete_embeddings(files['target-bundle.json'], files['index-snapshot.json'],
                                 files['query-snapshot.json'], artifact)
    return save_result(result, output, repo_root)


def import_job(bundle_dir, output, repo_root=REPO, index_path=None):
    artifact = bundle_at(bundle_dir, embeddings=True)
    bundle = {key: artifact[key] for key in ('dataset', 'embedding_input')}
    result = import_artifact(bundle, artifact, None if index_path is None else read(index_path))
    return save_result(result, output, repo_root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'complete', 'import'):
        command = commands.add_parser(name)
        command.add_argument('--repo-root', type=Path, default=REPO)
        command.add_argument('--output-dir', type=Path, required=True)
        if name == 'complete':
            command.add_argument('--job-dir', type=Path, required=True)
        else:
            command.add_argument('--bundle-dir', type=Path, required=True)
            command.add_argument('--index', type=Path)
            if name == 'plan':
                command.add_argument('--query-snapshot', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'complete':
            result = complete_job(args.job_dir, args.output_dir, args.repo_root)
        elif args.command == 'plan':
            result = prepare_job(args.bundle_dir, args.output_dir, args.repo_root, args.index, args.query_snapshot)
        else:
            result = import_job(args.bundle_dir, args.output_dir, args.repo_root, args.index)
        print(encoded(result).decode('utf-8'), end='')
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
