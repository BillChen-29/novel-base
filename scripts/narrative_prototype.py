#!/usr/bin/env python3
"""Offline, inspectable narrative recommendation prototype (stdlib only).

Story annotations and strategy cards are author supplied. Exact quote checks
establish provenance, not factual interpretation or literary quality. No model,
embedding service, QMD index, or existing writing workflow is invoked here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath


GOALS = {
    "recover_and_investigate": "处理后果并沿既有线索调查",
    "raise_pressure": "保持压力并推进当前目标",
    "reveal_truth": "在前提与许可允许时揭示真相",
}
REQUIREMENTS = {"open_thread", "two_characters", "reveal_ready"}
AUXILIARY = {
    "assets/style_library/index.md", "assets/style_library/style-dd66a72d.md",
    "assets/pacing/real-data-pacing-benchmark.md",
    "assets/technique_library/real-data-pacing-benchmark.md",
    "assets/ingest_manifest.json",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: object, name: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{name} 必须是非空字符串")
    return value


def _strings(value: object, name: str, nonempty: bool = False) -> list[str]:
    _require(isinstance(value, list), f"{name} 必须是字符串列表")
    for item in value:
        _text(item, name)
    _require(len(set(value)) == len(value), f"{name} 不得重复")
    _require(not nonempty or bool(value), f"{name} 不得为空")
    return value


def _integer(value: object, name: str, low: int, high: int | None = None) -> int:
    _require(type(value) is int and value >= low and (high is None or value <= high),
             f"{name} 必须是 {low} 至 {high if high is not None else '任意上限'} 的整数")
    return value


def _objects(value: object, name: str, nonempty: bool = False) -> list[dict]:
    _require(isinstance(value, list) and all(isinstance(x, dict) for x in value),
             f"{name} 必须是对象列表")
    _require(not nonempty or bool(value), f"{name} 不得为空")
    return value


def _validate_project(project: dict) -> dict:
    _require(isinstance(project, dict), "project 必须是对象")
    _require(type(project.get("schema_version")) is int and project["schema_version"] == 1,
             "project.schema_version 必须为 1")
    for field in ("project_id", "title", "pov_character"):
        _text(project.get(field), field)
    characters = set(_strings(project.get("characters"), "characters", True))
    _require(project["pov_character"] in characters, "pov_character 必须属于 characters")
    goal = project.get("goal")
    _require(isinstance(goal, dict), "goal 必须是对象")
    _require(isinstance(goal.get("id"), str) and goal["id"] in GOALS, "goal.id 不受支持")
    _text(goal.get("description"), "goal.description")
    ids: set[str] = set()
    orders: set[int] = set()
    scenes = _objects(project.get("scenes"), "scenes", True)
    facts = _objects(project.get("facts"), "facts")
    threads = _objects(project.get("threads"), "threads")
    for group in (scenes, facts, threads):
        for item in group:
            ident = _text(item.get("id"), "id")
            _require(ident not in ids, f"重复 id: {ident}")
            ids.add(ident)
    scene_map = {s["id"]: s for s in scenes}
    fact_map = {f["id"]: f for f in facts}
    for scene in scenes:
        order = _integer(scene.get("order"), "scene.order", 1)
        _require(order not in orders, "scene.order 不得重复")
        orders.add(order)
        _integer(scene.get("tension"), "scene.tension", 1, 5)
        _text(scene.get("text"), "scene.text")
        _text(scene.get("function"), "scene.function")
        present = _strings(scene.get("present_characters"), "present_characters")
        _require(set(present) <= characters, "present_characters 含未知角色")
    for fact in facts:
        _text(fact.get("text"), "fact.text")
        scene_id = _text(fact.get("scene_id"), "fact.scene_id")
        _require(scene_id in scene_map, f"事实引用不存在的场景: {scene_id}")
        quote = _text(fact.get("quote"), "fact.quote")
        _require(quote in scene_map[scene_id]["text"], f"事实 {fact['id']} 的引文不在对应原文中")
        _require(set(_strings(fact.get("known_by"), "known_by")) <= characters,
                 "known_by 含未知角色")
    for thread in threads:
        _text(thread.get("description"), "thread.description")
        _require(isinstance(thread.get("status"), str) and thread["status"] in {"open", "resolved"},
                 "thread.status 不受支持")
        setup = _strings(thread.get("setup_fact_ids"), "setup_fact_ids")
        _require(set(setup) <= set(fact_map), "setup_fact_ids 引用了不存在的事实")
        resolution = thread.get("resolution_fact_id")
        _require("resolution_fact_id" in thread and
                 (resolution is None or isinstance(resolution, str) and resolution in fact_map),
                 "resolution_fact_id 必须为空或引用已有事实")
        _require(type(thread.get("reveal_allowed")) is bool, "reveal_allowed 必须为布尔值")
    result = copy.deepcopy(project)
    result["scenes"].sort(key=lambda scene: scene["order"])
    return result


def _asset_path(repo_root: Path, value: str) -> Path:
    _text(value, "source_path")
    relative = PurePosixPath(value)
    _require(bool(relative.parts) and not relative.is_absolute() and ".." not in relative.parts and
             "\\" not in value and relative.parts[0] == "assets" and
             str(relative) == value, f"非法资产路径: {value}")
    root = repo_root.resolve()
    assets = (root / "assets").resolve()
    path = (root / value).resolve()
    _require(assets.is_relative_to(root) and path.is_relative_to(assets),
             f"资产路径逃逸: {value}")
    _require(path.is_file(), f"资产文件不存在: {value}")
    return path


def _classification(path: str) -> tuple[str, str, bool]:
    if path in AUXILIARY:
        kind = "index" if path.endswith("index.md") else "report_or_log"
        if path.endswith("style-dd66a72d.md"):
            kind = "test_fixture"
        return "auxiliary", kind, False
    if path.startswith("assets/platforms/"):
        return "configuration", "platform", False
    for directory, kind in (("motif_library", "motif"),
                            ("character_archetypes", "character"), ("style_library", "style")):
        if path.startswith(f"assets/{directory}/"):
            return "creative", kind, True
    if path.startswith("assets/technique_library/_scenarios/"):
        return "recommendation", "scenario", True
    if path.startswith("assets/technique_library/"):
        return "recommendation", "technique", True
    if path.startswith("assets/pacing/"):
        return "recommendation", "pacing", True
    if path == "assets/ai_patterns.md":
        return "recommendation", "editing", True
    return "auxiliary", "unclassified", False


def build_catalog(repo_root: Path) -> list[dict]:
    """Classify real asset files without moving or rewriting their contents."""
    root = Path(repo_root).resolve()
    _require((root / "assets").is_dir(), "仓库 assets 目录不存在")
    catalog = []
    for path in sorted((root / "assets").rglob("*")):
        if path.is_symlink():
            _require(path.resolve().is_relative_to((root / "assets").resolve()),
                     f"资产符号链接逃逸: {path.name}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        safe_path = _asset_path(root, relative)
        raw = safe_path.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"资产不是 UTF-8: {relative}") from error
        heading = re.search(r"^#\s+(.+?)\s*$", content, re.MULTILINE)
        layer, kind, eligible = _classification(relative)
        catalog.append({"id": relative, "path": relative,
                        "title": heading.group(1) if heading else path.stem,
                        "layer": layer, "kind": kind, "eligible": eligible,
                        "sha256": hashlib.sha256(raw).hexdigest()})
    return catalog


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 JSON {path.name}: {error}") from error


def _load_cards(path: Path, root: Path, catalog: list[dict]) -> list[dict]:
    data = _read_json(path)
    _require(isinstance(data, dict) and type(data.get("schema_version")) is int and
             data["schema_version"] == 1, "策略 schema_version 必须为 1")
    cards = _objects(data.get("cards"), "cards", True)
    by_path = {item["path"]: item for item in catalog}
    identifiers: set[str] = set()
    for card in cards:
        for field in ("id", "title", "description", "function", "expected_effect"):
            _text(card.get(field), f"card.{field}")
        _require(card["id"] not in identifiers, "策略 id 不得重复")
        identifiers.add(card["id"])
        _text(card.get("target_tension"), "target_tension")
        for field in ("goals", "requires", "source_paths", "query_terms", "operations", "avoid_when"):
            _strings(card.get(field), f"card.{field}", field in {"goals", "source_paths", "operations"})
        _require(set(card["goals"]) <= set(GOALS), "策略 goals 不受支持")
        _require(set(card["requires"]) <= REQUIREMENTS, "策略 requires 不受支持")
        for source in card["source_paths"]:
            _asset_path(root, source)
            _require(source in by_path and by_path[source]["layer"] == "recommendation" and
                     by_path[source]["eligible"], f"策略来源不属于可用推荐知识: {source}")
    return cards


def _tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    for run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]+", text):
        tokens.update(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            tokens.add(run)
    return tokens


def _similarity(query: set[str], text: str) -> float:
    words = _tokens(text)
    return len(query & words) / math.sqrt(len(query) * len(words)) if query and words else 0.0


def _source_ref(item: dict, content: str, query: set[str]) -> dict:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    passage = max(paragraphs, key=lambda part: _similarity(query, part), default=content)
    return {"path": item["path"], "title": item["title"], "excerpt": passage[:600],
            "sha256": item["sha256"]}


def _reveal_readiness(project: dict, known: dict[str, dict]) -> tuple[list[dict], list[str]]:
    order = {scene["id"]: scene["order"] for scene in project["scenes"]}
    ready, failures = [], []
    for thread in project["threads"]:
        resolution = thread["resolution_fact_id"]
        setup = thread["setup_fact_ids"]
        missing = []
        if thread["status"] != "open":
            missing.append("线索已经完成")
        if not thread["reveal_allowed"]:
            missing.append("作者尚未允许揭示")
        if not setup:
            missing.append("缺少铺垫事实")
        elif not all(ident in known for ident in setup):
            missing.append("视角人物尚未知晓全部铺垫")
        if resolution is None:
            missing.append("缺少答案事实")
        elif resolution not in known:
            missing.append("视角人物未知答案")
        elif setup and all(ident in known for ident in setup):
            end = order[known[resolution]["scene_id"]]
            if not all(order[known[ident]["scene_id"]] < end for ident in setup):
                missing.append("铺垫必须早于答案")
        if missing:
            failures.append(f"{thread['id']}：{'、'.join(missing)}")
        else:
            ready.append(thread)
    return ready, failures or ["没有可用于揭示的未完成线索"]


def _shared_facts(project: dict, known: dict[str, dict]) -> list[str]:
    present = set(project["scenes"][-1]["present_characters"])
    pov = project["pov_character"]
    return [fact["id"] for fact in known.values()
            if pov in present and len(present & set(fact["known_by"])) >= 2]


def _score_card(card: dict, project: dict) -> list[dict]:
    parts = [{"rule": "base", "points": 50, "reason": "通过必要条件的策略基线"}]
    goal = project["goal"]["id"]
    if goal in card["goals"]:
        parts.append({"rule": "author_goal", "points": 40, "reason": "符合作者当前目标"})
    recent = project["scenes"][-2:]
    high = len(recent) == 2 and all(scene["tension"] >= 4 for scene in recent)
    if card["id"] == "aftermath_clue" and high:
        parts.append({"rule": "aftermath_after_pressure", "points": 15,
                      "reason": "最近两场相对强度较高，优先考虑处理后果"})
    if card["id"] == "escalate_pressure" and high and goal != "raise_pressure":
        parts.append({"rule": "consecutive_pressure", "points": -20,
                      "reason": "已连续高强度，且作者未要求继续加压"})
    if project["scenes"][-1]["function"] == card["function"]:
        parts.append({"rule": "repeated_function", "points": -10,
                      "reason": "与最近一场功能重复，降低优先级供作者比较"})
    return parts


def run_pipeline(project: dict, repo_root: Path, cards_path: Path | None = None,
                 top_k: int = 3) -> dict:
    """Return a deterministic report, leaving the caller and all assets unchanged."""
    _integer(top_k, "top_k", 1)
    project = _validate_project(project)
    root = Path(repo_root).resolve()
    catalog = build_catalog(root)
    cards = _load_cards(Path(cards_path) if cards_path else root / "recommendation/cards.json",
                        root, catalog)
    content = {item["path"]: _asset_path(root, item["path"]).read_text(encoding="utf-8")
               for item in catalog if item["eligible"]}
    by_path = {item["path"]: item for item in catalog}
    pov = project["pov_character"]
    known = {fact["id"]: {field: copy.deepcopy(fact[field]) for field in
             ("id", "text", "scene_id", "quote", "known_by")}
             for fact in project["facts"] if pov in fact["known_by"]}
    query = _tokens(project["goal"]["description"] + " " + " ".join(
        fact["text"] for fact in known.values()))
    scene_orders = {scene["id"]: scene["order"] for scene in project["scenes"]}
    ranked_facts = sorted(known.values(), key=lambda fact: (
        -_similarity(query, fact["text"]), -scene_orders[fact["scene_id"]], fact["id"]))
    story_hits = [{**copy.deepcopy(fact), "score": round(_similarity(query, fact["text"]), 6),
                   "provenance": "作者提供；已核验引文在原场景出现，未自动验证语义解释"}
                  for fact in ranked_facts[:6]]
    creative_query = query | _tokens(" ".join(term for card in cards
        if project["goal"]["id"] in card["goals"] for term in card["query_terms"]))
    creative = []
    for item in catalog:
        if item["layer"] != "creative" or not item["eligible"]:
            continue
        score = _similarity(creative_query, item["title"]) + _similarity(
            creative_query, content[item["path"]])
        if score > 0:
            creative.append({**_source_ref(item, content[item["path"]], creative_query),
                             "score": round(score, 6), "kind": item["kind"],
                             "usage": "外部创作参考；不构成本书已发生的事实"})
    creative.sort(key=lambda hit: (-hit["score"], hit["path"]))
    creative = creative[:4]
    ready, reveal_failures = _reveal_readiness(project, known)
    open_setup = [ident for thread in project["threads"] if thread["status"] == "open"
                  for ident in thread["setup_fact_ids"] if ident in known]
    shared_facts = _shared_facts(project, known)
    requirements = {
        "open_thread": bool(open_setup),
        "two_characters": bool(shared_facts),
        "reveal_ready": bool(ready),
    }
    missing_messages = {
        "open_thread": "缺少由视角人物已知事实铺垫的未完成线索",
        "two_characters": "最近场景需有视角人物与另一角色在场，且至少共享一条已知事实",
        "reveal_ready": "；".join(reveal_failures),
    }
    recommendations, rejected = [], []
    for card in cards:
        reasons = [missing_messages[rule] for rule in card["requires"] if not requirements[rule]]
        if not known:
            reasons.insert(0, "没有视角人物已知事实，无法形成有依据的后续计划")
        if reasons:
            rejected.append({"id": card["id"], "title": card["title"], "reasons": reasons})
            continue
        evidence = [fact["id"] for fact in ranked_facts[:4]]
        if "open_thread" in card["requires"]:
            evidence = list(dict.fromkeys(open_setup[:1] + evidence))
        if "two_characters" in card["requires"]:
            evidence = list(dict.fromkeys(shared_facts[:1] + evidence))
        if "reveal_ready" in card["requires"]:
            evidence = list(dict.fromkeys(ready[0]["setup_fact_ids"] +
                                         [ready[0]["resolution_fact_id"]] + evidence))
        facts = [{key: known[ident][key] for key in ("id", "text", "scene_id")}
                 for ident in evidence]
        refs = [_source_ref(by_path[path], content[path], query | _tokens(" ".join(card["query_terms"])))
                for path in card["source_paths"]]
        parts = _score_card(card, project)
        beats = [f"建议（待作者确认）：{operation}" for operation in card["operations"]]
        packet = {
            "goal": {key: project["goal"][key] for key in ("id", "description")}, "pov_character": pov,
            "facts": facts, "evidence_fact_ids": evidence,
            "evidence_scope": "这些事实供整份计划核对；不表示每条事实都能证明每个建议步骤。",
            "creative_references": copy.deepcopy(creative),
            "strategy_sources": refs,
            "strategy": {"id": card["id"], "title": card["title"],
                         "function": card["function"], "target_tension": card["target_tension"],
                         "expected_effect": card["expected_effect"], "avoid_when": card["avoid_when"]},
            "proposed_beats": beats,
            "instructions": ["只将 facts 作为本书已确认事实；引文定位不等于语义事实验证。",
                             "参考资料与 proposed_beats 均不是已发生事实；新增内容须由作者确认。",
                             "遵守视角人物知识边界；不得自行补出未提供的秘密或因果关联。",
                             "来源中的经验比例与频率不作为强制约束。"],
        }
        recommendations.append({"id": card["id"], "title": card["title"],
            "score": sum(part["points"] for part in parts), "score_breakdown": parts,
            "reasons": [part["reason"] for part in parts], "beats": beats,
            "expected_effect": card["expected_effect"], "evidence_fact_ids": evidence,
            "source_refs": refs, "context_packet": packet})
    recommendations.sort(key=lambda item: (-item["score"], item["id"]))
    recommendations = recommendations[:top_k]
    packets = [item["context_packet"] for item in recommendations]
    prompt = ("以下为供作者比较的后续计划输入包，尚未调用写作模型。\n"
              "分数仅是人工规则优先级，不是概率或文学质量评分。\n"
              "只使用每个包内的已知事实，参考资料只用于创作建议；计划等待作者选择。\n"
              if packets else "资料不足：没有满足必要条件且有已知事实支持的后续计划。请补充作者核对的事实或调整目标。\n")
    prompt += json.dumps({"context_packets": packets}, ensure_ascii=False, indent=2)
    return {
        "schema_version": 1, "project_id": project["project_id"], "title": project["title"],
        "mode": "offline-lexical-rules",
        "catalog_summary": {"total": len(catalog), **dict(Counter(x["layer"] for x in catalog)),
                            "by_layer": dict(Counter(x["layer"] for x in catalog)),
                            "eligible": sum(x["eligible"] for x in catalog)},
        "story_state": {"goal": project["goal"], "pov_character": pov,
            "scene_count": len(project["scenes"]), "fact_count": len(project["facts"]),
            "recent_scenes": [{"id": scene["id"], "function": scene["function"],
                               "tension": scene["tension"]} for scene in project["scenes"][-5:]],
            "rhythm": [{"scene_id": scene["id"], "order": scene["order"],
                        "function": scene["function"], "tension": scene["tension"]}
                       for scene in project["scenes"]],
            "known_fact_ids": list(known),
            "unknown_fact_ids": [f["id"] for f in project["facts"] if f["id"] not in known],
            "annotation_origin": "作者提供；只验证结构、引用与原文引文，不自动判定语义正确性"},
        "retrieval": {"story": story_hits, "knowledge": creative},
        "recommendations": recommendations, "rejected": rejected, "writer_prompt": prompt,
        "trace": [
            {"stage": "validate", "detail": "核验数据格式、角色引用、事实引文与场景顺序"},
            {"stage": "catalog", "detail": "对真实 assets 逻辑分层并记录 SHA-256，未改写原始资产"},
            {"stage": "retrieve", "detail": "仅用视角人物已知事实与目标做中文二元词/英文词的词面匹配"},
            {"stage": "recommend", "detail": "先检查必要条件，再按公开规则排序；目标强度由作者定义"},
            {"stage": "assemble", "detail": f"将 {len(packets)} 份真实上游输入包序列化进 writer_prompt；未调用 AI"},
        ],
    }


def _output_directory(value: str | None, root: Path) -> Path:
    output = Path(value).expanduser().resolve() if value else root / "runtime-data/narrative-prototype"
    _require(not output.is_relative_to(root) or output.is_relative_to(root / "runtime-data"),
             "仓库内的输出目录必须位于 runtime-data 下")
    output.mkdir(parents=True, exist_ok=True)
    # Recheck after mkdir to cover existing symlink components.
    output = output.resolve()
    _require(not output.is_relative_to(root) or output.is_relative_to(root / "runtime-data"),
             "输出目录不得覆盖仓库代码或资产")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="作者标注的故事 JSON")
    parser.add_argument("--output-dir", help="输出目录；仓库内限 runtime-data")
    parser.add_argument("--goal", choices=GOALS)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--compare-goals", action="store_true", help="预运行三种作者目标供页面切换")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        project = _read_json(Path(args.project).expanduser())
        if args.goal:
            _require(isinstance(project, dict), "project 必须是对象")
            project["goal"] = {"id": args.goal, "description": GOALS[args.goal]}
        report = run_pipeline(project, root, top_k=args.top_k)
        variants = []
        if args.compare_goals:
            for goal, label in GOALS.items():
                if goal == project["goal"]["id"]:
                    variant_report = report
                else:
                    variant = copy.deepcopy(project)
                    variant["goal"] = {"id": goal, "description": label}
                    variant_report = run_pipeline(variant, root, top_k=args.top_k)
                variants.append({"label": label, "report": variant_report})
        output = _output_directory(args.output_dir, root)
        filenames = ["result.json", "writer_prompt.txt", "report.html"]
        if variants:
            filenames.append("comparison.json")
        source = Path(args.project).expanduser().resolve()
        for filename in filenames:
            target = output / filename
            _require(source != target.resolve() and not (target.exists() and target.samefile(source)),
                     f"输入故事与输出文件冲突，拒绝覆盖: {filename}")
            _require(not target.is_symlink(), f"输出文件不得是符号链接: {filename}")
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "writer_prompt.txt").write_text(report["writer_prompt"], encoding="utf-8")
        if variants:
            (output / "comparison.json").write_text(json.dumps({"variants": variants}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        from narrative_prototype_report import render_report
        (output / "report.html").write_text(render_report(report, comparisons=variants), encoding="utf-8")
        print(f"已完成离线原型：{output / 'report.html'}")
        return 0
    except (ValueError, OSError, ImportError) as error:
        print(f"原型未完成：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
