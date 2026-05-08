# Novel-Creator-Skill Script Audit (2026-05-06)

## Scope
- 33 Python scripts + 7 test files
- Dimensions: syntax, imports, paths, params, output format, SKILL.md mapping, e2e testing

## Critical Fixes Required

### PEP 604 Compatibility (Python 3.9)
Two scripts crash on Python 3.9 due to `X | Y` union type syntax (requires 3.10+):

| File | Line | Broken Code | Fix |
|------|------|-------------|-----|
| `fill_config.py` | 88 | `-> str | None:` | `-> Optional[str]:` + `from typing import Optional` |
| `self_review.py` | 50 | `-> Path | None:` | `-> Optional[Path]:` + `from typing import Optional` |

**Note:** PEP 585 lowercase generics (`list[str]`, `dict[str, str]`) work fine on 3.9.

### Output Format Inconsistency
- `style_fingerprint.py` outputs `{"profile_name": ..., "slug": ..., "metrics": ..., "outputs": ...}` without `"ok"` field
- All other 20+ CLI scripts include `{"ok": true/false, ...}` in their JSON output
- Downstream consumers (test scripts, orchestrators) may depend on `ok` field

## Warnings
- `novel_flow_executor.py:12` — unused `import hashlib` (0 references in file)

## E2E Test Results (2026-05-06)
| Step | Command | Result |
|------|---------|--------|
| 1. Init | `novel_flow_executor.py one-click` | ✅ Created 16 files |
| 2. Fill config | `fill_config.py philosophy` | ❌ CRASH (PEP 604) |
| 3. Outline | `outline_generator.py generate --volumes 3` | ✅ Generated 3-volume outline |
| 4. Self review | `self_review.py start --chapter-id 001` | ❌ CRASH (PEP 604) |
| 5. Reflection | `reflection.py new --content "..."` | ✅ Created reflection file |
| 6. Review panel | `review_panel.py summary` | ✅ Graceful empty return |
| 7. Regression | `test_novel_flow_executor.py` | ✅ 10/10 tests pass |

## Path Hardcoding Stats
| Directory | Hardcoded Refs | Scripts |
|-----------|---------------|---------|
| `00_memory` | ~40 | 13 |
| `03_manuscript` | ~19 | 9 |
| `02_knowledge_base` | ~15 | 9 |
| `retrieval` | ~11 | 6 |
| `04_editing` | ~6 | 4 |
| `.flow` | ~5 | 4 |

## Argparse Subcommand Map
```
anti_resolution_guard.py: check, constraint
auto_novel_writer.py: plan, run, progress, report
beat_sheet_generator.py: generate, expand, validate
chapter_synthesizer.py: synthesize, validate
cross_agent_reviewer.py: review, record, unresolved
editorial_team_manager.py: snapshot, status
event_matrix_scheduler.py: init, status, recommend, record
interactive_ideation_engine.py: init, status, collect, advance, generate
novel_flow_executor.py: one-click, continue-write, brainstorm (subcommands via if/elif)
outline_anchor_manager.py: init, check, advance, recalculate
outline_generator.py: generate, revise
pacing_tracker.py: init, record, check, status
plot_rag_retriever.py: build, query
reflection.py: new, list, search
research_agent.py: keywords, gaps, store, plan
review_panel.py: summary, trend
self_review.py: start, submit
story_graph_builder.py: init, export, validate
story_graph_updater.py: extract, apply, diff, cascade
text_humanizer.py: detect, report, prompt
```

## SKILL.md Command → Script Mapping
All 16 core commands map correctly to their scripts. No mismatches found.
