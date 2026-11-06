"""Filesystem contracts for immutable embedding cache jobs; no model calls."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from recommendation_retrieval import encoded, prepare_embedding_bundle

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('cache_cli', ROOT / 'experiments/recommendation-shared-index/cache_cli.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class CacheCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.bundle = prepare_embedding_bundle(
            {'token': {'project_id': 'local', 'revision': 1, 'source_sha256': 'a' * 64},
             'state_sha256': 'b' * 64, 'catalog_sha256': 'c' * 64},
            '角色持有未读纸条', [{'id': 'read', 'title': '读取载体', 'retrieval_text': '纸条信件读取'}])
        self.source = self.root / 'input'
        self.source.mkdir()
        for key, name in [('dataset', 'dataset.json'), ('embedding_input', 'embedding-input.json')]:
            (self.source / name).write_bytes(encoded(self.bundle[key]))
        self.job = self.root / 'runtime-data/job'

    def prepare(self, **kwargs):
        return cli.prepare_job(self.source, self.job, self.root, **kwargs)

    def encode(self, directory):
        from recommendation_retrieval import MODEL_SHA256
        items = cli.read(directory / 'embedding-input.json')
        payload = {'schema_version': 1, 'complete': True, 'dimensions': 768,
                   'model_sha256': MODEL_SHA256, 'qmd_version': '2.1.0', 'runtime_version': '3.18.1',
                   'prefix': 'qmd-format-functions-v1', 'total_inputs': len(items['items']),
                   'dataset_sha256': items['dataset_sha256'],
                   'input_sha256': cli.digest(items),
                   'vectors': {i['id']: [1.0] + [0.0] * 767 for i in items['items']}}
        (directory / 'embeddings.json').write_bytes(encoded(payload))

    def test_cold_complete_then_warm_job_needs_no_model_result(self):
        result = self.prepare()
        self.assertEqual(result['stats']['total_inputs'], 2)
        self.encode(self.job)
        output = self.root / 'runtime-data/completed'
        done = cli.complete_job(self.job, output, self.root)
        self.assertEqual(done['stats']['new_documents'], 1)
        self.assertEqual(cli.read(output / 'artifact.json')['dataset'], self.bundle['dataset'])
        warm = self.root / 'runtime-data/warm'
        cli.prepare_job(self.source, warm, self.root, output / 'knowledge-index.json', output / 'query-snapshot.json')
        self.assertEqual(cli.read(warm / 'embedding-input.json')['items'], [])
        done2 = self.root / 'runtime-data/warm-completed'
        cli.complete_job(warm, done2, self.root)
        self.assertEqual(cli.read(done2 / 'stats.json')['total_inputs'], 0)

    def test_existing_output_not_overwritten(self):
        self.prepare()
        before = {p.name: p.read_bytes() for p in self.job.iterdir()}
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.job.iterdir()})

    def test_output_outside_runtime_or_runtime_root_rejected(self):
        for path in [self.root / 'wrong', self.root / 'runtime-data']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                cli.prepare_job(self.source, path, self.root)
            self.assertFalse(path.exists())

    def test_symlink_output_ancestor_rejected(self):
        real = self.root / 'real'
        real.mkdir()
        (self.root / 'runtime-data').symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(list(real.iterdir()), [])

    def test_private_job_permissions_even_with_permissive_umask(self):
        previous = os.umask(0)
        try:
            self.prepare()
        finally:
            os.umask(previous)
        self.assertEqual(self.job.stat().st_mode & 0o777, 0o700)
        for p in self.job.iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_swapped_destination_symlink_cannot_redirect_writes(self):
        outside = self.root / 'outside'
        outside.mkdir()
        original = Path.mkdir
        swapped = False
        def swap(path, *args, **kwargs):
            nonlocal swapped
            result = original(path, *args, **kwargs)
            if path == self.job and not swapped:
                swapped = True
                path.rename(path.with_name('detached'))
                path.symlink_to(outside, target_is_directory=True)
            return result
        with patch.object(Path, 'mkdir', swap):
            with self.assertRaises((ValueError, OSError)): self.prepare()
        self.assertTrue(swapped)
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_input_does_not_create_output(self):
        bad = copy.deepcopy(self.bundle['embedding_input'])
        bad['items'][0]['text'] += ' changed'
        (self.source / 'embedding-input.json').write_bytes(encoded(bad))
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.job.exists())

    def test_job_snapshot_or_delta_tamper_rejected_before_publish(self):
        self.prepare()
        self.encode(self.job)
        for name in ['target-bundle.json', 'index-snapshot.json', 'query-snapshot.json', 'dataset.json', 'embedding-input.json']:
            p = self.job / name
            previous = p.read_bytes()
            p.write_text('{}\n')
            with self.subTest(name=name), self.assertRaises(ValueError):
                cli.complete_job(self.job, self.root / 'runtime-data/out', self.root)
            self.assertFalse((self.root / 'runtime-data/out').exists())
            p.write_bytes(previous)

    def test_missing_or_wrong_embeddings_cannot_publish(self):
        self.prepare()
        dest = self.root / 'runtime-data/out'
        with self.assertRaises((ValueError, OSError)): cli.complete_job(self.job, dest, self.root)
        self.encode(self.job)
        p = self.job / 'embeddings.json'
        value = cli.read(p)
        value['model_sha256'] = 'e' * 64
        p.write_bytes(encoded(value))
        with self.assertRaises(ValueError): cli.complete_job(self.job, dest, self.root)
        self.assertFalse(dest.exists())

    def test_strict_json_rejects_duplicates_and_nonfinite(self):
        p = self.root / 'bad.json'
        for text in ['{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}']:
            p.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError): cli.read(p)

    def test_import_validated_legacy_job_and_keep_source_unchanged(self):
        self.encode(self.source)
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        dest = self.root / 'runtime-data/import'
        cli.import_job(self.source, dest, self.root)
        self.assertEqual(len(cli.read(dest / 'knowledge-index.json')['documents']), 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})


if __name__ == '__main__': unittest.main()
