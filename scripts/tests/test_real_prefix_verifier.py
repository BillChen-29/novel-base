"""Local experiment outputs must not overwrite source novels or escape by ID."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'experiments/continuity-audit/verify_real_prefixes.py'
spec = importlib.util.spec_from_file_location('real_prefix_verifier', SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class RealPrefixOutputTests(unittest.TestCase):
    def test_reports_cannot_overwrite_source_by_path_or_link(self):
        for mode in ('direct', 'symlink', 'hardlink'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); source = root / 'source.txt'; raw = '应当保留的原文。'.encode()
                source.write_bytes(raw)
                selection = root / 'selection.json'
                selection.write_text(json.dumps({'books': [{'book_id':'book', 'source_path':str(source),
                    'source_sha256':hashlib.sha256(raw).hexdigest()}], 'cases':[{'id':'safe-case'}]}))
                summary = source if mode == 'direct' else root / 'summary.json'
                if mode == 'symlink': summary.symlink_to(source)
                if mode == 'hardlink': os.link(source, summary)
                argv = ['verify', '--selection', str(selection), '--output', str(root/'results'), '--summary', str(summary)]
                with patch.object(sys, 'argv', argv), self.assertRaisesRegex(ValueError, 'output_overlaps_source|unsafe_output_link'):
                    verifier.main()
                self.assertEqual(source.read_bytes(), raw)
                self.assertFalse((root/'results').exists())

    def test_linked_run_parent_rejects_before_copying_any_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); outside = root/'outside'; outside.mkdir()
            output = root/'linked-runs'; output.symlink_to(outside, target_is_directory=True)
            case = {'id':'safe-case', 'prefix':'前', 'actual_next':'后',
                    'prefix_start':0, 'prefix_end':1, 'next_start':1, 'next_end':2,
                    'order_review':{'eligible':True}}
            with self.assertRaisesRegex(ValueError, 'unsafe_output_link'):
                verifier.verify_case(case, output, '前后')
            self.assertEqual(list(outside.iterdir()), [])

    def test_case_id_cannot_escape_even_via_direct_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for case_id in ('../escape', str(root/'outside'), 'nested/case', ''):
                with self.subTest(case_id=case_id), self.assertRaisesRegex(ValueError, 'invalid_case_id'):
                    verifier.verify_case({'id':case_id}, root/'results', '只读原文')
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
