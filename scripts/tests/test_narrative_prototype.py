"""Behavioral contracts for the offline narrative recommendation prototype."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from narrative_prototype import build_catalog, run_pipeline  # noqa: E402


def story_fixture() -> dict:
    """Use independent, Unicode source material with an explicit private fact."""
    return {
        "schema_version": 1,
        "project_id": "contract-story",
        "title": "雨夜的铜钥匙 🗝️",
        "pov_character": "林舟",
        "characters": ["林舟", "许岚"],
        "goal": {
            "id": "recover_and_investigate",
            "description": "处理追逃后果，寻找铜钥匙线索，暂不揭露真相。",
        },
        "scenes": [
            {"id": "s1", "order": 1, "text": "林舟捡到一把铜钥匙。追兵冲进巷口。",
             "function": "action", "tension": 5, "present_characters": ["林舟", "许岚"]},
            {"id": "s2", "order": 2,
             "text": "林舟的左臂受了伤。许岚独自看过证词：刺客的雇主是沈老板。两人继续逃跑。",
             "function": "action", "tension": 5, "present_characters": ["林舟", "许岚"]},
        ],
        "facts": [
            {"id": "f_setup", "text": "林舟持有铜钥匙", "scene_id": "s1",
             "quote": "林舟捡到一把铜钥匙。", "known_by": ["林舟", "许岚"]},
            {"id": "f_injury", "text": "林舟左臂受伤", "scene_id": "s2",
             "quote": "林舟的左臂受了伤。", "known_by": ["林舟", "许岚"]},
            {"id": "f_secret", "text": "沈老板是幕后雇主", "scene_id": "s2",
             "quote": "刺客的雇主是沈老板。", "known_by": ["许岚"]},
        ],
        "threads": [
            {"id": "t_key", "description": "铜钥匙与追杀者的关系", "status": "open",
             "setup_fact_ids": ["f_setup"], "resolution_fact_id": "f_secret",
             "reveal_allowed": False},
        ],
    }


def file_fingerprints() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((REPO_ROOT / "assets").rglob("*")) if path.is_file()
    }


def source_path(ref: str | dict) -> str:
    return ref if isinstance(ref, str) else ref["path"]


class NarrativePrototypeContracts(unittest.TestCase):
    def test_catalog_routes_all_assets_and_preserves_verifiable_sources(self):
        catalog = build_catalog(REPO_ROOT)
        self.assertEqual(len(catalog), 271)
        self.assertEqual(Counter(item["layer"] for item in catalog), {
            "creative": 232, "recommendation": 31, "configuration": 3, "auxiliary": 5,
        })
        self.assertEqual(len({item["id"] for item in catalog}), 271)
        self.assertEqual({item["path"] for item in catalog}, set(file_fingerprints()))
        for item in catalog:
            with self.subTest(path=item["path"]):
                path = (REPO_ROOT / item["path"]).resolve()
                self.assertTrue(path.is_relative_to((REPO_ROOT / "assets").resolve()))
                self.assertTrue(item["title"])
                self.assertTrue(item["kind"])
                self.assertIsInstance(item["eligible"], bool)
                self.assertEqual(item["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                if item["layer"] == "auxiliary":
                    self.assertFalse(item["eligible"])

    def test_default_pipeline_returns_grounded_json_report(self):
        project = story_fixture()
        result = run_pipeline(project, REPO_ROOT)
        self.assertEqual(json.loads(json.dumps(result, ensure_ascii=False)), result)
        for key in ("recommendations", "rejected", "retrieval", "writer_prompt", "trace", "catalog_summary"):
            self.assertIn(key, result)
        self.assertEqual(result["recommendations"][0]["id"], "aftermath_clue")
        self.assertLessEqual(len(result["recommendations"]), 3)
        self.assertTrue(result["trace"])
        self.assertTrue(result["retrieval"]["story"])
        self.assertTrue(result["retrieval"]["knowledge"])
        self.assertTrue(result["writer_prompt"].strip())
        fact_ids = {fact["id"] for fact in project["facts"]}
        for item in result["recommendations"]:
            with self.subTest(strategy=item["id"]):
                for key in ("id", "title", "score", "score_breakdown", "reasons", "beats",
                            "evidence_fact_ids", "source_refs", "context_packet"):
                    self.assertIn(key, item)
                self.assertTrue(item["reasons"])
                self.assertTrue(item["beats"])
                self.assertTrue(item["source_refs"])
                self.assertLessEqual(set(item["evidence_fact_ids"]), fact_ids)
                for ref in item["source_refs"]:
                    path = (REPO_ROOT / source_path(ref)).resolve()
                    self.assertTrue(path.is_relative_to((REPO_ROOT / "assets").resolve()))
                    self.assertTrue(path.is_file())

    def test_author_goal_changes_first_recommendation(self):
        project = story_fixture()
        recover = run_pipeline(project, REPO_ROOT)
        project["goal"] = {"id": "raise_pressure", "description": "提高压力，推动下一次危机。"}
        pressure = run_pipeline(project, REPO_ROOT)
        self.assertEqual(recover["recommendations"][0]["id"], "aftermath_clue")
        self.assertEqual(pressure["recommendations"][0]["id"], "escalate_pressure")

    def test_reveal_requires_permission_setup_resolution_and_pov_knowledge(self):
        ready = story_fixture()
        ready["goal"] = {"id": "reveal_truth", "description": "兑现铜钥匙伏笔。"}
        ready["threads"][0]["reveal_allowed"] = True
        ready["facts"][2]["known_by"].append("林舟")
        accepted = run_pipeline(ready, REPO_ROOT, top_k=4)
        self.assertIn("earned_reveal", {item["id"] for item in accepted["recommendations"]})
        self.assertEqual(accepted["recommendations"][0]["id"], "earned_reveal")
        mutations = {
            "permission": lambda p: p["threads"][0].update(reveal_allowed=False),
            "setup": lambda p: p["threads"][0].update(setup_fact_ids=[]),
            "resolution": lambda p: p["threads"][0].update(resolution_fact_id=None),
            "knowledge": lambda p: p["facts"][2].update(known_by=["许岚"]),
            "already_resolved": lambda p: p["threads"][0].update(status="resolved"),
            "chronology": lambda p: [scene.update(order=3 - scene["order"])
                                      for scene in p["scenes"]],
        }
        for reason, mutate in mutations.items():
            with self.subTest(missing=reason):
                project = copy.deepcopy(ready)
                mutate(project)
                result = run_pipeline(project, REPO_ROOT, top_k=4)
                self.assertNotIn("earned_reveal", {item["id"] for item in result["recommendations"]})
                rejected = {item["id"]: item for item in result["rejected"]}
                self.assertIn("earned_reveal", rejected)
                self.assertTrue(rejected["earned_reveal"]["reasons"])

    def test_dialogue_requires_present_characters_and_shared_knowledge(self):
        for missing in ("partner", "shared_fact", "pov_present"):
            with self.subTest(missing=missing):
                project = story_fixture()
                if missing == "partner":
                    project["scenes"][-1]["present_characters"] = ["林舟"]
                elif missing == "pov_present":
                    project["scenes"][-1]["present_characters"] = ["许岚"]
                else:
                    for fact in project["facts"]:
                        if "林舟" in fact["known_by"]:
                            fact["known_by"] = ["林舟"]
                result = run_pipeline(project, REPO_ROOT, top_k=4)
                self.assertNotIn("subtext_probe", {item["id"] for item in result["recommendations"]})
                self.assertIn("subtext_probe", {item["id"] for item in result["rejected"]})

    def test_writer_material_never_leaks_unknown_fact_or_its_scene_text(self):
        project = story_fixture()
        result = run_pipeline(project, REPO_ROOT, top_k=4)
        private = project["facts"][2]
        materials = [result["writer_prompt"]] + [
            json.dumps(item["context_packet"], ensure_ascii=False)
            for item in result["recommendations"]
        ]
        for material in materials:
            for secret in (private["text"], private["quote"], "沈老板"):
                self.assertNotIn(secret, material)

    def test_repeated_high_tension_increases_need_for_aftermath(self):
        high = story_fixture()
        low = copy.deepcopy(high)
        for scene in low["scenes"]:
            scene["tension"] = 1
        high_result = run_pipeline(high, REPO_ROOT, top_k=4)
        low_result = run_pipeline(low, REPO_ROOT, top_k=4)
        by_id = lambda result: {item["id"]: item for item in result["recommendations"]}
        self.assertGreater(by_id(high_result)["aftermath_clue"]["score"],
                           by_id(low_result)["aftermath_clue"]["score"])
        self.assertNotEqual(by_id(high_result)["aftermath_clue"]["score_breakdown"],
                            by_id(low_result)["aftermath_clue"]["score_breakdown"])

    def test_invalid_inputs_and_broken_references_fail_explicitly(self):
        invalid = [None, [], {}, "story"]
        mutations = {
            "no_scenes": lambda p: p.update(scenes=[]),
            "empty_title": lambda p: p.update(title=""),
            "unknown_pov": lambda p: p.update(pov_character="陌生人"),
            "invalid_goal_type": lambda p: p["goal"].update(id=[]),
            "duplicate_scene": lambda p: p["scenes"][1].update(id="s1"),
            "bad_order": lambda p: p["scenes"][0].update(order=-1),
            "bad_tension": lambda p: p["scenes"][0].update(tension=6),
            "boolean_tension": lambda p: p["scenes"][0].update(tension=True),
            "missing_scene": lambda p: p["facts"][0].update(scene_id="absent"),
            "invented_quote": lambda p: p["facts"][0].update(quote="原文并不存在这一句。"),
            "unknown_knower": lambda p: p["facts"][0].update(known_by=["陌生人"]),
            "missing_setup_fact": lambda p: p["threads"][0].update(setup_fact_ids=["absent"]),
            "bad_thread_status": lambda p: p["threads"][0].update(status="maybe"),
            "invalid_thread_status_type": lambda p: p["threads"][0].update(status=[]),
            "bad_reveal_type": lambda p: p["threads"][0].update(reveal_allowed="false"),
        }
        for name, mutate in mutations.items():
            project = story_fixture()
            mutate(project)
            invalid.append((name, project))
        for item in invalid:
            name, project = item if isinstance(item, tuple) else (repr(item), item)
            with self.subTest(invalid=name), self.assertRaises(ValueError):
                run_pipeline(project, REPO_ROOT)
        for top_k in (None, 0, -1, True, "3"):
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                run_pipeline(story_fixture(), REPO_ROOT, top_k=top_k)
        self.assertEqual(len(run_pipeline(story_fixture(), REPO_ROOT, top_k=1)["recommendations"]), 1)

    def test_pipeline_is_deterministic_and_does_not_mutate_inputs_or_assets(self):
        project = story_fixture()
        before_project = copy.deepcopy(project)
        before_assets = file_fingerprints()
        first = run_pipeline(project, REPO_ROOT)
        second = run_pipeline(project, REPO_ROOT)
        self.assertEqual(first, second)
        with ThreadPoolExecutor(max_workers=3) as pool:
            parallel = list(pool.map(lambda _: run_pipeline(project, REPO_ROOT), range(3)))
        self.assertTrue(all(result == first for result in parallel))
        self.assertEqual(project, before_project)
        self.assertEqual(file_fingerprints(), before_assets)
        project["scenes"].reverse()
        self.assertEqual(run_pipeline(project, REPO_ROOT), first)

    def test_cli_writes_reviewable_outputs_and_rejects_asset_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = story_fixture()
            project["title"] = '<img src=x onerror="alert(1)"> 的铜钥匙'
            story_path = root / "story.json"
            story_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
            output = root / "result"
            command = [sys.executable, str(REPO_ROOT / "scripts/narrative_prototype.py"),
                       "--project", str(story_path), "--output-dir", str(output),
                       "--goal", "raise_pressure", "--top-k", "1"]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads((output / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(report["recommendations"][0]["id"], "escalate_pressure")
            self.assertEqual(len(report["recommendations"]), 1)
            self.assertEqual((output / "writer_prompt.txt").read_text(encoding="utf-8"),
                             report["writer_prompt"])
            html = (output / "report.html").read_text(encoding="utf-8")
            self.assertIn("<html", html.lower())
            self.assertNotIn(project["title"], html)
            before_assets = file_fingerprints()
            command[command.index("--output-dir") + 1] = str(REPO_ROOT / "assets")
            refused = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(before_assets, file_fingerprints())
            linked_output = root / "linked-output"
            linked_output.mkdir()
            sentinel = root / "do-not-overwrite.json"
            sentinel.write_text('{"original": true}', encoding="utf-8")
            (linked_output / "result.json").symlink_to(sentinel)
            command[command.index("--output-dir") + 1] = str(linked_output)
            refused = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), '{"original": true}')

    def test_recommendation_sources_reject_escape_missing_paths_and_symlinks(self):
        original = json.loads((REPO_ROOT / "recommendation/cards.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            cards_path = temp_path / "cards.json"
            for bad_path in (".", "../secret.md", str(temp_path / "secret.md"),
                             "assets/technique_library/absent-asset.md"):
                with self.subTest(path=bad_path):
                    cards = copy.deepcopy(original)
                    cards["cards"][0]["source_paths"] = [bad_path]
                    cards_path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        run_pipeline(story_fixture(), REPO_ROOT, cards_path=cards_path)
            isolated_repo = temp_path / "repo"
            asset_dir = isolated_repo / "assets/technique_library"
            asset_dir.mkdir(parents=True)
            outside = temp_path / "outside.md"
            outside.write_text("# This is outside the asset library", encoding="utf-8")
            (asset_dir / "escape.md").symlink_to(outside)
            cards = copy.deepcopy(original)
            for card in cards["cards"]:
                card["source_paths"] = ["assets/technique_library/escape.md"]
            cards_path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                run_pipeline(story_fixture(), isolated_repo, cards_path=cards_path)

    def test_no_verified_facts_produces_no_unsupported_recommendation(self):
        project = story_fixture()
        project["facts"] = []
        project["threads"] = []
        result = run_pipeline(project, REPO_ROOT)
        self.assertEqual(result["recommendations"], [])
        self.assertTrue(result["writer_prompt"].strip())
        self.assertNotIn("沈老板", result["writer_prompt"])
        self.assertTrue(result["rejected"])

    def test_comparison_preserves_original_goal_and_exact_main_report(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            project = story_fixture()
            project["goal"]["description"] = "先核对铜钥匙的用途，保留许岚的秘密，避免新增追兵。"
            source = directory / "story.json"
            source.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
            output = directory / "output"
            completed = subprocess.run([
                sys.executable, str(REPO_ROOT / "scripts/narrative_prototype.py"),
                "--project", str(source), "--output-dir", str(output), "--compare-goals",
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads((output / "result.json").read_text(encoding="utf-8"))
            comparison = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
            variants = comparison["variants"]
            self.assertEqual(len(variants), 3)
            matching = [variant["report"] for variant in variants
                        if variant["report"]["story_state"]["goal"]["id"] == project["goal"]["id"]]
            self.assertEqual(matching, [report])
            self.assertEqual(report["story_state"]["goal"], project["goal"])

    def test_plan_evidence_is_not_randomly_bound_to_individual_beats(self):
        result = run_pipeline(story_fixture(), REPO_ROOT)
        for recommendation in result["recommendations"]:
            packet = recommendation["context_packet"]
            self.assertEqual(packet["evidence_fact_ids"], recommendation["evidence_fact_ids"])
            self.assertEqual({fact["id"] for fact in packet["facts"]},
                             set(recommendation["evidence_fact_ids"]))
            for beat in recommendation["beats"]:
                self.assertIn("待作者确认", beat)
                self.assertNotIn("事实锚点", beat)

    def test_aftermath_with_clue_requires_an_available_open_thread(self):
        project = story_fixture()
        project["threads"] = []
        result = run_pipeline(project, REPO_ROOT, top_k=4)
        accepted = {item["id"] for item in result["recommendations"]}
        rejected = {item["id"] for item in result["rejected"]}
        self.assertNotIn("aftermath_clue", accepted)
        self.assertIn("aftermath_clue", rejected)
        self.assertIn("subtext_probe", accepted)

    def test_overbroad_source_quote_does_not_leak_into_writer_packet(self):
        project = story_fixture()
        project["facts"][1]["quote"] = project["scenes"][1]["text"]
        result = run_pipeline(project, REPO_ROOT)
        self.assertTrue(any("沈老板" in fact["quote"] for fact in result["retrieval"]["story"]))
        self.assertNotIn("沈老板", result["writer_prompt"])
        for recommendation in result["recommendations"]:
            packet = recommendation["context_packet"]
            self.assertNotIn("沈老板", json.dumps(packet, ensure_ascii=False))
            for fact in packet["facts"]:
                self.assertEqual(set(fact), {"id", "text", "scene_id"})

    def test_cli_refuses_to_overwrite_input_with_any_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for filename in ("result.json", "writer_prompt.txt", "report.html", "comparison.json"):
                with self.subTest(filename=filename):
                    output = directory / filename.replace(".", "-")
                    output.mkdir()
                    source = output / filename
                    original = json.dumps(story_fixture(), ensure_ascii=False).encode("utf-8")
                    source.write_bytes(original)
                    completed = subprocess.run([
                        sys.executable, str(REPO_ROOT / "scripts/narrative_prototype.py"),
                        "--project", str(source), "--output-dir", str(output), "--compare-goals",
                    ], capture_output=True, text=True, timeout=30)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertNotIn("Traceback", completed.stderr)
                    self.assertEqual(source.read_bytes(), original)
                    self.assertEqual({path.name for path in output.iterdir()}, {filename})

if __name__ == "__main__":
    unittest.main()
