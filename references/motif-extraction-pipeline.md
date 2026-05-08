# Motif Library Extraction Pipeline

从参考书籍（PDF/EPUB）批量提取母题到 `assets/motif_library/` 的完整流程。

## 触发条件

用户说"提取母题""填充母题库""从这本书里提取"等。

## 流程

### Step 0: 文件探测

```bash
ls -lh /path/to/books/
```

判断文件类型：
- **EPUB/markitdown 可处理**：直接用 `markitdown` 转为临时 Markdown
- **扫描版 PDF**：需要 OCR（macOS Vision 框架）

### Step 1: markitdown 转换（EPUB/文本 PDF）

```bash
markitdown file.epub -o /tmp/extracted.md
wc -c /tmp/extracted.md
head -80 /tmp/extracted.md
```

质量判断：
- \> 100 bytes 且可读 → 使用
- ≤ 100 bytes 或乱码 → 回退到 OCR

**Pitfall:** markitdown 默认不支持 PDF，需安装 `markitdown[pdf]`：
```bash
uv tool install markitdown --force --with "markitdown[pdf]"
```

### Step 2: OCR 扫描版 PDF

OCR 脚本：`/tmp/ocr_pdf.py`（macOS Vision 框架）

```bash
# 测试前几页
~/.hermes/hermes-agent/venv/bin/python3 /tmp/ocr_pdf.py \
  "path/to/book.pdf" --start 1 --end 15 -o /tmp/test_ocr.md

# 批量提取（每批 30-50 页）
~/.hermes/hermes-agent/venv/bin/python3 /tmp/ocr_pdf.py \
  "path/to/book.pdf" --start 30 --end 60 -o /tmp/chunk_30_60.md
```

**OCR 质量：**
- 中文识别质量好（macOS Vision 原生支持）
- 英文识别质量尚可（偶有拼写错误）
- JBIG2 stream 错误可忽略（非致命）

**大文件策略：**
- 先 OCR 目录页（前 10-20 页）确定章节结构
- 再按章节/批次 OCR 正文
- 每批 30-50 页，避免内存问题

### Step 3: 提取母题

从 OCR/转换文本中识别母题，每个母题写成独立 `.md` 文件。

**格式模板**（参考 `homeward.md`）：

```markdown
# 母题：[中文名] ([English Name])

## 一句话定义
[一句话描述这个母题的核心叙事模式]

## 叙事结构模板
1. **[阶段1]**：...
2. **[阶段2]**：...
3. **[阶段3]**：...
4. **[阶段4]**：...
5. **[阶段5]**：...

## 承载的常见命题
- [命题1]
- [命题2]

## 可搭配的意象池
- [意象1]（[象征意义]）
- [意象2]（[象征意义]）

## 常见情境原型
- **[原型名]**：[描述]（[来源]）

## 经典案例
- **《[作品名]》**（[文化]）：[简述]

## 不适用场景
- [场景1]
- [场景2]
```

**命名规则：** 英文小写加连字符，如 `brothers-betrayal.md`、`shape-shifting-escape.md`

**提取重点：**
- 母题（可复用的叙事模式）> 人物原型 > 意象
- 跨文化的可复用模式，不是单个故事的复述
- 每个母题应有 5+ 个经典案例来自不同文化

### Step 4: QMD 索引更新

```bash
qmd update -c motif-library
qmd embed -c motif-library
```

**Pitfall:** `qmd collection add` 有路径 bug——路径参数被忽略，collection 默认创建在 `~/` 下。修复方法：直接改 SQLite：
```bash
sqlite3 ~/.cache/qmd/index.sqlite \
  "UPDATE store_collections SET path='/实际路径' WHERE name='collection-name';"
qmd update && qmd embed
```

### Step 5: 去重合并

用 QMD 检索相似条目：

```bash
qmd query "洪水" -c motif-library --no-rerank -n 10
```

检查相似条目是否为真正重复：
- 同一母题的不同角度（如洪水的起因、避难、再造）→ 保留
- 同一母题的重复描述 → 合并

## 并行提取策略

当有多本书需要提取时，使用 `delegate_task` 并行处理：

```
批次1（最多3个并发）：书A、书B、书C
批次2：书D、书E、补完批次1中被截断的任务
```

每本书分配一个子代理，子代理负责：
1. OCR/转换该书
2. 提取母题
3. 写入 motif_library

**Pitfall:** 子代理有工具调用次数限制（~50次），大书可能需要分批。

## 已验证的提取结果

| 来源 | 提取数量 | 覆盖范围 |
|------|---------|---------|
| 外国神话史诗民间故事鉴赏辞典 (EPUB) | 18 | 东方+西方民间故事 |
| 中国神话母题索引 (764页扫描PDF) | 25 | Thompson A-Z 体系 |
| 神祗与英雄 (304页扫描PDF) | 19 | 第2-11章 |
| Indo-European Folk-Tales (176页英文扫描PDF) | 19 | 全书7章 |
| 钟敬文文选 (540页扫描PDF) | 15 | 中国民间故事型式 |
| 千面英雄 (坎贝尔) (EPUB) | 14 | 英雄之旅框架、角色原型 |
| 中国民间故事类型 (艾伯华) (扫描PDF) | 21 | 246种中国故事型式 |
| 金枝 (弗雷泽) (EPUB) | 14 | 巫术、神圣王、替罪羊、植神 |
