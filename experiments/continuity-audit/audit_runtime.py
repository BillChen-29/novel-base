"""Executable capability audit; unmet continuity requirements remain FAIL.

All projects live in TemporaryDirectory. No API calls, real novels, or existing
indexes are used. Run this module directly with --report-dir to retain evidence.
This is an audit of desired boundaries, not a promise that current code passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import narrative_prototype as prototype
import novel_flow_executor as flow
import plot_rag_retriever as rag
import story_graph_builder as graph

USE_CURRENT_CONTRACT = False


def make_project(root: Path, chapters: dict[int, str]) -> Path:
    (root / "03_manuscript").mkdir(parents=True)
    (root / "00_memory").mkdir()
    (root / "00_memory/character_tracker.md").write_text(
        "| 人物 | 状态 |\n| --- | --- |\n| 阿青 | 在场 |\n| 阿白 | 在场 |\n", encoding="utf-8"
    )
    for number, text in chapters.items():
        (root / f"03_manuscript/第{number}章 audit.md").write_text(text, encoding="utf-8")
    return root


def retrieve(root: Path, query: str, index: dict | None = None, **kwargs) -> dict:
    return rag.retrieve(index or rag.build_index(root), root, query, top_k=5,
                        candidate_k=10, per_chapter=2, passage_max_chars=500, **kwargs)


def run_cli(script: str, *args: str) -> dict:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, str(SCRIPT_DIR / script), *args],
                          capture_output=True, text=True, env=env, timeout=30)
    if proc.returncode:
        raise RuntimeError(f"{script} failed: {proc.stderr[:1000]}")
    return json.loads(proc.stdout)


def query_cli(root: Path, auto_build: bool = False) -> dict:
    args = ["query", "--project-root", str(root), "--query", "阿青保管的密码是什么", "--force"]
    if auto_build:
        args.append("--auto-build")
    return run_cli("plot_rag_retriever.py", *args)


def write_graph(root: Path, nodes: list, edges: list | None = None) -> None:
    (root / "00_memory/story_graph.json").write_text(
        json.dumps({"version": "1.0", "nodes": nodes, "edges": edges or [], "timeline": []},
                   ensure_ascii=False), encoding="utf-8")


def graph_context(root: Path, chapter: int = 1, pov_character=None) -> dict:
    return graph.cmd_context(argparse.Namespace(project_root=str(root), chapter=chapter,
                             cutoff_chapter=chapter if USE_CURRENT_CONTRACT else None,
                             cutoff_offset=None, pov_character=pov_character,
                             max_foreshadows=10, max_events=10), graph.GraphConfig())


def story() -> dict:
    return {"schema_version": 1, "project_id": "audit-fiction", "title": "临时边界样本",
            "pov_character": "阿青", "characters": ["阿青", "阿白"],
            "goal": {"id": "raise_pressure", "description": "提高压力，保留人物已有状态。"},
            "scenes": [{"id": "s1", "order": 1, "text": "阿青的左手受伤了。阿白独自读信，得知暗号为夜航。阿青没有看到信。",
                        "function": "action", "tension": 4, "present_characters": ["阿青", "阿白"]}],
            "facts": [{"id": "f1", "text": "阿青左手受伤", "scene_id": "s1", "quote": "阿青的左手受伤了。", "known_by": ["阿青", "阿白"]},
                      {"id": "f2", "text": "暗号为夜航", "scene_id": "s1", "quote": "得知暗号为夜航。", "known_by": ["阿白"]}],
            "threads": []}


class ContinuityRuntimeAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-continuity-audit-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.observations = {}

    def observe(self, **values):
        self.observations.update(values)

    def test_01_same_named_characters_are_isolated_when_project_indexes_match(self):
        """正常调用时两个项目的同名角色和正文独立。"""
        a = make_project(self.base / "a", {1: "阿青保管的密码是青鸟。"})
        b = make_project(self.base / "b", {1: "阿青保管的密码是白鲸。"})
        ra, rb = retrieve(a, "阿青密码"), retrieve(b, "阿青密码")
        sa, sb = json.dumps(ra, ensure_ascii=False), json.dumps(rb, ensure_ascii=False)
        self.observe(project_a_passages=ra["retrieved"][0]["passages"], project_b_passages=rb["retrieved"][0]["passages"])
        self.assertIn("青鸟", sa)
        self.assertNotIn("白鲸", sa)
        self.assertIn("白鲸", sb)
        self.assertNotIn("青鸟", sb)

    def test_02_foreign_index_is_rejected_for_another_project(self):
        """错误传入另一项目索引时应拒绝，不读取外部小说路径。"""
        a = make_project(self.base / "a", {1: "阿青保管的密码是青鸟。"})
        b = make_project(self.base / "b", {1: "阿青保管的密码是白鲸。"})
        ia = rag.build_index(a)
        try:
            result = retrieve(b, "阿青密码", ia)
        except ValueError:
            return
        self.observe(requested_project="b", indexed_project="a", retrieved=result["retrieved"])
        self.assertNotIn("青鸟", json.dumps(result, ensure_ascii=False), "索引项目与请求项目不匹配仍读取 A 的正文")

    def test_03_retrieval_can_enforce_a_past_continuation_cutoff(self):
        """续写第 2 章时，历史上下文不应包含第 3 章才揭晓的答案。"""
        root = make_project(self.base / "p", {1: "阿青尚不知道密码，只在门前等候。", 3: "阿青读到最终密码：未来蓝鲸。"})
        result = retrieve(root, "阿青密码", **({'cutoff_chapter': 1} if USE_CURRENT_CONTRACT else {}))
        self.observe(requested_cutoff=1, cutoff_parameter_available=USE_CURRENT_CONTRACT,
                     retrieved_files=[d["chapter_file"] for d in result["retrieved"]],
                     retrieved=result["retrieved"])
        self.assertNotIn("未来蓝鲸", json.dumps(result, ensure_ascii=False), "当前 API 无法传入截点；全目录索引返回未来正文")
        self.assertIn("只在门前等候", json.dumps(result, ensure_ascii=False))

    def test_04_auto_build_refreshes_modified_text(self):
        """常规修改后显式 auto-build 应更新缓存和正文。"""
        root = make_project(self.base / "p", {1: "阿青保管的密码是旧青鸟。"})
        first = query_cli(root, auto_build=True)
        path = root / "03_manuscript/第1章 audit.md"
        old = path.stat().st_mtime
        path.write_text("阿青保管的密码是新白鲸。", encoding="utf-8")
        os.utime(path, (old + 2, old + 2))
        result = query_cli(root, auto_build=True)
        self.observe(first_cache_hit=first["cache_hit"], second_cache_hit=result["cache_hit"], result=result["result"])
        self.assertIn("新白鲸", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("旧青鸟", json.dumps(result, ensure_ascii=False))

    def test_05_auto_build_removes_deleted_chapters(self):
        """删除章节并重建后，正文和元数据都应消失。"""
        root = make_project(self.base / "p", {1: "阿青保管的密码是删除青鸟。"})
        query_cli(root, auto_build=True)
        (root / "03_manuscript/第1章 audit.md").unlink()
        result = query_cli(root, auto_build=True)
        metas = list((root / "00_memory/retrieval/chapter_meta").glob("*.json"))
        self.observe(retrieved=result["result"]["retrieved"], remaining_meta_count=len(metas))
        self.assertEqual(result["result"]["retrieved"], [])
        self.assertEqual(metas, [])

    def test_06_default_query_does_not_serve_modified_cached_text(self):
        """默认 query 复查内容变化，不能继续返回已改写原文。"""
        root = make_project(self.base / "p", {1: "阿青保管的密码是旧青鸟。"})
        query_cli(root)
        (root / "03_manuscript/第1章 audit.md").write_text("阿青保管的密码是新白鲸。", encoding="utf-8")
        result = query_cli(root)
        self.observe(cache_hit=result["cache_hit"], retrieved=result["result"]["retrieved"])
        self.assertNotIn("旧青鸟", json.dumps(result, ensure_ascii=False), "未传 auto-build 时缓存未检查源文件变更")

    def test_07_default_query_does_not_serve_deleted_cached_text(self):
        """默认 query 不能继续返回已删除章节的缓存引文。"""
        root = make_project(self.base / "p", {1: "阿青保管的密码是删除青鸟。"})
        query_cli(root)
        (root / "03_manuscript/第1章 audit.md").unlink()
        result = query_cli(root)
        self.observe(cache_hit=result["cache_hit"], retrieved=result["result"]["retrieved"])
        self.assertEqual(result["result"]["retrieved"], [], "删除源文件后缓存仍被返回")

    def test_08_auto_build_detects_content_change_with_preserved_mtime(self):
        """保留修改时间的替换也应触发内容校验。"""
        root = make_project(self.base / "p", {1: "阿青保管的密码是旧青鸟。"})
        query_cli(root, auto_build=True)
        path = root / "03_manuscript/第1章 audit.md"
        stat = path.stat()
        path.write_text("阿青保管的密码是新白鲸。", encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        result = query_cli(root, auto_build=True)
        self.observe(cache_hit=result["cache_hit"], retrieved=result["result"]["retrieved"])
        self.assertNotIn("旧青鸟", json.dumps(result, ensure_ascii=False), "增量索引只比较 mtime，保留 mtime 后旧结果继续命中")

    def test_09_graph_events_obey_chapter_cutoff(self):
        """图谱事件已实现章节号过滤。"""
        root = make_project(self.base / "p", {})
        write_graph(root, [{"id": "e1", "type": "event", "chapter": 1, "description": "此前发现钥匙"},
                           {"id": "e3", "type": "event", "chapter": 3, "description": "未来打开宝库"}])
        result = graph_context(root, 1)
        self.observe(**result)
        self.assertIn("此前发现钥匙", result["context_prompt"])
        self.assertNotIn("未来打开宝库", result["context_prompt"])

    def test_10_graph_foreshadows_obey_chapter_cutoff(self):
        """未来才埋下的伏笔不能进入截点上下文。"""
        root = make_project(self.base / "p", {})
        write_graph(root, [{"id": "f3", "type": "foreshadow", "planted_chapter": 3,
                            "description": "未来收到的密信", "resolved": False}])
        result = graph_context(root, 1)
        self.observe(**result)
        self.assertNotIn("未来收到的密信", result["context_prompt"])

    def test_11_graph_latest_character_state_does_not_leak_backwards(self):
        """回到旧截点时不能使用后续章节更新的人物地点。"""
        root = make_project(self.base / "p", {})
        write_graph(root, [{"id": "qing", "type": "character", "name": "阿青", "location": "未来王城",
                            "status": "正常", "last_updated": 3}])
        result = graph_context(root, 1)
        self.observe(**result)
        self.assertNotIn("未来王城", result["context_prompt"])

    def test_12_graph_context_supports_pov_knowledge_filtering(self):
        """图谱上下文需区分视角人物未知的秘密。"""
        root = make_project(self.base / "p", {})
        write_graph(root, [{"id": "e1", "type": "event", "chapter": 1,
                            "description": "阿白独知暗号为夜航", "known_by": ["阿白"],
                            "source_refs": [{"chapter": 1, "quote": "阿白独自读信。"}]}])
        result = graph_context(root, 1, pov_character="阿青" if USE_CURRENT_CONTRACT else None)
        self.observe(requested_pov="阿青", pov_parameter_available=USE_CURRENT_CONTRACT, **result)
        self.assertNotIn("暗号为夜航", result["context_prompt"], "generate-context 无视角参数，known_by 属性未用于过滤")

    def test_13_graph_context_preserves_relations_and_evidence(self):
        """关系边及事件证据应进入给写作器的上下文。"""
        root = make_project(self.base / "p", {})
        write_graph(root, [{"id": "qing", "type": "character", "name": "阿青", "location": "城门", "status": "正常",
                            **({'last_updated': 1} if USE_CURRENT_CONTRACT else {})},
                           {"id": "bai", "type": "character", "name": "阿白", "location": "城门", "status": "正常",
                            **({'last_updated': 1} if USE_CURRENT_CONTRACT else {})},
                           {"id": "e1", "type": "event", "chapter": 1, "description": "两人重逢",
                            "source_refs": [{"chapter": 1, "quote": "阿青说，你仍是我的师父。"}]}],
                    [{"id": "rel", "type": "mentor", "source": "bai", "target": "qing", "since_chapter": 1}])
        result = graph_context(root, 1)
        self.observe(**result)
        self.assertIn("师父", result["context_prompt"], "当前上下文只投影角色地点/状态、伏笔、事件；未读取关系边或证据")

    def test_14_graph_prompt_is_collected_by_main_flow(self):
        """主链写前约束确实调用图谱上下文。"""
        root = make_project(self.base / "p", {1: "阿青站在城门。"})
        write_graph(root, [{"id": "qing", "type": "character", "name": "阿青", "location": "城门", "status": "正常",
                            **({'last_updated': 1} if USE_CURRENT_CONTRACT else {})}])
        result = flow._collect_writing_constraints(root, root / "03_manuscript/第2章 audit.md", "继续调查")
        self.observe(graph_context=result.get("graph_context"), sources_ok=result.get("sources_ok"))
        self.assertIn("城门", result["graph_context"]["context_prompt"])

    def test_15_prototype_rejects_nonexistent_quote(self):
        """不存在于引用场景的原文引文会被拒绝。"""
        project = story()
        project["facts"][0]["quote"] = "原文从未出现此句。"
        with self.assertRaises(ValueError) as caught:
            prototype.run_pipeline(project, REPO_ROOT)
        self.observe(error=str(caught.exception))

    def test_16_prototype_rejects_semantically_opposite_fact(self):
        """正确定位的引文不能为语义相反的事实背书。"""
        project = story()
        project["facts"][0]["text"] = "阿青左手完好无伤"
        result = prototype.run_pipeline(project, REPO_ROOT)
        self.observe(fact=project["facts"][0], retrieved_story=result["retrieval"]["story"],
                     declared_scope=result["story_state"]["annotation_origin"])
        self.assertFalse("阿青左手完好无伤" in result["writer_prompt"], "原型校验字符串引文存在，但不判定语义蕴含")

    def test_17_prototype_respects_correctly_labelled_pov_knowledge(self):
        """已正确标注的他人秘密不进入视角写作包。"""
        result = prototype.run_pipeline(story(), REPO_ROOT)
        self.observe(known=result["story_state"]["known_fact_ids"], unknown=result["story_state"]["unknown_fact_ids"])
        self.assertNotIn("夜航", result["writer_prompt"])

    def test_18_prototype_verifies_knowledge_labels_against_text(self):
        """错误的 known_by 标签不能覆盖明确的原文知识边界。"""
        project = story()
        project["facts"][1]["known_by"].append("阿青")
        result = prototype.run_pipeline(project, REPO_ROOT)
        self.observe(source_text=project["scenes"][0]["text"], fact=project["facts"][1],
                     known=result["story_state"]["known_fact_ids"])
        self.assertFalse("夜航" in result["writer_prompt"], "known_by 由输入标签决定，没有从原文自动核验")

    def test_19_beat_expansion_uses_previous_ending(self):
        """上章结尾应实际进入 Beat 扩写提示词。"""
        root = make_project(self.base / "p", {})
        previous = "门后传来三次敲击，阿青仍把断剑握在左手。"
        run_cli("beat_sheet_generator.py", "generate", "--project-root", str(root),
                "--chapter", "2", "--chapter-goal", "继续调查", "--previous-ending", previous)
        expanded = run_cli("beat_sheet_generator.py", "expand", "--project-root", str(root), "--chapter", "2", "--beat-id", "1")
        sheet = json.loads((root / "00_memory/beats/ch0002_beat_sheet.json").read_text(encoding="utf-8"))
        self.observe(previous_ending_stored=sheet["previous_ending"], expand_prompt=expanded["expand_prompt"])
        self.assertTrue(previous in expanded["expand_prompt"], "previous_ending 已存储但 expand 不使用")

    def test_20_beat_pipeline_preserves_retrieved_and_graph_context(self):
        """主链送入的历史及图谱上下文应传到扩写提示词。"""
        root = make_project(self.base / "p", {})
        query = "推进对话与调查。" * 30 + "\n[相关历史剧情]\n历史关键事实：左手断剑不能丢失。"
        constraints = {"outline_constraints": {"constraints_prompt": "保持悬念。" * 50},
                       "event_recommendation": {"notes": ["展开调查。" * 30]},
                       "graph_context": {"context_prompt": "图谱关键事实：阿白仍在海岛，不能立即出现。"}}
        chapter = root / "03_manuscript/第2章 audit.md"
        success, mode = flow._generate_beat_draft(root, chapter, 2, query, constraints,
                                argparse.Namespace(draft_provider="template", pacing_mode="standard", beat_count=4))
        prompt = (root / "00_memory/beats/ch0002_beat01_expand.md").read_text(encoding="utf-8")
        sheet = json.loads((root / "00_memory/beats/ch0002_beat_sheet.json").read_text(encoding="utf-8"))
        self.observe(success=success, mode=mode, input_query_chars=len(query),
                     chapter_goal=sheet["chapter_goal"], previous_ending=sheet["previous_ending"],
                     history_in_prompt="左手断剑不能丢失" in prompt,
                     graph_in_prompt="阿白仍在海岛" in prompt)
        self.assertTrue("左手断剑不能丢失" in prompt, "query[:200] 丢弃后置历史正文；总目标还被限制到400字符")
        self.assertIn("阿白仍在海岛", prompt)


class AuditResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def record(self, test, status, error=None):
        self.records.append({"id": test._testMethodName, "requirement": test.shortDescription(),
                             "status": status, "observations": test.observations, "error": error})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "fail", str(err[1]))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error", str(err[1]))


def main() -> int:
    global USE_CURRENT_CONTRACT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--current-contract", action="store_true", help="显式传入新增截点和POV；有效旧状态补章级时间，断言不放宽")
    parser.add_argument("--run-date", help="报告日期 YYYY-MM-DD（由运行者指定）")
    args = parser.parse_args()
    USE_CURRENT_CONTRACT = args.current_contract
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContinuityRuntimeAudit)
    result = unittest.TextTestRunner(verbosity=2, resultclass=AuditResult).run(suite)
    if args.report_dir:
        args.report_dir.mkdir(parents=True, exist_ok=True)
        counts = {status: sum(r["status"] == status for r in result.records) for status in ("pass", "fail", "error")}
        code_files = ["plot_rag_retriever.py", "story_graph_builder.py", "narrative_prototype.py", "novel_flow_executor.py", "beat_sheet_generator.py"]
        payload = {"schema_version": 1, "date": args.run_date, "repo_root": str(REPO_ROOT),
                   "current_contract": USE_CURRENT_CONTRACT,
                   "method": "Real local functions and CLIs with isolated synthetic fixtures. No LLM/network calls. Unmet requirements remain failing assertions, no expectedFailure.",
                   "limitations": ["边界审计不等于真实小说续写质量评价。", "原型语义验证与自动知情抽取是尚未具备的能力；报告保留其声明范围。",
                     "当前合同显式传入截点/POV，阳性人物状态标注其有效章节；没有改变否定事实或放宽断言。" if USE_CURRENT_CONTRACT else "兼容历史调用方式：不传新增截点/POV参数，不能代表当前API的有界能力。"],
                   "source_sha256": {name: hashlib.sha256((SCRIPT_DIR / name).read_bytes()).hexdigest() for name in code_files},
                   "counts": counts, "checks": result.records}
        (args.report_dir / "runtime-audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = ["# 续写运行边界审计", "", f"日期：{args.run_date or '未指定'}。全部使用临时虚构样本，真实调用现有模块和命令入口，不调用生成模型。", "",
                 f"共 {len(result.records)} 项：通过 {counts['pass']}，未满足 {counts['fail']}，执行错误 {counts['error']}。失败没有标记为预期成功；本文件是能力边界审计。", "",
                 "| 检查 | 结果 |", "| --- | --- |"]
        for row in result.records:
            lines.append(f"| {row['requirement']} | {row['status'].upper()} |")
        lines += ["", "## 证据", ""]
        for row in result.records:
            lines += [f"### {row['id']}", "", row["requirement"] or "", "", f"结果：{row['status'].upper()}。", ""]
            if row["error"]:
                # Failures may include a large actual prompt. Detailed observations remain in JSON.
                lines += [str(row["error"])[-350:], ""]
            lines += ["```json", json.dumps(row["observations"], ensure_ascii=False, indent=2), "```", ""]
        (args.report_dir / "runtime-audit.md").write_text("\n".join(lines), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
