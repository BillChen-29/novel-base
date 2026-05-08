#!/usr/bin/env python3
"""B2 章节距离规则测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import apply_distance_rules


class TestApplyDistanceRules:
    """apply_distance_rules 测试"""

    def test_distance_zero(self):
        """距离为0（同章节）→ skip"""
        results = {"motifs": [{"chapter_number": 10, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert len(items) == 1
        assert items[0]["weight"] == 0.1
        assert items[0]["distance_note"] == "skip"

    def test_distance_one(self):
        """距离1 → skip"""
        results = {"motifs": [{"chapter_number": 11, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 0.1
        assert items[0]["distance_note"] == "skip"

    def test_distance_two(self):
        """距离2 → skip"""
        results = {"motifs": [{"chapter_number": 12, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 0.1
        assert items[0]["distance_note"] == "skip"

    def test_distance_three(self):
        """距离3 → rewrite_40"""
        results = {"motifs": [{"chapter_number": 13, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 0.5
        assert items[0]["distance_note"] == "rewrite_40"

    def test_distance_five(self):
        """距离5 → rewrite_40"""
        results = {"motifs": [{"chapter_number": 15, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 0.5
        assert items[0]["distance_note"] == "rewrite_40"

    def test_distance_six(self):
        """距离6 → ok"""
        results = {"motifs": [{"chapter_number": 16, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 1.0
        assert items[0]["distance_note"] == "ok"

    def test_distance_large(self):
        """距离很大 → ok"""
        results = {"motifs": [{"chapter_number": 1, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=100)
        assert items[0]["weight"] == 1.0
        assert items[0]["distance_note"] == "ok"

    def test_backward_distance(self):
        """反向距离（chapter_number < current_chapter）"""
        results = {"motifs": [{"chapter_number": 8, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        # distance = |10 - 8| = 2 → skip
        assert items[0]["weight"] == 0.1
        assert items[0]["distance_note"] == "skip"

    def test_missing_chapter_number(self):
        """chapter_number 缺失 → 默认 weight=1.0"""
        results = {"motifs": [{"title": "no chapter number"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 1.0
        assert items[0]["distance_note"] == "ok"

    def test_none_chapter_number(self):
        """chapter_number 为 None → 默认 weight=1.0"""
        results = {"motifs": [{"chapter_number": None, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 1.0
        assert items[0]["distance_note"] == "ok"

    def test_multiple_categories_flattened(self):
        """多个分类的结果被平铺"""
        results = {
            "motifs": [
                {"chapter_number": 10, "title": "m1"},
                {"chapter_number": 20, "title": "m2"},
            ],
            "techniques": [
                {"chapter_number": 5, "title": "t1"},
            ],
        }
        items = apply_distance_rules(results, current_chapter=10)
        assert len(items) == 3

    def test_empty_results(self):
        """空结果字典"""
        results = {"motifs": [], "techniques": []}
        items = apply_distance_rules(results, current_chapter=10)
        assert len(items) == 0

    def test_boundary_distance_2(self):
        """边界测试：距离恰好为2"""
        results = {"motifs": [{"chapter_number": 8, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 0.1
        assert items[0]["distance_note"] == "skip"

    def test_boundary_distance_5(self):
        """边界测试：距离恰好为5"""
        results = {"motifs": [{"chapter_number": 15, "title": "test"}]}
        items = apply_distance_rules(results, current_chapter=10)
        assert items[0]["weight"] == 0.5
        assert items[0]["distance_note"] == "rewrite_40"


def run_tests():
    """简单测试运行器"""
    import traceback

    test_class = TestApplyDistanceRules
    instance = test_class()

    passed = 0
    failed = 0
    for method_name in sorted(dir(instance)):
        if method_name.startswith("test_"):
            method = getattr(instance, method_name)
            try:
                method()
                passed += 1
                print(f"  ✓ {method_name}")
            except Exception as e:
                failed += 1
                print(f"  ✗ {method_name}: {e}")
                traceback.print_exc()

    print(f"\n结果: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
