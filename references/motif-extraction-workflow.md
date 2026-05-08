# Motif Library Extraction Workflow

Extract motifs (母题), character archetypes, and imagery from reference books into `assets/motif_library/` and `assets/character_archetypes/`.

## Source Material Types

| Type | Tool | Notes |
|------|------|-------|
| EPUB | `markitdown file.epub -o /tmp/out.md` | Works out of the box, clean text |
| Text-based PDF | `markitdown file.pdf -o /tmp/out.md` | Needs `markitdown[pdf]` dependency |
| Scanned PDF | macOS Vision OCR | markitdown returns 0 bytes or garbled text |
| Screenshots | macOS Vision OCR | pyobjc-framework-Vision in hermes venv |

## Step 0: Install markitdown PDF support

```bash
uv tool install markitdown --force --with "markitdown[pdf]"
```

Without this, PDF conversion throws `MissingDependencyException`.

## Step 1: Detect scan vs text PDF

```bash
markitdown "file.pdf" -o /tmp/test.md
wc -c /tmp/test.md
head -50 /tmp/test.md
```

| Result | Diagnosis | Action |
|--------|-----------|--------|
| > 100 bytes, readable text | Text-based PDF | Use markitdown output |
| 0 bytes | Scanned PDF | Use OCR |
| Garbled text (random chars, no structure) | Scanned PDF with OCR artifacts | Use OCR |

## Step 2A: Text extraction (markitdown)

```bash
markitdown "file.epub" -o /tmp/extract.md
# Check quality
wc -c /tmp/extract.md
head -80 /tmp/extract.md
```

## Step 2B: OCR for scanned PDFs

Use macOS Vision framework via pyobjc. Script template:

```python
import Vision, Quartz
from Foundation import NSURL

def ocr_image(image_path):
    image_url = NSURL.fileURLWithPath_(image_path)
    source = Quartz.CGImageSourceCreateWithURL(image_url, None)
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(["zh-Hans", "en-US"])
    request.setRecognitionLevel_(0)  # 0=accurate, 1=fast
    
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    handler.performRequests_error_([request], None)
    
    lines = []
    for r in request.results():
        lines.append(r.topCandidates_(1)[0].string())
    return "\n".join(lines)
```

For PDFs: convert pages to images first with `pdftoppm` or `sips`, then OCR each page.

**Pitfall:** Large PDFs (20MB+) need chunking. Process in document order, split into ~50-page batches.

## Step 3: Identify motifs from extracted text

Look for:
- **母题 (motifs)**: Cross-cultural narrative patterns (归乡, 兄弟反目, 变形逃亡...)
- **人物原型 (archetypes)**: Recurring character roles (英雄, 导师, 变形者...)
- **意象 (imagery)**: Sensory carriers of motifs (河流, 旧宅, 动物变形...)

Source books often label these explicitly: "情境母题", "故事类型", "型式".

## Step 4: Format as motif_library entry

Template (7 sections, see `templates/motif-template.md`):

```markdown
# 母题：[中文名] ([English Name])

## 一句话定义
[One sentence: what this motif is about]

## 叙事结构模板
[5-6 step narrative arc]

## 承载的常见命题
[Thematic implications, 4-6 bullets]

## 可搭配的意象池
[Sensory images, 6-8 items]

## 常见情境原型
[5 situation archetypes with examples]

## 经典案例
[5-6 cross-cultural examples]

## 不适用场景
[When NOT to use this motif, 3-4 bullets]
```

## Step 5: Write to assets directory

```bash
# Motifs
~/.hermes/skills/novel-creator-skill/assets/motif_library/[kebab-case-name].md

# Character archetypes
~/.hermes/skills/novel-creator-skill/assets/character_archetypes/[kebab-case-name].md
```

## Step 6: QMD deduplication

After batch extraction, use QMD to detect similar/overlapping entries:

```bash
qmd query "兄弟 反目 背叛" -c motif-library -n 5
qmd query "变形 逃亡" -c motif-library -n 5
```

Merge entries that cover the same narrative pattern with different names.

**Pitfall:** QMD collection for motif-library may need manual path fix. See "QMD Collection Setup" below.

## QMD Collection Setup

```bash
# Add collection (may silently use wrong path)
qmd collection add motif-library "/path/to/motif_library"

# Verify path
qmd collection show motif-library

# If path is wrong, fix in SQLite:
sqlite3 ~/.cache/qmd/index.sqlite \
  "UPDATE store_collections SET path='/Users/chenzefeng/.hermes/skills/novel-creator-skill/assets/motif_library' WHERE name='motif-library';"

# Re-index and embed
qmd update
qmd embed
```

**Pitfall:** `qmd collection add <name> <path>` silently ignores the path argument and stores `~/<name>` as the default path. Always verify with `qmd collection show` and fix via SQLite if needed.

## Parallel Extraction with Subagents

For multiple source books, launch parallel subagents:
- Each subagent handles one book
- Shared context: target format template + output directory
- For scanned PDFs: process in document order, split into chunks
- After all subagents complete: run QMD dedup pass

## Current Source Books (比较文学-故事类型-图书)

| Book | Format | Method | Target Sections |
|------|--------|--------|-----------------|
| 中国神话母题索引 (杨利慧) | Scanned PDF | OCR | 凡例 + 母题条目 |
| 神祗与英雄 (陈建宪) | Scanned PDF | OCR | 二到十一章 |
| Indo-European Folk-Tales (Halliday) | Scanned PDF | OCR | 全文自解析 |
| 钟敬文文选 | Scanned PDF | OCR | 中国民间故事型式小节 |
| 印欧民间故事型式表 | — | SKIP | 过于模糊 |
| 外国神话史诗民间故事鉴赏辞典 | EPUB | markitdown | 东方+西方民间故事部分 |
