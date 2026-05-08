# novel-creator-skill v8.0 命令映射

> 来源：Phase 2 子代理分析（2026-05-06）
> 完整文档：`~/Downloads/novel-creator-command-mapping.md`（480行）

## 核心脚本命令速查

### novel_flow_executor.py（主流程编排器）

```bash
# 一键开书
python3 scripts/novel_flow_executor.py one-click \
  --project-root <目录> --title <书名> --genre <题材> --idea <剧情种子>

# 继续写作（全链路：检索→写作→门禁→索引更新）
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <目录> --query "<新剧情>" \
  --candidate-k 12 --max-auto-retry-rounds 2 --rollback-on-failure

# 改纲
python3 scripts/novel_flow_executor.py revise-outline \
  --project-root <目录> --query "<改纲原因>"

# 脑洞发散
python3 scripts/novel_flow_executor.py brainstorm \
  --project-root <目录> --seed "<种子>" --rounds 5
```

### plot_rag_retriever.py（RAG 检索）

```bash
# 构建索引
python3 scripts/plot_rag_retriever.py build --project-root <目录>

# 检索
python3 scripts/plot_rag_retriever.py query \
  --project-root <目录> --query "<新剧情>" --top-k 4 --candidate-k 12 --auto-build
```

### chapter_gate_check.py（门禁检查）

```bash
python3 scripts/chapter_gate_check.py \
  --project-root <目录> --chapter-file <章节文件> \
  --chapter-id <ID> --pacing-tier fast
```

### story_graph_builder.py（知识图谱）

```bash
python3 scripts/story_graph_builder.py init --project-root <目录>
python3 scripts/story_graph_builder.py add-node --project-root <目录> --type character --name "陈远" --data '{"role":"protagonist"}'
python3 scripts/story_graph_builder.py export --project-root <目录>
python3 scripts/story_graph_builder.py validate --project-root <目录>
python3 scripts/story_graph_builder.py generate-context --project-root <目录>
```

### outline_anchor_manager.py（大纲锚点）

```bash
python3 scripts/outline_anchor_manager.py init --project-root <目录>
python3 scripts/outline_anchor_manager.py check --project-root <目录> --chapter 5
python3 scripts/outline_anchor_manager.py advance --project-root <目录> --chapter 6
```

### style_fingerprint.py（风格提取）

```bash
python3 scripts/style_fingerprint.py \
  --profile-name "番茄快节奏悬疑" \
  --project-root <目录> \
  <样章文件1> <样章文件2> ...
```

## 需新开发的 5 个脚本

| 脚本 | 功能 | 优先级 |
|------|------|--------|
| `fill_config.py` | 碎片想法→结构化填充配置文件 | P0 |
| `outline_generator.py` | 基于 philosophy+characters+motifs 生成大纲 | P0 |
| `self_review.py` | 主观评估（自评分 1-5 + 发布心态） | P1 |
| `review_panel.py` | 每 10 章数据复盘面板 | P1 |
| `reflection.py` | 灵感/反思记录 | P2 |

## 输出格式约定

所有脚本输出 JSON 到 stdout，`ok: true/false` 为顶层状态字段。
