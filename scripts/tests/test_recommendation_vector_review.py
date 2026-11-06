"""Focused regressions from review; no model-quality claims."""
import unittest
from unittest.mock import patch

from recommendation_retrieval import (
    DIMENSIONS, INPUT_FORMAT, MODEL_SHA256, QMD_VERSION, RUNTIME_VERSION,
    prepare_embedding_bundle, rank_cards,
)
from retrieval_pilot import bm25_rank


class RetrievalReviewTests(unittest.TestCase):
    def test_nul_delimited_document_fields_cannot_alias_and_overwrite(self):
        cards = [
            {'id': 'a', 'title': 'A\0B', 'retrieval_text': 'C'},
            {'id': 'b', 'title': 'A', 'retrieval_text': 'B\0C'},
        ]
        # Both have the same legacy delimiter-based content hash. Reject the
        # input before the later card silently replaces the earlier document.
        with self.assertRaisesRegex(ValueError, 'nul'):
            prepare_embedding_bundle({}, 'query', cards)

    def test_distinct_document_fields_keep_distinct_embedding_items(self):
        cards = [
            {'id': 'a', 'title': 'AB', 'retrieval_text': 'C'},
            {'id': 'b', 'title': 'A', 'retrieval_text': 'BC'},
            {'id': 'c', 'title': 'AB', 'retrieval_text': 'C'},
        ]
        bundle = prepare_embedding_bundle({}, 'query', cards)
        documents = [item for item in bundle['embedding_input']['items']
                     if item['kind'] == 'document']
        self.assertEqual(len(documents), 2)
        self.assertEqual({(item['title'], item['text']) for item in documents},
                         {('AB', 'C'), ('A', 'BC')})
        self.assertEqual(len(bundle['dataset']['cards']), 3)

    def test_wrong_profile_dimensions_fail_before_vector_normalization(self):
        cards = [{'id': 'a', 'title': 'A', 'retrieval_text': 'alpha'}]
        bundle = prepare_embedding_bundle({}, 'alpha', cards)
        for dimensions in (True, DIMENSIONS - 1, DIMENSIONS + 1, float(DIMENSIONS)):
            payload = {'model_sha256': MODEL_SHA256, 'prefix': INPUT_FORMAT,
                       'qmd_version': QMD_VERSION, 'runtime_version': RUNTIME_VERSION,
                       'dimensions': dimensions}
            with self.subTest(dimensions=dimensions), patch(
                    'recommendation_retrieval._validated_vectors') as normalize:
                with self.assertRaisesRegex(ValueError, 'dimensions'):
                    rank_cards({}, 'alpha', cards, method='vector',
                               embedding_artifact={**bundle, 'embeddings': payload})
                normalize.assert_not_called()

    def test_default_bm25_keeps_legacy_acceptance_of_nul_text(self):
        cards = [
            {'id': 'a', 'title': 'A\0B', 'retrieval_text': 'alpha'},
            {'id': 'b', 'title': 'A', 'retrieval_text': 'B\0alpha'},
        ]
        query = 'alpha\0B'
        chunks = [{'source_path': card['id'], 'chunk_id': card['id'],
                   'title': card['title'], 'text': card['retrieval_text']}
                  for card in cards]
        self.assertEqual(rank_cards({}, query, cards)['ranking'],
                         bm25_rank(query, chunks)[:2])


if __name__ == '__main__':
    unittest.main()
