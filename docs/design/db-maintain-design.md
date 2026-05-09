# db-maintain 数据库维护命令设计

> 目标：让 clone 仓库的人无需手动编辑文件，通过交互式 CLI 命令管理 novel-base 的数据资产。

## 子命令列表

```
python3 novel_flow_executor.py db-maintain <子功能>
```

| 子功能 | 说明 |
|--------|------|
| `ingest <file> --type web_novel` | 投喂故事 → 自动分析 → 生成平台模板 |
| `ingest <file> --type motif/character/technique/style` | 投喂故事 → 提取母题/角色/技法/风格 |
| `add-platform --name xxx --avg-chars 2500 ...` | 手动添加平台预设 |
| `list-platforms` | 列出所有平台预设 |
| `add-motif/add-character/add-technique/add-style` | 手动添加资产条目 |
| `list-assets` | 列出 assets 各子库统计 |
| `import-batch <dir>` | 批量导入目录 |
| `validate` | 校验 assets 格式 |
| `export` | 导出数据汇总 |

## 投喂流程（核心）

```
db-maintain ingest 故事.txt --type web_novel
    ↓
自动分析：章均字数、对话占比、标点密度、段落长度、人称、钩子率
    ↓
推导平台模板参数（derive_platform_from_analysis）
    ↓
保存到 runtime-data/platforms/<book_name>.json
    ↓
用户确认后注册为正式平台预设
```

## 投喂分析算法

```python
def derive_platform_from_analysis(pacing, style, book_title):
    avg_wc = round(pacing['avg_wc'] / 500) * 500
    min_chars = int(avg_wc * 0.90)
    avg_para_len = style['avg_para_len'] if style['avg_para_len'] > 0 else 100
    min_paragraphs = max(5, int(avg_wc / avg_para_len * 0.8))
    dr = style['dialogue_ratio'] / 100
    min_dialogue_ratio = max(0.03, round(dr - 0.15, 2))
    max_dialogue_ratio = min(0.80, round(dr + 0.15, 2))
    avg_sent_len = style['avg_sentence_len'] if style['avg_sentence_len'] > 0 else 20
    min_sentences = max(5, int(avg_wc / avg_sent_len * 0.8))
    hook_rate = pacing.get('hook_rate', 0.2)
    beat_count = 5 if hook_rate >= 0.3 else (4 if hook_rate >= 0.15 else 3)
    mode = pacing.get('mode', 'B')
    pacing_mode_map = {'A': 'immersive', 'B': 'standard', 'C': 'standard', 'D': 'fast'}
    pacing_mode = pacing_mode_map.get(mode, 'standard')
    pov = style.get('pov', '')
    narrative_voice = 'first_person' if '第一' in pov else 'third_person'
    style_perspective = pov or '第三人称有限'
    return {
        "avg_chars_per_chapter": avg_wc,
        "default_min_chars": min_chars,
        "default_min_paragraphs": min_paragraphs,
        "default_min_dialogue_ratio": min_dialogue_ratio,
        "default_max_dialogue_ratio": max_dialogue_ratio,
        "default_min_sentences": min_sentences,
        "default_beat_count": beat_count,
        "pacing_mode": pacing_mode,
        "narrative_voice": narrative_voice,
        "style_perspective": style_perspective,
    }
```

## 复用的现有能力

- `novel_ingest.py` — 节奏分析、风格分析、母题/角色/技法提取
- `style_fingerprint.py` — 风格指标提取
- `common.py` — 路径解析、文件读写

## 数据存储

```
runtime-data/                        # .gitignored，db-maintain 管理
├── platforms/                       # 用户自定义平台预设
│   ├── fanqie.json
│   ├── zhihu.json
│   └── my_platform.json
├── custom/                          # 用户手动添加的资产
├── llm_queue/                       # 待 LLM 处理的提取任务
├── ingest_log.json                  # 投喂操作日志
└── import_batch/                    # 批量导入临时存放
```
