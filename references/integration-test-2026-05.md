# Novel-Base 集成测试报告 (2026-05-09)

## 测试环境
- macOS, Python 3.11.15 (Hermes venv)
- novel-base v1.2.0, ECC 10/10 通过
- 测试小说：《最后一个知情者》（都市悬疑，40章，114k字符）

## 脚本测试结果（12/17 通过）

| 脚本 | 命令 | 结果 |
|------|------|------|
| novel_flow_executor.py | one-click | ✅ |
| novel_flow_executor.py | continue-write | ✅ (template模式) |
| chapter_gate_check.py | 直接调用 | ✅ (需--auto-create-missing) |
| plot_rag_retriever.py | build | ✅ (42章索引) |
| plot_rag_retriever.py | query | ✅ (需--min-score调整) |
| story_graph_builder.py | validate | ✅ |
| outline_anchor_manager.py | advance | ✅ |
| anti_resolution_guard.py | check | ✅ |
| event_matrix_scheduler.py | init/recommend | ✅ |
| cross_agent_reviewer.py | review | ✅ |
| style_fingerprint.py | extract | ✅ |
| benchmark_novel_flow.py | 基线评测 | ✅ (3轮, 100% ok, 612ms) |

## 性能数据

| 操作 | 耗时 |
|------|------|
| one-click 初始化 | ~6s |
| continue-write (template) | ~8s |
| RAG build (42章) | ~15s |
| benchmark (3轮) | ~612ms/轮 |

## 关键发现

1. **模板写作不可用**：`--draft-provider template` 生成通用模板，不含故事内容
2. **RAG 查询返回 0**：索引构建成功但查询空结果。根因：(a) analyze_query_trigger 条件触发跳过 (b) 评分阈值 >0 过滤了所有结果。已修复：增加默认触发(>=8字符) + min-score + BM25 fallback
3. **大纲计算硬编码**：VOL1_END=120 不随 target_words 变化。已修复：动态计算
4. **字数统计不一致**：evaluate_quality 用 len(pure)（所有非空白字符），count_chars() 存在但未被调用。已导入但未启用（需同步修改 template 生成器阈值）
5. **跨章一致性缺失**：无脚本检查角色性别漂移、设定规则违反等跨章问题

## 已修复 Issues（commit 0b252ef）
- #1 门禁产物预生成
- #4 RAG 查询精度
- #5 大纲动态计算
- #6 CLI 标准化（style_fingerprint + anti_resolution_guard）
- #7 AI 词表扩展
- #9 真相系统集成（observer prompt）
- #10 图谱更新反馈

## 待修复 Issues
- #2 跨章节一致性检查（需新建脚本，5h+）
- #8 CJK 字数统计（需同步 template 生成器）
- #3 模板写作质量（需读取 novel_plan.md 注入内容）
