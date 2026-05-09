# Novel-Base 脚本修复记录（2026-05-09）

集成测试中发现并修复的问题，已推送 Git（commit 0b252ef）。

## 已修复 Issues

### #1 门禁产物预生成（chapter_gate_check.py）
- **问题**：`chapter_gate_check` 需要预先存在的 gate artifacts，无法独立运行
- **修复**：新增 `--auto-create-missing` 参数，自动从 truth/ 目录生成缺失的 gate 产物
- **文件**：`scripts/chapter_gate_check.py`（+18行）

### #4 RAG 查询精度（plot_rag_retriever.py）
- **问题**：`rag_query` 返回 0 结果，relevance score 全为 0
- **修复**：新增 `--min-score` 参数 + BM25 fallback（当向量检索无结果时降级到关键词匹配）
- **文件**：`scripts/plot_rag_retriever.py`（+41行）

### #5 大纲动态计算（novel_flow_executor.py）
- **问题**：VOL1_END 硬编码为 "120"，章节计算用 `// 3500`（与番茄巅峰榜真实数据不符）
- **修复**：VOL1_END/VOL2_START/VOL2_END 改为基于 target_words 动态计算，公式改为 `// 2500`（番茄巅峰榜基准）
- **文件**：`scripts/novel_flow_executor.py`

### #6 CLI 标准化（style_fingerprint.py, anti_resolution_guard.py）
- **问题**：参数格式不统一（有的用 `--text`，有的用位置参数）
- **修复**：style_fingerprint 改为子命令模式，anti_resolution_guard 的 `--chapter` 改为 int 类型
- **文件**：`scripts/style_fingerprint.py`, `scripts/anti_resolution_guard.py`

### #7 AI 词表扩展（novel_flow_executor.py）
- **问题**：AI_PHRASE_BLACKLIST 缺少常见 AI 套话
- **修复**：补充"微微"、"深吸一口气"等高频 AI 用语
- **文件**：`scripts/novel_flow_executor.py`

### #9 真相系统集成（novel_flow_executor.py）
- **问题**：truth 文件存在但未被自动整合到写作 prompt
- **修复**：自动从 truth/ 目录生成 observer prompt，注入写作上下文
- **文件**：`scripts/novel_flow_executor.py`

### #10 图谱自动反馈（novel_flow_executor.py）
- **问题**：event_matrix_scheduler 的执行结果未反馈到知识图谱
- **修复**：新增 `graph_update_count` 统计 + `--dry-run` 模式
- **文件**：`scripts/novel_flow_executor.py`

## 未修复 Issues

### #2 跨章节一致性检查
- **状态**：未开始
- **方案**：新建 `cross_chapter_consistency.py`，子命令 check/snapshot
- **工时**：5h+

### #8 CJK 字数统计
- **状态**：部分完成
- **问题**：`count_chars` 已导入但 `evaluate_quality` 仍在用 `len(pure)`
- **原因**：改为 `count_chars` 后 3 个测试失败（template 生成器的 min_chars 阈值需同步调整）
- **方案**：需同时修改 template 生成器的字数目标，属于 #3 模板质量的一部分

## 关键教训

1. **`--draft-provider template` 生成的内容完全无故事信息**——模板生成器不读 novel_plan/outline，只输出通用框架。实际使用必须手动写或用 AI 生成。
2. **`chapter_gate_check` 不能独立运行**——需要预先存在的 gate artifacts。
3. **stash 陷阱**：Claude Code 子进程会 stash 改动但不自动 pop，导致改动"消失"。每次 delegate_task 后需检查 `git stash list`。
4. **字数统计不统一**：`count_chars`（CJK only）vs `len(pure)`（所有非空白字符）两种方式混用，导致测试不一致。
