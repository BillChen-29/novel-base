# 集成测试结果（2026-05-09）

> 从 SKILL.md 移出的集成测试记录。

## 集成测试发现（2026-05-09）

> 40章/114k字完整测试验证，以下为实测发现的脚本问题。

### P0 阻断性问题

| # | 脚本 | 问题 | 状态 |
|---|------|------|------|
| 1 | chapter_gate_check.py | 单独调用时6个产物文件必须预存在，否则报"文件不存在"。需 `--auto-create-missing` | 待修复 |
| 2 | 无对应脚本 | 跨章节一致性检查缺失（角色性别漂移、设定规则违反无法检测） | 待新建 |

### P1 功能问题

| # | 脚本 | 问题 | 状态 |
|---|------|------|------|
| 3 | novel_flow_executor.py | `generate_draft_text()` 模板模式生成通用填充，不读 novel_plan/character_tracker | 待修复 |
| 4 | plot_rag_retriever.py | `query()` 索引构建成功但查询返回0（触发条件+评分阈值双重问题） | 待修复 |
| 5 | novel_flow_executor.py | `init_project_files()` 硬编码 VOL1_END=120，忽略 target_words。公式应为 `target_words // 2500`（番茄巅峰榜基准） | 待修复 |

### P2 代码质量

| # | 脚本 | 问题 | 状态 |
|---|------|------|------|
| 6 | 多个脚本 | CLI参数不统一（style_fingerprint 用位置参数，anti_resolution 用 --chapter-file，其余用 --chapter） | 待统一 |
| 7 | novel_flow_executor.py | `AI_PHRASE_BLACKLIST` 漏检"微微""深吸一口气" | 待补充 |
| 8 | common.py | `evaluate_quality()` 未调用 `count_chars()`，直接 `len(re.sub(...))` 含标点 | 待修复 |

### P3 流水线完善

| # | 脚本 | 问题 | 状态 |
|---|------|------|------|
| 9 | novel_flow_executor.py | chapter_observer/reflector 未集成到 continue-write 流程 | 待集成 |
| 10 | novel_flow_executor.py | `--auto-graph-update` 实际默认 True（非 False），缺 dry-run 和计数反馈 | 待增强 |

### 关键 Pitfall

- **大纲计算公式**：`target_words // 3500` 错误，应为 `// 2500`（番茄巅峰榜章均字数）。推荐榜 2355，新书榜 2610，巅峰榜 2516
- **图谱自动更新**：`--auto-graph-update` 默认是 True（开启），不是 False。v1 分析曾误判
- **RAG 双重零结果路径**：(A) `analyze_query_trigger()` 关键词未命中时跳过检索 (B) `retrieve()` 的 `> 0` 阈值过滤掉所有无交集结果
- **字数统计陷阱**：`count_chars(cjk_only)` 函数存在但 `evaluate_quality()` 没调用它，用的是 `len(re.sub(r"\s+","",body))`（含标点+英文）
- **Claude Code ACP 调用**：`claude --acp --stdio` 在 CLI 2.1.119 不支持，`delegate_task` 的 `acp_command` 参数无效

### 完整修复方案

详见 `<project-root>/project_plan_final.md`

---

## 集成测试结果（2026-05-09）

通过 40 章小说全流程测试，12/17 脚本验证通过。关键修复已推送到 GitHub。
详见 `references/integration-test-findings-2026-05.md`。

**已修复的问题**：
- 门禁产物预生成（`--auto-create-missing`）
- 大纲卷计算动态化（基于 target_words / 2500）
- RAG 查询精度（`--min-score` + BM25 回退）
- CLI 标准化（style_fingerprint 子命令化, anti_resolution_guard `--chapter` int）
- AI 词表扩展（微微、深吸一口气等）
- 真相系统集成（observer prompt 自动生成）
- 图谱更新反馈（graph_update_count + dry-run）
- 门禁占位文件检测（quality_report 为占位时跳过）— 2026-05-09
- anti_resolution_guard 参数修复（chapter=整数）— 2026-05-09
- stub 文件自动清理（continue_write 写入后删除"待写"文件）— 2026-05-09
- 字数截断逻辑（LLM 生成超标时在句号处截断）— 2026-05-09

**已知遗留**：
- template 模式内容质量差（通用模板，不读 novel_plan.md）
- 跨章节一致性检查缺失（需新建脚本）
- CJK 字数统计与 template 生成器不兼容（count_chars 已导入未启用）
