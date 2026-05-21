# 命令详情

> 从 SKILL.md 移出的命令详细说明。

## `/继续写` 的续写前引导机制

每次执行 `/继续写` 时，系统在写作前自动执行：

1. **引导提问**：向用户询问本章的剧情走向偏好（"你希望本章发生什么？有什么新的脑洞吗？"）
2. **脑洞拓展**：基于当前大纲和知识库，提供 2-3 个可能的剧情走向供选择
3. **用户确认**：用户选择一个方向，或提供自己的想法
4. **兜底机制**：如果用户回复"不确定"/"随便"/"自动"，则按 `novel_plan.md` 当前节点自动推进，无需人工干预
5. **全自动模式**：如果在开书确认卡中选择了"全自动"等级，跳过引导直接按大纲写作
6. **节奏预检（⛔ BLOCKING，写作开始前必须声明）**：① 本章节奏档位（慢档/中档/快档）及依据；② 近3章配额触发记录，确认本章 A/B/C 至多触发1项；③ 章末保留的具体悬念是什么。预检未通过时禁止进入写作。

---

## `/改纲续写` 使用说明

**适用场景**：发现主线走向需要调整，修改了 `novel_plan.md` 之后，必须通过此命令重新对齐系统的三层索引（大纲锚点 + 知识图谱 + RAG 索引），然后才能继续写作。

**执行前置条件**（顺序不可颠倒）：
1. 手动编辑 `00_memory/novel_plan.md`，完成改纲内容
2. 确认改纲影响的起始章节（`--from-chapter`），即从第几章开始剧情走向已发生变化

**三步级联流程**：
1. **锚点重算**（必须成功，否则中止）：备份当前 `outline_anchors.json` → 从修改后的 `novel_plan.md` 重新计算所有大纲锚点
2. **图谱级联标记**（依赖锚点重算成功）：将 `last_updated >= from_chapter` 的知识图谱节点标记为 `cascade_pending=True`，生成级联影响报告
3. **RAG 索引重建**（依赖锚点重算成功）：调用 `plot_rag_retriever.py build` 全量重建检索索引

**脚本执行**：
```bash
python3 scripts/novel_flow_executor.py revise-outline \
  --project-root <项目目录> \
  --from-chapter <起始章节号> \
  --change-description "<本次改纲的简要说明>" \
  [--emit-json]
```

**成功判定**：`ok = anchors_recalculated AND report_written`

**产物**：
- `.flow/backup_anchors_<时间戳>.json`：改纲前的锚点备份
- `00_memory/outline_anchors.json`：重算后的新锚点
- `00_memory/revise_outline_report.md`：本次改纲影响范围报告

**改纲后续操作**：检查报告确认级联节点无误 → 对 `cascade_pending=True` 的节点做人工审核或自动修正 → 执行 `/继续写` 恢复正常写作流程
