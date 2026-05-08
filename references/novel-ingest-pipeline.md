# Ingest 管线与自动化脚本

## novel_ingest.py — 统一入口（v2）

路径：`novel-creator-skill/scripts/novel_ingest.py`

```bash
# 用户告诉类型，脚本执行对应分析
python3 scripts/novel_ingest.py <file> --type <类型>

# 类型选项
--type web_novel    # 网文 → pacing + 风格指标
--type motif        # 母题/神话文本 → 切分段落块供LLM提取
--type character    # 角色原型文本 → 切分段落块供LLM提取
--type technique    # 写作技巧文本 → 切分段落块供LLM提取
--type style        # 风格参考 → pacing + 风格指标

# 选项
--chapters N        # 分析前N章（默认50，仅web_novel/style）
--mid               # 同时分析100-150章（仅web_novel）
--json              # 输出JSON
--write             # 自动写入数据库（默认仅打印）
--force             # 忽略去重，强制重新处理
```

### 工作流程
```
用户标记类型 → 读取文件 → 执行对应分析 → 输出报告 → 记录manifest
```

### 五种分析路径

| 类型 | 自动执行 | 入库目标 |
|------|---------|---------|
| web_novel | pacing + 风格指标 | pacing_template/ + style_library/ |
| motif | 切分段落块(3000字/块) | motif_library/（需LLM提取） |
| character | 切分段落块 | character_archetypes/（需LLM提取） |
| technique | 切分段落块 | technique_library/（需LLM提取） |
| style | pacing + 风格指标 | style_library/ |

### 去重机制

- `assets/ingest_manifest.json` 记录已入库文件
- 同一文件+同一类型不会重复处理
- `--force` 可强制重新处理

### 节奏分析输出

网文类型自动输出：
- 章均字数、字数波动
- 钩子率、钩子类型（question/ellipsis/reversal/cliffhanger/reveal/upgrade/suspense）
- 爽点分布（upgrade/face_slap/reveal/counterattack/power_up）
- 对话比例（仅epub，智能引号 `""` 检测）
- 情绪标记（感叹号/问号/省略号密度）
- 节奏模式识别（A低钩子/B高钩子问号/C零钩子/D低对话）

### 风格指标输出

- 叙述视角（第一/第三人称）
- 情绪风格（高/中/低情绪）
- 句均长度、段均长度
- 对话比例
- 情绪密度（！/？/…每千字）

## TomatoNovelDownloader 输出格式

下载器（v2.4.9）输出TXT的特殊格式：
- 章节分隔符：`----------------------------------------`（40个短横线）
- **无对话引号**：下载器去掉了所有 `""「」`，对话比例无法分析
- 元数据在文件开头：书名/作者/book_id/评分/字数/章节/分类/标签/在读
- EPUB格式保留完整标点，对话分析必须用epub

## Pitfall

- **Python 3.9 中文变量名**：`for 变量名 in ...` 在 Python 3.9 上报 SyntaxError。所有脚本变量名必须用 ASCII 英文
- **TXT无对话引号**：TomatoNovelDownloader 输出的 TXT 去掉了所有引号，对话比例始终为零。需要对话数据必须用 EPUB
- **TXT编码**：脚本自动尝试 utf-8 → gbk → gb18030 → latin-1
- **epub依赖**：需要 ebooklib + beautifulsoup4（已装在hermes venv）
- **章节分割**：epub按文档片段+正则匹配，txt按`----`分隔符
- **中后期分析**：`--mid` 分析100-150章，需要总章数≥100

## 相关文件

- 分析脚本：`scripts/novel_ingest.py`（统一入口）
- 基准数据：`assets/pacing_template/real-data-pacing-benchmark.md`（14本分析结果）
- manifest：`assets/ingest_manifest.json`（入库记录）
- 优化计划：`.hermes/plans/novel-creator-skill-optimization.md`

## QMD 集成（已完成）

**6 个 collection 全部建立，340 文档已索引：**

| collection | 文档数 | 内容 |
|-----------|--------|------|
| wiki | 111 | Obsidian 文学知识库 |
| motif-library | 178 | 叙事母题 |
| character-archetypes | 45 | 角色原型 |
| technique-library | 16 | 写作技法 |
| pacing-template | 5 | 节奏模板 |
| style-library | 17 | 风格档案 |

**P9 已实现**：`novel_ingest.py --sync-qmd` 参数，写入后自动调 `qmd update` + `qmd embed`。

映射关系：
- motif → motif-library
- character → character-archetypes
- technique → technique-library
- style → style-library
- web_novel → pacing-template + style-library

**QMD 增量索引**：`qmd update` 支持增量检测新/改/删文件，不需要全量 rebuild。

**Pitfall**：`qmd collection add` 会忽略路径参数，创建后必须用 `qmd collection show <name>` 验证路径。如果路径不对，用 sqlite3 修复：
```bash
sqlite3 ~/.cache/qmd/index.sqlite "UPDATE store_collections SET path='正确路径' WHERE name='collection名';"
```

## 双搜索架构（P10）

**plot_rag_retriever.py**（项目级）：搜章节正文，BM25+实体重叠，Python函数调用
**QMD**（通用级）：搜通用层资产，BM25+向量+reranking，CLI subprocess调用

**统一方案**：在 `common.py` 加 `unified_search()` 薄胶水（≤80行）
- 调 plot_rag Python API 搜项目内
- 调 QMD CLI（subprocess, timeout 10s, 静默降级）搜通用层
- 返回按来源分组的 dict（不混排分数，两系统分数不可比）

**搜索时机**：
- 大纲阶段：搜 QMD（母题/原型/技法）
- 写作阶段：搜 plot_rag（前文上下文），QMD 结果复用缓存
- QMD 结果做章节级缓存，plot_rag 不缓存
