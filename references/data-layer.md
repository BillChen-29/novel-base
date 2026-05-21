# 数据层架构

> 从 SKILL.md 移出的详细数据层文档。

## 数据层架构（V3 — 项目配置优先）

**核心原则**：数据与代码分离，GitHub 是中间层。项目配置 > 平台预设 > 硬编码默认值。

**V3 关键变更**（2026-05-09）：
- `--platform` 变为可选（default=None），新增 `standalone` 选项
- 项目级配置 `00_memory/platform_config.json` 作为最高优先级
- 独立小说不需要套用任何平台模板
- null 值语义：字段为 null 时回退到平台预设/默认值（支持部分覆盖）
- PLATFORM_PRESETS 从硬编码改为 config.json 数据驱动（assets/platforms/*/config.json）
- db-maintain 命令已实现（list-assets, list-platforms, add-platform, validate, ingest）
- 门禁占位文件检测（quality_report 为占位时跳过）
- anti_resolution_guard 参数修复（chapter=整数）
- stub 文件自动清理（写入实际章节后删除"待写"文件）
- 字数截断逻辑（LLM 生成超标时在句号处截断）
- 详见 `references/architecture-v3.md` + `docs/v3-refactoring-report.md`

```
GitHub (代码 + 设计文档)
├── scripts/           57 个 .py
├── templates/         20 个模板
├── references/        34 个 A 类设计文档
└── .gitignore         排除 runtime-data/, assets/, zhihu-*.md

Hermes Skill 目录 (运行时)
├── [git pull] ← GitHub 代码 + 设计文档
├── assets/            267 个通用层资产 (本地-only)
└── runtime-data/      平台模板 + 自定义数据 (本地-only)

Project 目录 (Claude Code 工作区)
└── [git clone] ← GitHub (无数据)
```

**文件分类标准**：
- **A 类（代码/设计文档）**：描述"系统如何工作" → 留在 GitHub
- **B 类（运行时数据）**：描述"创作内容是什么" → 本地-only

**B 类文件清单**（8 个）：
- `references/genre-style-matrix.md` — 题材矩阵
- `references/novel-pacing-analysis.md` — 节奏基准
- 6 个测试/审计报告（时间敏感）

### db-maintain 命令（已实现）

```bash
python3 novel_flow_executor.py db-maintain <子功能>
├── list-assets          # 列出 assets 各子库统计
├── list-platforms       # 列出所有平台预设
├── add-platform         # 手动添加平台预设
├── validate             # 校验 assets 格式
└── ingest               # 投喂故事文件
```

**投喂流程**：用户提供故事文件 → 自动分析（章均字数、对话占比、标点密度、段落长度、人称、钩子率）→ 推导平台模板参数 → 保存到 runtime-data/platforms/

详见 `/tmp/db_maintain_design.md`（设计文档）。

---

## 自动化分析脚本

| 脚本 | 功能 |
|------|------|

集成测试报告见 `references/integration-test-report-2026-05-09.md`。

关键遗留问题：
- `--draft-provider template` 生成器质量差（零故事信息，纯占位符）
- #2 跨章一致性检查需新建脚本（5h+）
- #8 CJK 字数统计：count_chars 已导入但未启用（与 template 生成器不兼容）
- stub 文件清理：仅在 continue_write() 中触发，Claude Code 直接写入时不会自动清理

## 使用方法

### 快速初始化
```bash
python3 scripts/one-click_novel_flow.py --title "小说标题" --genre "题材" --target-words 1000000
```
类型：`web_novel` / `motif` / `character` / `technique` / `style`

详细用法见 `references/novel-ingest-pipeline.md`
