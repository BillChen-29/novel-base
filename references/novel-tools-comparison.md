# AI 小说创作工具对比

## 1. leenbj/novel-creator-skill ⭐ 250

**仓库**: https://github.com/leenbj/novel-creator-skill
**状态**: 生产级
**兼容**: Claude Code, Codex, OpenCode, Gemini CLI

### 核心功能
- 百万字级长篇（300万字+），每章约 3500 字
- 知识图谱：人物、地点、势力、伏笔、事件、关系网，每章自动更新
- RAG 检索：BM25 TF-IDF + 语义重排序，写前自动检索相关上下文
- 5 步质量门禁：记忆同步→一致性→风格→校对→门禁检查
- 反 AI 味：7 类 AI 写作痕迹检测，两轮编辑消除
- 风格库：支持多风格模板，自动匹配
- 多模型：GPT-4、Claude、Kimi 2.5、GLM-5、本地模型

### 命令
- `/一键开书` — 初始化项目
- `/继续写` — 带完整流程续写
- `/修复本章` — 门禁失败后自动修复
- `/写全篇` — 从模糊想法到路线图
- `/批量写作` — 批量生成多章
- `/仿写` — 从样章提取风格并仿写
- `/风格提取` / `/风格校准` / `/风格迁移`
- `/门禁检查` / `/检查一致性` / `/剧情检索`

### 项目结构
- `00_memory/` — 记忆层（plan, state, character_tracker, style_anchor, retrieval 等）
- `02_knowledge_base/` — 世界观设定
- `03_manuscript/` — 章节正文
- `04_editing/` — 质量门禁报告
- `assets/style_library/` — 风格库
- `.flow/` — 执行状态和快照

### 局限
- 非原生 Hermes skill（面向 Claude Code 等）
- 配置较重，需理解其文件结构
- 每章 3500 字，番茄小说需调整为 2000-3000 字

---

## 2. zz465213/ai-novel-creator ⭐ 1

**仓库**: https://github.com/zz465213/ai-novel-creator
**状态**: 早期
**兼容**: Claude Code, Gemini CLI, Cursor（非 Hermes）

### 核心功能
- 三层上下文结构：写作标准→小说项目→手稿场景
- 风格分析：导入已有稿件自动检测写作风格
- 场景拆分：按场景粒度拆分写作任务
- Token 节省：lite 版文档减少上下文消耗
- 自动进度追踪

### 命令
- `/plan-novel` — 初始化小说项目
- `/analyze-manuscript` — 导入分析已有稿件
- `/create-outline` — 生成大纲、角色、世界观、场景任务
- `/write-scenes` — 按场景写作

### 局限
- 仅 1 star，6 commits，极早期
- 无知识图谱、无 RAG、无质量门禁、无反 AI 味检测
- 功能单薄，不如 novel-creator-skill 完善

---

## 对比总结

| 维度 | novel-creator-skill | ai-novel-creator |
|------|---------------------|-------------------|
| 成熟度 | 生产级 ⭐250 | 早期 ⭐1 |
| 知识图谱 | ✅ 自动维护 | ❌ |
| RAG 检索 | ✅ BM25 + 语义 | ❌ |
| 质量门禁 | ✅ 5 步检查 | ❌ |
| 反 AI 味 | ✅ 7 类检测 | ❌ |
| 风格管理 | ✅ 多风格库 | 基础 |
| 复杂度 | 重 | 轻 |

**推荐**: novel-creator-skill 功能完善，但需要适配番茄小说的章节长度和节奏要求。
