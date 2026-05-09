# 数据/代码分离架构 — 最终方案

> 日期: 2026-05-09
> 基于多轮讨论 + Round 1 审查修正

## 三层架构

```
novel-base/                          # GitHub 仓库根目录
│
│  ════════════════════════════════════════════════════════
│  代码层 — 提交到 GitHub（代码 + 文档 + 模板）
│  ════════════════════════════════════════════════════════
│
├── SKILL.md, CLAUDE.md, .gitignore
├── scripts/                         # Python 脚本（全部代码）
├── templates/                       # 项目初始化模板（代码层）
├── references/                      # A 类设计文档（文档层）
│
│  ════════════════════════════════════════════════════════
│  数据层 — .gitignore 忽略，本地维护
│  物理位置：~/.hermes/skills/creative/novel-base/assets/
│  代码通过 SKILL_ROOT 相对路径加载，无需额外配置。
│  ════════════════════════════════════════════════════════
│
├── assets/                          # 通用知识库（.gitignored）
│   ├── motif_library/               # 178 个母题
│   ├── character_archetypes/        # 45 个角色原型
│   ├── technique_library/           # 26 个写作技法
│   ├── style_library/               # 11 个风格参考
│   ├── pacing/                      # ★ 通用节奏理论（不按平台分）
│   └── platforms/                   # ★ 平台预设（数据驱动）
│       ├── fanqie/config.json
│       └── zhihu/config.json
│
├── runtime-data/                    # .gitignored，db-maintain 管理
│   ├── platforms/                   # 用户自定义平台预设
│   ├── custom/                      # 用户手动添加的资产
│   ├── llm_queue/                   # 待 LLM 处理的提取任务
│   └── ingest_log.json              # 投喂操作日志
```

## 关键修正

| 原方案 | 修正后 |
|--------|--------|
| pacing_template 移到 platforms/ | → assets/pacing/（通用理论，平台无关） |
| PLATFORM_PRESETS 硬编码 | → config.json 数据驱动（三层加载） |
| novel_ingest.py 硬编码路径 | → SKILL_ROOT 动态推算 |
| references/ 归属不明 | → A 类留 GitHub，B 类分流 |

## config.json Schema

```json
{
  "platform": "fanqie",
  "avg_chars_per_chapter": 2500,
  "default_min_chars": 2500,
  "default_min_paragraphs": 8,
  "default_min_dialogue_ratio": 0.03,
  "default_max_dialogue_ratio": 0.7,
  "default_min_sentences": 8,
  "default_beat_count": 4,
  "pacing_mode": "standard",
  "narrative_voice": "third_person",
  "style_perspective": "第三人称有限"
}
```

## 加载逻辑

```
加载优先级: runtime-data/ > assets/ > 硬编码默认值
代码路径: 所有脚本通过 SKILL_ROOT = SCRIPT_DIR.parent 推算
```

## 迁移步骤（4 Phase，5-8 天）

| Phase | 内容 | 工时 |
|-------|------|------|
| 0 | 创建目录 + config.json + 重命名 pacing_template → pacing | 2 小时 |
| 1 | 路径修复 + 数据驱动改造 | 1-2 天 |
| 2 | db-maintain 命令实现 | 2-3 天 |
| 3 | references/ 文档分流 | 1 天 |
| 4 | 高级功能（sync-index, export） | 1-2 天 |

## Pitfall

- pacing_template 里的 5 个文件是通用节奏理论，不是平台专属，不要移到 platforms/
- PLATFORM_PRESETS 改为 config.json 后，需要保持向后兼容（硬编码默认值作为 fallback）
- novel_ingest.py 的 ASSETS_DIR 硬编码路径 `~/.hermes/skills/novel-creator-skill/assets` 可能不匹配实际路径
- QMD collection 如果源文件路径变更需要重建索引
