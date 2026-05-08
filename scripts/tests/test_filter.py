#!/usr/bin/env python3
"""B1 知识库内容过滤测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import (
    check_conflict,
    evaluate_value,
    classify_content,
    filter_search_results,
)


class TestCheckConflict:
    """check_conflict 测试"""

    def test_no_overlap(self):
        item = {"snippet": "这是一个关于编程的故事", "title": "代码人生"}
        summaries = [{"summary": "战争与和平的叙事", "keywords": "战争 和平 叙事"}]
        score = check_conflict(item, summaries)
        assert score == 0.0

    def test_high_overlap(self):
        item = {"snippet": "战争改变了命运", "title": "战争命运"}
        summaries = [{"summary": "战争改变了人们的命运", "keywords": "战争 命运 改变"}]
        score = check_conflict(item, summaries)
        assert score > 0.4, f"Expected > 0.4, got {score}"

    def test_partial_overlap(self):
        item = {"snippet": "魔法与战斗的故事", "title": "魔法战士"}
        summaries = [{"summary": "战士在魔法世界中的冒险", "keywords": "战士 魔法 冒险"}]
        score = check_conflict(item, summaries)
        # 有交集但不一定会超过 0.4
        assert 0.0 <= score <= 1.0

    def test_empty_summaries_raises(self):
        item = {"snippet": "测试内容"}
        try:
            check_conflict(item, [])
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_empty_keywords(self):
        item = {"snippet": "", "title": ""}
        summaries = [{"summary": "测试摘要", "keywords": "测试"}]
        score = check_conflict(item, summaries)
        assert score == 0.0

    def test_multiple_summaries_uses_max(self):
        item = {"snippet": "魔法世界的战斗", "title": "战斗魔法"}
        summaries = [
            {"summary": "关于烹饪的书", "keywords": "烹饪 美食"},
            {"summary": "魔法世界中的战斗传说", "keywords": "魔法 战斗 传说"},
        ]
        score = check_conflict(item, summaries)
        assert score > 0.0


class TestEvaluateValue:
    """evaluate_value 测试"""

    def test_critical(self):
        item = {"score": 0.9}
        assert evaluate_value(item, 10) == "critical"

    def test_critical_boundary(self):
        item = {"score": 0.8}
        assert evaluate_value(item, 10) == "critical"

    def test_reference(self):
        item = {"score": 0.6}
        assert evaluate_value(item, 10) == "reference"

    def test_reference_boundary(self):
        item = {"score": 0.5}
        assert evaluate_value(item, 10) == "reference"

    def test_low(self):
        item = {"score": 0.3}
        assert evaluate_value(item, 10) == "low"

    def test_zero_score(self):
        item = {"score": 0}
        assert evaluate_value(item, 10) == "low"

    def test_missing_score(self):
        item = {}
        assert evaluate_value(item, 10) == "low"


class TestClassifyContent:
    """classify_content 测试"""

    def test_motif_library(self):
        item = {"collection": "motif-library"}
        assert classify_content(item) == "plot_fuel"

    def test_character_archetypes(self):
        item = {"collection": "character-archetypes"}
        assert classify_content(item) == "character_dim"

    def test_technique_library(self):
        item = {"collection": "technique-library"}
        assert classify_content(item) == "narrative_technique"

    def test_style_library(self):
        item = {"collection": "style-library"}
        assert classify_content(item) == "narrative_technique"

    def test_pacing_template(self):
        item = {"collection": "pacing-template"}
        assert classify_content(item) == "plot_fuel"

    def test_unknown_collection(self):
        item = {"collection": "unknown-collection"}
        assert classify_content(item) == "unknown"

    def test_missing_collection(self):
        item = {}
        assert classify_content(item) == "unknown"


class TestFilterSearchResults:
    """filter_search_results 测试"""

    def test_basic_filtering(self):
        results = {
            "motifs": [
                {
                    "snippet": "编程改变世界",
                    "title": "代码革命",
                    "score": 0.9,
                    "collection": "motif-library",
                },
                {
                    "snippet": "无关内容",
                    "title": "别的东西",
                    "score": 0.3,
                    "collection": "motif-library",
                },
            ],
        }
        filtered = filter_search_results(results, current_chapter=10)
        assert "motifs" in filtered
        assert len(filtered["motifs"]) == 2
        # 每个条目都应有新增字段
        for item in filtered["motifs"]:
            assert "conflict_score" in item
            assert "value" in item
            assert "category" in item

    def test_empty_summaries_skips_conflict(self):
        results = {
            "motifs": [
                {"snippet": "测试内容", "title": "测试", "score": 0.6, "collection": "motif-library"}
            ],
        }
        filtered = filter_search_results(results, current_chapter=5, chapter_summaries=[])
        assert len(filtered["motifs"]) == 1
        assert filtered["motifs"][0]["conflict_score"] == 0.0

    def test_none_summaries_skips_conflict(self):
        results = {
            "techniques": [
                {"snippet": "技巧内容", "title": "技巧", "score": 0.7, "collection": "technique-library"}
            ],
        }
        filtered = filter_search_results(results, current_chapter=5, chapter_summaries=None)
        assert len(filtered["techniques"]) == 1

    def test_high_conflict_removed(self):
        results = {
            "motifs": [
                {
                    "snippet": "战争改变了命运的轨迹",
                    "title": "战争命运轨迹",
                    "score": 0.6,
                    "collection": "motif-library",
                },
            ],
        }
        summaries = [{"summary": "战争改变了命运的轨迹", "keywords": "战争 命运 轨迹 改变"}]
        filtered = filter_search_results(results, current_chapter=10, chapter_summaries=summaries)
        # 高冲突项应被过滤
        assert len(filtered["motifs"]) == 0

    def test_preserves_categories(self):
        results = {
            "motifs": [
                {"snippet": "A", "title": "A", "score": 0.6, "collection": "motif-library"}
            ],
            "archetypes": [
                {"snippet": "B", "title": "B", "score": 0.7, "collection": "character-archetypes"}
            ],
        }
        filtered = filter_search_results(results, current_chapter=10)
        assert len(filtered["motifs"]) == 1
        assert filtered["motifs"][0]["category"] == "plot_fuel"
        assert filtered["archetypes"][0]["category"] == "character_dim"


def run_tests():
    """简单测试运行器"""
    import traceback

    test_classes = [
        TestCheckConflict,
        TestEvaluateValue,
        TestClassifyContent,
        TestFilterSearchResults,
    ]

    passed = 0
    failed = 0
    for cls in test_classes:
        instance = cls()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                method = getattr(instance, method_name)
                try:
                    method()
                    passed += 1
                    print(f"  ✓ {cls.__name__}.{method_name}")
                except Exception as e:
                    failed += 1
                    print(f"  ✗ {cls.__name__}.{method_name}: {e}")
                    traceback.print_exc()

    print(f"\n结果: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
