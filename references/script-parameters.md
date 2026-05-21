# 脚本入口参数

> 从 SKILL.md 移出的详细脚本参数文档。

## 新增参数（2026-05-09 修复）

| 脚本 | 新增参数 | 说明 |
|------|---------|------|
| chapter_gate_check.py | `--auto-create-missing` | 自动创建缺失的门禁产物文件（占位模板） |
| plot_rag_retriever.py query | `--min-score` | 最低得分阈值（默认0.0），低于此分数的结果被过滤 |
| novel_flow_executor.py one-click | `--avg-chars-per-chapter` | 章均字数（默认2500，基于番茄巅峰榜基准） |
| novel_flow_executor.py one-click/continue-write | `--platform {fanqie,zhihu,standalone}` | 目标平台（可选，默认 None）。fanqie=番茄, zhihu=知乎盐选, standalone=独立小说。不指定时使用默认值并生成项目配置文件 |
| novel_flow_executor.py one-click | `--target-words` | 目标总字数（默认 1000000） |
| style_fingerprint.py | 子命令模式 `extract` | 从位置参数改为子命令，`--project-root` 改为 required |
| anti_resolution_guard.py | `--chapter int` | 从 `--chapter-file`（路径）改为 `--chapter`（整数） |

| 脚本 | 用途 |
|------|------|
| `python3 scripts/novel_flow_executor.py one-click` | `/一键开书` |
| `python3 scripts/novel_flow_executor.py db-maintain` | 数据库维护（list-assets, list-platforms, add-platform, validate, ingest） |
| `python3 scripts/novel_flow_executor.py continue-write --project-root <目录> --query "<新剧情>"` | `/继续写`（支持 --platform fanqie/zhihu/standalone） |
| `python3 scripts/novel_flow_executor.py revise-outline --project-root <目录> --from-chapter <N> --change-description "<说明>"` | `/改纲续写` |
| `python3 scripts/plot_rag_retriever.py build/query` | `/更新剧情索引` `/剧情检索` |
| `python3 scripts/chapter_gate_check.py` | `/门禁检查` |
| `python3 scripts/gate_repair_plan.py` | `/修复本章` |
| `python3 scripts/auto_novel_writer.py` | `/一键写书` |
| `python3 scripts/style_fingerprint.py` | `/风格提取` |
| `python3 scripts/research_agent.py` | `/联网调研` |
| `python3 scripts/benchmark_novel_flow.py` | `/评测基线` |
| `python3 scripts/story_graph_builder.py` | 知识图谱 CRUD / 校验 / Mermaid 导出 |
| `python3 scripts/outline_anchor_manager.py` | 大纲锚点初始化 / 配额检查 / 推进 |
| `python3 scripts/event_matrix_scheduler.py` | 事件矩阵冷却 / 推荐 / 记录 |
| `python3 scripts/anti_resolution_guard.py` | 反向刹车校验 / 约束 prompt 生成 |
| `python3 scripts/beat_sheet_generator.py` | Beat Sheet 生成 / 扩写提示 / 校验 |
| `python3 scripts/chapter_synthesizer.py` | 章节合成 / 合成稿质量校验 |
| `python3 scripts/cross_agent_reviewer.py` | 跨Agent审核任务生成 / 结果记录 |
| `python3 scripts/story_graph_updater.py` | 章节完成后自动提取信息更新图谱 |
| `python3 scripts/interactive_ideation_engine.py` | 交互式脑洞引导 5 轮收敛 / 产出物生成 |
| `python3 scripts/text_humanizer.py` | AI痕迹检测 / 两遍式润色 prompt 生成 |
| `python3 scripts/editorial_team_manager.py` | 编辑团队状态管理 |
| `python3 scripts/fill_config.py` | `/填充配置`（7种配置文件） |
| `python3 scripts/outline_generator.py generate/revise` | `/构思大纲` `/修订大纲` |
| `python3 scripts/self_review.py start/submit` | `/自评` |
| `python3 scripts/review_panel.py summary` | `/复盘` |
| `python3 scripts/reflection.py new` | `/反思` |
| `python3 scripts/novel_ingest.py` | `/导入数据`（统一入口，零token） |

**`continue-write` 标准用法（全功能默认开启）：**

```bash
# 标准用法：知识图谱/大纲锚点/Beat Sheet/AI痕迹纠正/风格更新均自动激活
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <项目目录> --query "<新剧情>"

# 高级用户：按需关闭部分功能
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <项目目录> --query "<新剧情>" \
  --no-beat-sheet --no-constraints --no-graph-update
```

完整参数说明见 `references/command-playbook.md`。
