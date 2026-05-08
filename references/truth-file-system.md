# 真相文件系统架构

> 综合 AI_NovelGenerator + InkOS 设计理念
> 2026-05-07 实现

## 概述

7个真相文件（JSON + schema 验证 + markdown 投影），存储在 `00_memory/truth/` 目录。

## 文件清单

| 文件 | 用途 | 核心字段 |
|------|------|---------|
| `world_state.json` | 世界观 | world_name, magic_system, tech_level, locations, rules |
| `character_matrix.json` | 角色矩阵 | characters[].name, role, personality, motivation, relationships |
| `emotional_arcs.json` | 情感弧光 | characters.{name}.arc[].chapter, emotion, intensity, trigger |
| `resource_ledger.json` | 资源账本 | resources[].name, type, owner, amount, history; power_levels[] |
| `subplot_board.json` | 支线管理 | subplots[].name, status, key_characters, tension_level |
| `hook_ledger.json` | 钩子账本 | hooks[].id, description, status, planted_chapter, deadline |
| `chapter_summaries.json` | 章节摘要 | chapters[].chapter, title, summary, key_events, word_count |

## 钩子操作语义

- `upsert_hook(chapter, description, **kwargs)` — 新增钩子
- `mention_hook(chapter, hook_id)` — 提及已有钩子
- `resolve_hook(chapter, hook_id)` — 回收钩子
- `defer_hook(hook_id, new_deadline)` — 延期钩子
- `check_hook_health(project_root, current_chapter)` — 健康检查（过期/爆发/停滞）

## 健康检查

| 检查项 | 触发条件 | 输出 |
|--------|---------|------|
| stale_debt | deadline < 当前章节 且 status=open | 超期未回收列表 |
| burst_warning | 同一章 resolve > 3 | 同章回收过多警告 |
| no_advance | >10章未 mention 且 status=open | 长期未提及列表 |
| resource_mutation | 金额变化>10倍且无事件记录 | 资源突变警告 |
| emotion_spike | intensity变化>5且无trigger | 情感突变警告 |
| subplot_forgotten | active但>15章未提及 | 遗忘支线列表 |

## 两阶段写作流程

```
Phase 1（创意）：
  truth_manager.load_truth() → 读取真相文件
  unified_search() → 搜索（plot_rag + QMD）
  filter_search_results() → 三级过滤（冲突→价值→分类）
  apply_distance_rules() → 距离权重（近章降权）
  load_scenario_by_role() → 加载场景文件
  → 生成正文

Phase 2（状态沉淀）：
  chapter_observer.py → 组装 Observer prompt
  [LLM 提取 9 类事实]
  chapter_reflector.py → 更新真相文件
  truth_manager.render_markdown() → 生成投影
```

## 知识过滤（3级）

1. **冲突检测**：Jaccard 相似度（关键词重叠），>0.4 跳过
2. **价值评估**：critical/reference/low
3. **结构归类**：plot_fuel/character_dim/world_fragment/narrative_technique

## 章节距离规则

| 距离 | 权重 | 说明 |
|------|------|------|
| ≤2章 | 0.1 | skip（几乎不用） |
| ≤5章 | 0.5 | rewrite_40（需改写≥40%） |
| >5章 | 1.0 | ok（正常引用） |

## 模块清单

```
scripts/
  schemas.py              — 7个 schema 定义
  truth_manager.py        — CRUD + 文件锁 + 所有操作
  migrate_memory.py       — markdown → JSON 迁移
  chapter_observer.py     — 事实提取（prompt组装+JSON解析）
  chapter_reflector.py    — 状态更新（纯Python）
  two_phase_writer.py     — 两阶段写作 wrapper
  auto_truth_sync.py      — 自动同步
  truth_sync_report.py    — 同步报告
  gate_extensions.py      — 门禁扩展（+5步）
  gate_runner.py          — 门禁 wrapper（10步）
  hook_health_check.py    — 钩子健康检查
  resource_consistency_check.py — 资源一致性检查
  emotional_consistency_check.py — 情感弧光检查
  subplot_health_check.py — 支线健康检查
  chapter_info_manager.py — 章节元数据管理
  observer_prompt.md      — Observer prompt 模板
```

## 测试

175个测试用例，通过 `run_all_tests.py` 运行。
