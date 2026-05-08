# CHANGELOG

## v1.2.0 (2026-05-08)

### 仓库改造：统一名称 + 数据清理

**Phase A: 合并 novel-writing** (commit ba44a03)
- 合并 novel-writing/SKILL.md 的 Hermes 专用段落到 SKILL.md
- 新增段落：仓库与名称关系、探针结果、plan-iteration 工作流、番茄平台写作规范、跨库反向提取模式、节奏模板扩充工作流
- 复制 cross-ai-handoff-report.md 到 references/
- 统一 SKILL.md frontmatter name: novel-claude-ai → novel-base
- 版本 v1.1.0 → v1.2.0

**Phase B: 数据清理** (commit 4d1ae5b)
- novel-creator.json id: novel-claude-ai → novel-base
- CLAUDE.md v8.0 → v1.2.0
- .gitignore 追加数据层规则（assets/, 00_memory/, 02_knowledge_base/, 03_manuscript/, 04_editing/, projects/, .flow/）
- git rm --cached 移除 309 个数据文件（本地保留）
- 推送到 GitHub BillChen-29/novel-base

**Phase B Step 6: 清理 novel-writing**
- 更新 web-novel-publishing 的 related_skills 引用: novel-writing → novel-base
- 备份到 /tmp/novel-writing-backup
- 删除 ~/.hermes/skills/creative/novel-writing/

### 操作记录

| 时间 | 操作 | 结果 |
|------|------|------|
| 2026-05-08 23:30 | Phase A: 合并 novel-writing SKILL.md | commit ba44a03, 889 行 |
| 2026-05-08 23:35 | Phase B: 更新配置文件 | novel-creator.json + CLAUDE.md |
| 2026-05-08 23:36 | Phase B: 更新 .gitignore | 追加 17 行数据层规则 |
| 2026-05-08 23:37 | Phase B: git rm --cached | 309 files, 19343 deletions |
| 2026-05-08 23:38 | Phase B: commit + push | commit 4d1ae5b, push 成功 |
| 2026-05-08 23:39 | Step 6: 更新 web-novel-publishing 引用 | novel-writing → novel-base |
| 2026-05-08 23:40 | Step 6: 备份并删除 novel-writing | /tmp/novel-writing-backup |
| 2026-05-08 23:41 | ECC 审查 | code-reviewer agent |

### 验证结果

- [x] SKILL.md name: novel-base
- [x] novel-creator.json id: novel-base
- [x] 版本统一 v1.2.0
- [x] git ls-files 无数据文件
- [x] GitHub 推送成功
- [x] novel-writing 已删除，备份已创建
