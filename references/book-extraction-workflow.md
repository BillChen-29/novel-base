# 文献提取入库工作流

从 PDF/EPUB 书籍中提取母题、角色原型、意象等，填充到 novel-creator 通用层数据库。

## 触发条件

用户提供书籍文件（PDF/EPUB），要求提取内容填充到 motif_library / character_archetypes 等。

## 流程

### Step 0：研究书籍结构

对不熟悉的书，先上网搜索：
- 章节结构、核心概念
- 与其他书的重叠部分
- 最有价值的提取目标

### Step 1：文本提取

| 格式 | 工具 | 命令 |
|------|------|------|
| EPUB | markitdown | `markitdown file.epub -o /tmp/output.md` |
| 文本PDF | markitdown | `markitdown file.pdf -o /tmp/output.md`（需 `uv tool install markitdown --force --with "markitdown[pdf]"`）|
| 扫描PDF | macOS Vision OCR | `~/.hermes/hermes-agent/venv/bin/python3 /tmp/ocr_pdf.py file.pdf --start N --end M -o /tmp/output.md` |

**质量判断**：
- markitdown 输出 > 100 bytes 且可读 → 使用
- markitdown 输出 0 bytes 或乱码 → 回退到 OCR
- OCR 脚本在 `/tmp/ocr_pdf.py`（可能需要重建，macOS 重启清 /tmp）

### Step 2：确定提取目标

- 先检查现有库（`qmd query` 或 `ls`），避免重复
- 每本书提取 15-30 个母题/原型
- 关注跨文化可复用的叙事模式，而非单个故事

### Step 3：并行提取

使用 `delegate_task` 启动子代理，每本书一个子代理。最多 3 个并发。
超时设置：扫描 PDF 大书（500+ 页）可能需要 600s+。

### Step 4：去重合并

提取完成后：
1. `qmd update && qmd embed` 更新索引
2. `qmd query` 检查相似条目
3. 合并真正的重复（保留内容更丰富的版本）

### Step 5：汇总报告

向用户报告：每本书提取了多少、覆盖了哪些类别、有哪些遗漏。

## 母题文件格式

```markdown
# 母题：名称 (English Name)

## 一句话定义
一句话描述核心叙事模式。

## 叙事结构模板
1. **第一步**：...
2. **第二步**：...
...

## 承载的常见命题
- 命题1
- 命题2

## 可搭配的意象池
- 意象1（象征意义）
- 意象2（象征意义）

## 常见情境原型
- **变体名**：具体情境描述（来源）
- **变体名**：具体情境描述（来源）

## 经典案例
- **《作品名》**：简要说明

## 不适用场景
- 场景1
- 场景2
```

## 角色原型文件格式

```markdown
# 原型名

> 一句话概括

---

## 1. 变体名式 — 特征标签

**一句话描述**：...

**核心特质**：
- 特质1
- 特质2

**性格弱点**：
- 弱点1

**经典动机**：...

**常见职业/身份映射**：...

**对话/行为标志**：
- 标志1

**与其他原型的化学反应**：
- × 原型A：关系描述

**参考来源**：...

**适用场景**：...
```

## Pitfalls

### markitdown 缺 PDF 依赖
`markitdown` 默认不含 PDF 支持。报 `MissingDependencyException` 时：
```bash
uv tool install markitdown --force --with "markitdown[pdf]"
```

### OCR 脚本路径
`/tmp/ocr_pdf.py` 在 macOS 重启后丢失。需要时重建，参考本文件 Step 1 的 OCR 命令。

### QMD collection 路径 bug
`qmd collection add <name> <path>` 会忽略 path 参数，创建到 `~/<name>`。
修复：直接编辑 SQLite：
```bash
sqlite3 ~/.cache/qmd/index.sqlite "UPDATE store_collections SET path='<correct_path>' WHERE name='<collection_name>';"
```

### 子代理并发限制
`delegate_task` 最多 3 个并发任务。超过会报错。分批启动。

### 扫描 PDF 页码偏移
PDF 物理页码 ≠ 书籍逻辑页码（前言、目录占页）。先 OCR 前 15-20 页找到目录，确定偏移量。

### 去重不能只看文件名
语义相似但文件名不同的条目需要 QMD 搜索才能发现。每次批量提取后必须 `qmd update && qmd embed`。
