# Novel-Base 集成测试报告

> 测试日期：2026-05-09
> 测试者：Hermes Agent + Claude Code

## 测试概况

- 测试小说：《最后一个知情者》（都市悬疑，40章，114,445字）
- ECC 回归测试：10/10 通过
- 脚本覆盖率：12/17（70.6%）
- Claude Code 审计评分：7.0/10

## 已修复 Issues（commit 0b252ef + 7d3e1a0）

| Issue | 文件 | 改动 |
|-------|------|------|
| #1 门禁产物预生成 | chapter_gate_check.py | `--auto-create-missing` 参数 |
| #4 RAG 查询精度 | plot_rag_retriever.py | `--min-score` + BM25 fallback |
| #5 大纲动态计算 | novel_flow_executor.py | VOL1_END 动态化 + `//2500` |
| #6 CLI 标准化 | style_fingerprint.py + anti_resolution_guard.py | 子命令化 + `--chapter int` |
| #7 AI 词表扩展 | novel_flow_executor.py | +微微, 深吸一口气 |
| #9 真相系统集成 | novel_flow_executor.py | observer prompt 自动生成 |
| #10 图谱反馈 | novel_flow_executor.py | graph_update_count + dry-run |

## 未修复 Issues

| Issue | 优先级 | 原因 |
|-------|--------|------|
| #2 跨章一致性检查 | P3 | 需新建脚本 cross_chapter_consistency.py（5h+） |
| #8 CJK 字数统计 | P0 | count_chars 已导入但未使用；改用 CJK 计数会导致 3 个测试失败（template 生成器需同步修改） |

## 关键发现

### --draft-provider template 生成器质量差
模板生成的内容零故事信息，纯占位符。实际使用必须手动写或用 AI 生成。

### 章节计算公式修正
原公式 `target_words // 3500` 基于错误假设。根据番茄巅峰榜真实数据，章均应为 2500 字：
```python
target_chapters = max(10, target_words // 2500)
```

### VOL1_END 硬编码问题
原代码将 VOL1_END 硬编码为 "120"，已改为基于 target_words 动态计算。

### CLI 参数不统一
不同脚本的 CLI 参数风格不一致（有些用 `--chapter 10`，有些用 `--chapter ch010`）。已标准化为 `--chapter` 接受整数。
