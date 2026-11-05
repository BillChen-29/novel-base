"""Regression tests for multi-condition evidence accounting, without model calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from retrieval_pilot import score_evidence


class EvidenceContracts(unittest.TestCase):
    def test_one_of_two_conditions_in_same_document_is_half_coverage(self):
        evidence = [{'path': 'a.md', 'quote': '需要代价'}, {'path': 'a.md', 'quote': '不能轻松完成'}]
        actual = score_evidence([{'source_path': 'a.md', 'excerpt': '必须需要代价。'}], evidence)
        self.assertEqual(actual, {'evidence_recall_at_k': 0.5, 'complete_evidence_at_k': 0.0})

    def test_duplicate_quotes_do_not_inflate_and_wrong_source_does_not_match(self):
        evidence = [{'path': 'a.md', 'quote': '需要代价'}] * 2 + [{'path': 'b.md', 'quote': '需要代价'}]
        actual = score_evidence([{'source_path': 'a.md', 'excerpt': '需要代价'}], evidence)
        self.assertEqual(actual['evidence_recall_at_k'], 0.5)

    def test_quotes_can_be_covered_across_returned_chunks(self):
        evidence = [{'path': 'a.md', 'quote': '需要代价'}, {'path': 'a.md', 'quote': '不能轻松完成'}]
        actual = score_evidence([{'source_path': 'a.md', 'excerpt': q['quote']} for q in evidence], evidence)
        self.assertEqual(actual, {'evidence_recall_at_k': 1.0, 'complete_evidence_at_k': 1.0})

    def test_empty_hits_are_zero_but_unanswerable_questions_are_unscored(self):
        self.assertEqual(score_evidence([], [{'path': 'a.md', 'quote': '条件'}]),
                         {'evidence_recall_at_k': 0.0, 'complete_evidence_at_k': 0.0})
        self.assertEqual(score_evidence([{'source_path': 'a.md', 'excerpt': '相似内容'}], []),
                         {'evidence_recall_at_k': None, 'complete_evidence_at_k': None})


if __name__ == '__main__':
    unittest.main()
