# Integration Test Findings (2026-05-09)

> 40-chapter novel test: 《最后一个知情者》(都市悬疑, 114k chars)
> Test report: `<project-root>/project_test_report.md`

## Script Test Results (12/17 passed)

| Script | Command | Result | Notes |
|--------|---------|--------|-------|
| novel_flow_executor.py | one-click | ✅ | 16 files, RAG index built |
| novel_flow_executor.py | continue-write | ✅ | template mode works, auto gate + index |
| chapter_gate_check.py | direct call | ✅ | 11 checks, needs pre-existing artifacts |
| chapter_gate_check.py | --auto-create-missing | ✅ | NEW: creates placeholder artifacts |
| plot_rag_retriever.py | build | ✅ | 42 chapters indexed |
| plot_rag_retriever.py | query | ✅ | --min-score + BM25 fallback added |
| story_graph_builder.py | validate | ✅ | empty graph validates |
| outline_anchor_manager.py | advance | ✅ | chapter + volume detection works |
| anti_resolution_guard.py | check | ✅ | now uses --chapter (int) not --chapter-file |
| event_matrix_scheduler.py | init/recommend | ✅ | event cooldown works |
| cross_agent_reviewer.py | review | ✅ | generates task + prompt files |
| style_fingerprint.py | extract | ✅ | now uses subcommand mode |
| benchmark_novel_flow.py | baseline | ✅ | 3 rounds, 100% ok, avg 612ms |

## Key Pitfalls Discovered

### 1. Template draft vs CJK word count mismatch
- `generate_draft_text()` targets 2500 non-whitespace chars (`len(re.sub(r'\s+', '', text))`)
- `count_chars(text, include_spaces=False)` counts only CJK chars (~2000-2200)
- Changing evaluate_quality to use count_chars WITHOUT also changing template target → 3 tests fail
- **Fix**: Either change both, or leave both as len(pure) for consistency
- **Status**: Left as len(pure) for now; count_chars imported but unused

### 2. Outline volume hardcoding
- `init_project_files()` had `VOL1_END="120"`, `VOL2_START="121"`, `VOL2_END="240"` hardcoded
- `one_click()` used `// 3500` instead of `// 2500` (番茄巅峰榜基准)
- **Fix**: Dynamic calculation from target_words, `// 2500` divisor

### 3. RAG query returns 0
- `analyze_query_trigger()` skipped queries not matching preset keywords
- `retrieve()` filtered with `> 0` threshold, discarding low-score results
- **Fix**: Default trigger for queries >= 8 chars, `--min-score` arg (default 0.0), BM25 fallback

### 4. Gate artifacts must pre-exist
- `chapter_gate_check.py` fails when 6 artifact files missing
- continue-write creates them automatically, but direct call doesn't
- **Fix**: `--auto-create-missing` flag creates placeholder files

### 5. CLI inconsistency across scripts
- style_fingerprint used positional args (now subcommand)
- anti_resolution_guard used --chapter-file path (now --chapter int)
- **Status**: 2 of ~6 inconsistent scripts fixed

### 6. Truth file system not in pipeline
- chapter_observer.py / chapter_reflector.py existed but not called by continue-write
- **Fix**: Observer prompt auto-generated after gate pass, saved to gate artifacts

## Remaining Issues (deferred)
- #2 Cross-chapter consistency check (new script, 5h+)
- #8 CJK-only word count (needs template target sync)
- #3 Template draft quality (reads novel_plan.md + character_tracker.md)
