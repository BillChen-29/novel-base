---
name: novel-base
description: 中文长篇小说全流程创作技能（v1.2.0）。当用户想写小说、创作故事、续写章节、构思剧情、搭建世界观、设计人物关系、提取写作风格、仿写其他小说时，必须使用本技能。覆盖从模糊想法到300万字成品的完整链路：脑洞引导、知识图谱构建、大纲管理、分镜写作、质量门禁、跨Agent审核、风格校准、中途改纲级联更新。即使用户只是说"帮我写个故事"或"我有个小说的想法"，也应触发本技能。
version: 1.2.0
author: merged from leenbj/novel-creator-skill + custom novel-writing
license: MIT
---

# Novel Base - 小说创作技能 v1.2.0

> **合并说明：** 本技能由 `leenbj/novel-creator-skill`（v8.0，57个Python脚本）与自建 `novel-writing` skill 合并而成。通用层数据库（376个文档）、真相文件系统、番茄平台适配等均为自建扩展。后续维护独立于上游。
>
> **名称统一：** 远程仓库 `novel-base`（GitHub）、本地目录 `novel-creator-skill`（Hermes 注册路径不变）、SKILL.md `name: novel-base`。不再使用 `novel-claude-ai`。

## 用户当前状态

- **目标平台**: 番茄小说（已确认）+ 知乎盐选（2026-05-09 新增，`--platform zhihu`，待实施）
- **偏好类型**: 都市悬疑（已确认，但系统设计为通用，不绑死一个题材）
- **写作工具**: 本技能（合并后的统一技能）
- **初始化方式**: `/填充配置` 命令——用户碎片感性输入，AI 结构化填充模板
- **架构设计**: 通用创作器（通用引擎层 + 项目配置层分离），完整 plan 在 `references/architecture-plan.md`

## 仓库与名称关系

本系统涉及**一个目录、三个名称**：

| 名称 | 位置 | 角色 |
|---|---|---|
| `novel-base` | GitHub `BillChen-29/novel-base` | 远程仓库名（统一名称） |
| `novel-creator-skill` | `~/.hermes/skills/novel-creator-skill/` | 本地代码+数据目录（Hermes 注册路径，保持不变） |
| `novel-base` | SKILL.md `name:` 字段 | frontmatter 声明名 |

**已废弃名称**：`novel-claude-ai`（旧 frontmatter name）、`novel-writing`（旧 Hermes skill，已合并到本文件）。

**分工**：Claude Code 改代码 → push 到 `novel-base`（GitHub）→ Hermes `git pull` 同步。数据层（assets/、00_memory/、QMD）仅本地维护，不进 git。

## novel-creator-skill 探针结果（Phase 0 已验证）

**仓库：** 原 `leenbj/novel-creator-skill` → 已 fork 到 `BillChen-29/novel-base`
**本地目录：** `~/.hermes/skills/novel-creator-skill/`
**SKILL.md 声明名：** `novel-base`（统一后）
**环境：** Python 3.9+，零外部依赖（纯标准库），10 个回归测试全部通过

### 核心能力矩阵

| 能力 | 脚本 | 状态 |
|------|------|------|
| 一键开书 | `novel_flow_executor.py one-click` | ✅ 创建完整记忆结构 |
| 继续写作 | `novel_flow_executor.py continue-write` | ✅ 检索→写作→门禁→索引更新全链路 |
| 门禁检查 | `chapter_gate_check.py` | ✅ 6 步检查（存储→隔离→记忆→一致性→风格→校稿→发布） |
| RAG 检索 | `plot_rag_retriever.py` | ✅ 两级（BM25 粗筛 + 语义精排），零外部依赖 |
| 风格指纹 | `style_fingerprint.py` | ✅ 提取人称/句长/对话占比/用词倾向 |
| 知识图谱 | `story_graph_builder.py` | ✅ CRUD + validate + Mermaid 导出 |
| 大纲锚点 | `outline_anchor_manager.py` | ✅ init/check/advance/recalculate |
| 多 LLM 写作 | `novel_chapter_writer.py` | ✅ OpenAI/Claude/Kimi/GLM/MiniMax |
| 一键写书调度 | `auto_novel_writer.py` | ✅ 断点续写 + 进度报告 |
| 联网调研 | `research_agent.py` | ✅ 关键词生成/缺口检测/资料存储 |

### 一键开书创建的文件结构

```
<project-root>/
  00_memory/
    novel_plan.md           # 主线计划（写前必读）
    novel_state.md          # 当前状态
    character_tracker.md    # 角色状态追踪
    foreshadowing_tracker.md # 伏笔追踪
    timeline.md             # 时间线
    world_state.md          # 世界状态
    style_anchor.md         # 风格锚点（3.3KB，含人称/句长/对话占比/感官偏好）
    story_graph.json        # 知识图谱
    outline_anchors.json    # 大纲锚点
    retrieval/
      story_index.json      # RAG 索引
      entity_chapter_map.json
  02_knowledge_base/        # 设定与知识库
  03_manuscript/            # 章节正文
  04_editing/gate_artifacts/<chapter_id>/
    gate_result.json        # passed=true 才能进入下一章
```

### 需要改造的部分

| 改造项 | 说明 |
|--------|------|
| 命令适配 | Claude Code 斜杠命令 → Hermes skill 调用方式 |
| 哲学对齐 | 不存在，需新增（按需+定期触发，3 问人工反思表单） |
| 母题/意象系统 | 不存在，需新增 `motif_library/`（通用层）+ `motifs.md`（项目层） |
| 世界质感 | 不存在，需新增 `world_texture.md` |
| 角色原型库 | ✅ 已完成 `character_archetypes/`（通用层，45 个文件） |
| 节奏模板 | 不存在，需新增 `pacing_template/`（通用层） |
| 数据闭环 | 不存在，需新增自评+趋势+复盘流程 |
| 多项目管理 | 不存在，需新增项目切换机制 |

## plan-iteration 工作流

用户会把 plan 发给其他 AI（如 DeepSeek）审查，带回反馈让我修。多轮迭代模式：
1. 我写/改 plan
2. 用户发给其他 AI
3. 用户带回审查意见（逐条）
4. 我逐条评估，**批判性采纳**（不盲目接受，判断每条是否真的合理）
5. 修复后同步副本（如有 `~/Downloads/` 副本要求）
6. 重复直到锁定

**注意：**
- Plan 有副本同步要求时，每次改动必须同步到 Downloads
- 外部 AI 的建议不一定都对——要结合实际情况判断，**批判性采纳**（不盲目接受，逐条评估是否真的合理）
- 用户会把方案发给多个 AI 审查（DeepSeek、Claude），期望我综合多方意见给出自己的判断，而不是直接执行某一方的建议
- 每轮修订后更新 plan 末尾的时间戳和修订说明
- 批量 patch 后必须 grep 验证每条改动落地（patch 工具静默失败）

## 架构设计核心原则

### 通用 vs 专门

**通用创作器 + 项目配置层。** 工具能力（流程、门禁、预测）和小说内容（人物、世界观、大纲）完全解耦。用户不会只写一本，通用能力是复利。

**设计阶段不要建议"先跑起来"。** 用户在构建生成器/工具时，架构设计本身就是产品。底层设计的质量决定了未来每一本小说的天花板。区分"造工具"和"用工具"两种心态。

**从实际生成场景来考虑设计。** 技法库的组织方式应该映射到写作时的使用场景（"我正在写开场/高潮/战斗"），而不是抽象的概念分类。场景层是缺失的关键层——原子概念告诉AI"什么是悬念"，但没告诉它"在章末场景中怎么用悬念"。

**场景串联文件（`technique_library/_scenarios/`）**：每个场景文件交叉引用5层数据库（motif→character→technique→style→pacing），搜索"废柴逆袭"能同时找到角色原型+相关场景+技法+风格。10个场景文件：opening、climax、cliffhanger、character-intro、world-building、fight-scene、dialogue-tension、revelation、romance、training。详见 `references/unified-search-architecture.md`。

### 五层文学支撑 + 节奏模板

| 文件 | 管什么 | 层级 | 比喻 |
|------|--------|------|------|
| `philosophy.md` | 思想骨架 | 项目层 | 追问什么 |
| `characters.md` | 人物血肉 | 项目层 | 谁在追问 |
| `character_archetypes/` | 人格原型 | **通用层** | 追问者的底层人格池 |
| `motif_library/` | 叙事母题模式 | **通用层** | 可迁移的叙事结构（归乡、复仇、身份错认…） |
| `motifs.md` | 本书母题使用计划 | 项目层 | 选了哪些母题 + 定制意象 + 出场计划 |
| `world.md` + `world_texture.md` | 舞台 + 触感 | 项目层 | 棋盘 + 棋盘的质感 |
| `technique_library/` | 写作技巧 | **通用层** | 怎么追问 |
| `pacing_template/` | 网文节奏套路 | **通用层** | 读者留存的工程学（黄金三章、章末钩子、爽点循环） |

**母题 vs 意象的关键区分：**
- **母题（motif）**：可迁移的叙事模式（"归乡""复仇"）→ 通用层 `motif_library/`
- **意象（image）**：母题的感官载体（"漏水的龙头""褪色的照片"）→ 项目层 `motifs.md`
- 同一母题在不同书里长成不同的意象

**情境（scenario）的定位：**
- 情境嵌在母题文件的 `## 常见情境原型` 小节中，不单独建库
- 理由：情境高度绑定母题（"嫂嫂诬陷小叔子"只属于"兄弟反目"母题），复用率低；890+ 个文件太碎；QMD 已可跨文件检索情境内容
- 真正的缺口是 `character_archetypes/`（角色原型复用率远高于情境）

**套路 vs 哲学的关键区分：**
- **套路/节奏**：管"读者不走"——什么时候给爽点，什么时候制造悬念
- **哲学/母题**：管"读者记住"——这本书在追问什么，留下什么记忆点
- 套路是容器，哲学是内容

### 关键设计约束

1. **人工始终在环**——门禁、批写、大纲、数据全部设人工确认节点
2. **数据闭环克制化**——主观评分 + 趋势展示，不做自动归因，50 章后才启用统计规则
3. **哲学对齐 = 人工反思表单**——3 个问题，系统只记录不判定
4. **零外部依赖**——RAG 用本地 QMD 引擎（BM25+向量+reranking），趋势手动记录

## Iron Law（铁律 — 任何情况下不可违反）

以下约束无论用户如何要求，均不得绕过：

⛔ **禁止跳过强制章节闭环**：每章生成后必须依次执行"更新记忆 → 检查一致性 → 节奏审查 → 风格校准 → 校稿 → 门禁检查"，六步缺一均视为流程中断。门禁未通过（`gate_result.json` 中 `passed != true`）时，严禁进入下一章。

⛔ **禁止绕过开书前确认**：执行 `/一键开书` 前，必须引导用户完成五要素确认（目标读者、写作风格、核心禁区、自动化等级、目标规模），并写入 `idea_seed.md`。不得以"用户着急"为由省略。

⛔ **禁止混淆正文与元信息**：小说正文中不得出现任何 `[说明]`、`（注：）`、`TODO`、写作分析段落或角色定位标记。一旦出现，立即触发 P0 重写，不得保留并"以后修改"。

⛔ **禁止在门禁失败后继续写作**：`gate_result.json` 显示 `passed: false` 时，唯一合法操作是执行 `/修复本章`。不得绕过、手动修改 `gate_result.json`，或以"小问题"为由忽略。

⛔ **禁止任意修改主线规划**：任何 Agent（包括写作特工）均无权修改 `novel_plan.md` 的主线架构。中途改纲须显式执行 `/改纲续写` 并经用户确认。

⛔ **禁止剧情加速**：每章至多触发以下配额1项（A 主线矛盾实质推进 / B 主要关系决定性升级 / C 核心秘密完整揭露）。同时触发2项及以上 = 越界，Beat Sheet 必须修改后重写，门禁强制失败。快档章节（主线突破）结束后下一章必须是慢档或中档。

## 1. 能力矩阵

| 能力 | 状态 | 入口命令 |
|------|------|---------|
| 交互式脑洞引导 + 知识图谱构建 | `[已实现]` | `/脑洞建图` |
| 新手三命令快速开书 | `[已实现]` | `/一键开书` `/继续写` `/修复本章` |
| 每章六步质量门禁 | `[已实现]` | 自动执行 |
| 长期记忆 + 300万字一致性保证 | `[已实现]` | 门禁+RAG+图谱协同（五层全部就位） |
| RAG 剧情检索 + 实体映射 | `[已实现]` | `/剧情检索` `/更新剧情索引` |
| 联网调研 + 知识缺口补充 | `[已实现]` | `/联网调研` |
| 风格提取、累积与跨项目复用 | `[已实现]` | `/风格提取` `/风格库检索` |
| 续写前引导 + 无人干预自动推进 | `[已实现]` | `/继续写` |
| 全自动写书调度（断点续写） | `[部分实现]` | `/一键写书` |
| 小说仿写（联网拆解 + 魔改） | `[部分实现]` | `/仿写` `/拆书` |
| 中途改纲 + 级联更新 | `[已实现]` | `/改纲续写` |
| 大纲锚点 + 进度配额强约束 | `[已实现]` | 自动集成 |
| 多步流水线写作（Beat Sheet） | `[已实现]` | 自动集成 |
| 反向刹车（Anti-Resolution） | `[已实现]` | 自动集成 |
| 事件矩阵 + 冷却机制 | `[已实现]` | 自动集成 |
| 跨Agent双智能体审核 | `[已实现]` | `/双审` |
| 读者群体 + 写作风格强制确认 | `[已实现]` | `/一键开书 --target-audience --writing-style` |
| 配置碎片想法填充 | `[已实现]` | `/填充配置` |
| AI 构思大纲 | `[已实现]` | `/构思大纲` |
| 大纲修订 | `[已实现]` | `/修订大纲` |
| 章节自评 | `[已实现]` | `/自评` |
| 写作复盘 | `[已实现]` | `/复盘` |
| 创作反思 | `[已实现]` | `/反思` |
| 数据库管理 | `[已实现]` | `/导入数据` |
| 真相文件系统（7文件 + 两阶段写作） | `[已实现]` | 自动集成 |
| QMD + plot_rag 双搜索架构 | `[已实现]` | 统一入口 `unified_search()` |

### 300万字一致性保证机制

长期记忆不是单一功能，而是多层机制协同：

| 层级 | 机制 | 状态 |
|------|------|------|
| 第1层 | 每章6步门禁（记忆同步+一致性+节奏审查+风格+校稿+门禁脚本） | `[已实现]` |
| 第2层 | RAG 剧情检索（两级粗筛精排，写前自动回读相关片段） | `[已实现]` |
| 第3层 | 知识图谱（节点+边+版本，每章回写，改纲级联） | `[已实现]` |
| 第4层 | 大纲锚点（全局进度条，章节推进配额，越界即失败） | `[已实现]` |
| 第5层 | 跨Agent审核（独立审稿官交叉验证，批处理10章体检） | `[已实现]` |
| 第6层 | 真相文件系统（7个JSON真相文件 + Observer/Reflector 自动沉淀） | `[已实现]` |

6层全部就位，可支撑300万字规模的剧情一致性。知识图谱每章自动回写 + 大纲锚点强约束 + 跨Agent审核 + 真相文件系统四重保障，从根本上消除全局性剧情漂移。

## 通用层数据库

跨项目共享的知识资产，所有项目均可调用。**376 个文档已索引到 QMD。**

| 库 | 文件数 | QMD collection | 内容 |
|---|---|---|---|
| `motif_library/` | 178 | motif-library | 中国神话母题索引(25)、神祗与英雄(19)、Indo-European(19)、钟敬文(15)、外国鉴赏辞典(18)、千面英雄(14)、中国民间故事类型(21)、金枝(14) + 其他 |
| `character_archetypes/` | 45 | character-archetypes | Campbell(9)、中国神话(5)、民间故事(4)、Frazer(2)、水浒(13)、原有(3)、网文角色(9) |
| `technique_library/` | 26 | technique-library | 原有(5) + 学术论文(11) + 场景串联(10) |
| `pacing_template/` | 5 | pacing-template | 理论(4) + 真实数据基准(1)（14本小说分析） |
| `style_library/` | 11 | style-library | 原有(5) + 巅峰榜epub深度风格(6) |

**QMD 集成**：6 个 collection，376 文档已索引：

| collection | 文档数 | 内容 |
|-----------|--------|------|
| wiki | 111 | Obsidian 文学知识库 |
| motif-library | 178 | 叙事母题 |
| character-archetypes | 45 | 角色原型 |
| technique-library | 26 | 写作技法（含10个场景串联文件） |
| pacing-template | 5 | 节奏模板 |
| style-library | 11 | 风格档案 |

搜索方式：
- **QMD 语义搜索**：`qmd query "关键词" -c motif-library`
- **Ingest 导入**：`python3 scripts/novel_ingest.py <文件> --type <类型> --write --sync-qmd`
- **统一搜索**：`common.py` 中的 `unified_search()` 同时搜 plot_rag + QMD

**节奏基准数据**：14本小说、700章分析，发现巅峰榜四种节奏模式（A低钩子反转/B高钩子问号/C零钩子内容驱动/D低对话描写）。详见 `pacing_template/real-data-pacing-benchmark.md`。

## 真相文件系统

7个真相文件（JSON + schema 验证 + markdown 投影），存储在 `00_memory/truth/` 目录。

| 文件 | 用途 |
|------|------|
| `world_state.json` | 世界观（地图/地点/科技/魔法体系） |
| `character_matrix.json` | 角色矩阵（姓名/关系/弧光/动机） |
| `emotional_arcs.json` | 情感弧光（每个角色的情感轨迹） |
| `resource_ledger.json` | 资源账本（物品/金钱/力量等级） |
| `subplot_board.json` | 支线管理（活跃/休眠/已解决） |
| `hook_ledger.json` | 钩子账本（upsert/mention/resolve/defer） |
| `chapter_summaries.json` | 章节摘要（结构化） |

**核心模块**：schemas.py, truth_manager.py, chapter_observer.py, chapter_reflector.py, two_phase_writer.py

**两阶段写作**：Phase 1（创意：搜索+过滤+生成）→ Phase 2（状态沉淀：Observer提取事实+Reflector更新真相文件）

**健康检查**：钩子过期/爆发/停滞、资源突变、情感跳跃、支线遗忘

详见 `references/truth-file-system.md`

## 2. 新手三命令

| 命令 | 说明 |
|------|------|
| `/一键开书` | 输入题材与剧情种子，自动完成建模 + 建库 + 首章准备 |
| `/继续写` | 自动执行"检索 → 写作 → 门禁 → 索引更新"全链路 |
| `/修复本章` | 门禁失败后自动生成最短修复路径 |

新手模式：`/新手模式 开启`（默认）；高级用户：`/新手模式 关闭`

### 进阶创作命令

| 命令 | 说明 | 何时使用 |
|------|------|---------|
| `/填充配置 <文件名> <碎片想法>` | 将碎片想法自动填充到指定配置文件（支持 philosophy / characters / motifs / world / world_texture / style_anchor / character_archetypes） | 有灵感但不知如何组织到配置中 |
| `/构思大纲` | 基于当前项目状态，AI 自动生成完整大纲 | 开书后需快速产出大纲 |
| `/修订大纲 <变更说明>` | 根据用户描述的变更意图，修订现有大纲 | 大纲需要局部调整 |
| `/自评 <章节号>` | 对指定章节进行自评打分（1-5分），输出 strengths / weaknesses / mindset | 写完章节后自我复盘 |
| `/复盘` | 汇总所有章节自评数据，生成整体复盘报告 | 定期回顾写作质量趋势 |
| `/反思 <内容>` | 记录一条创作反思（灵感、教训、改进点），写入反思日志 | 随时记录创作感悟 |
| `/导入数据 <文件> --type <类型>` | 分析外部文本，填充通用层数据库（`novel_ingest.py`，类型: web_novel/motif/character/technique/style） | 导入外部小说/素材到知识库 |

**填充配置类型说明**：

| type | 说明 |
|------|------|
| `philosophy` | 小说核心哲学 / 主题思想 |
| `characters` | 角色档案 |
| `motifs` | 母题 / 核心意象 |
| `world` | 世界观设定 |
| `world_texture` | 世界质感 / 细节肌理 |
| `style_anchor` | 风格锚点 / 基线文风 |
| `character_archetypes` | 角色原型 |

## 3. 开书前强制确认（写前必过）

执行 `/一键开书` 或 `/脑洞建图` 前，必须引导用户确认以下要素并写入 `00_memory/idea_seed.md`：

1. **目标读者**：年龄段、渠道（起点/番茄/出版）、口味偏好
2. **写作风格**：历史正文 / 网文爽文 / 文艺 / 悬疑推理 / 言情细腻（参照题材风格矩阵）
3. **核心禁区**：不能写什么（敏感题材、读者雷点）
4. **自动化等级**：手动（每章确认）/ 半自动（每10章确认）/ 全自动
5. **目标规模**：总字数、预期卷数、单章字数范围

用户回答"不确定"时：基于题材和读者群体，给出 2-3 个推荐选项供选择。

确认结果直接绑定后续生成参数（温度、对话占比、句长节奏、爽点密度等）。

## 4. 强制章节闭环

每次生成新章节后固定执行，按顺序逐项勾选，任何一项未通过都 ⛔ 禁止进入下一章：

- [ ] `/更新记忆` ⚠️ — 同步章节变化到状态追踪器。**跳过后果**：角色状态、伏笔、时间线等关键信息失去追踪，后续章节将产生设定冲突。
- [ ] `/检查一致性` ⚠️ — 检查剧情/设定/角色/时间线冲突。**跳过后果**：矛盾在后续章节累积，到百章后几乎无法修复。
- [ ] `/节奏审查` ⛔ — **语义级节奏审查**（Claude Code 自身执行，无需外部 API）。读章节正文，完成四项判断并写入 `04_editing/gate_artifacts/<chapter_id>/pacing_review.md`。**跳过后果**：关键词脚本无法检测的隐性剧情加速将溜过门禁。详见下方《节奏审查执行规范》。
- [ ] `/风格校准` ⚠️ — 检测并修正文风偏移（题材基调、句长节奏、对话比例）。**跳过后果**：风格逐章漂移，读者流失率上升。
- [ ] `/校稿` ⛔ — 两遍式去AI味润色：清除24类AI模式 → 自审剩余AI感 → 二次修改。解决翻译腔、过度总结、对话同质化。**跳过后果**：正文保留明显AI痕迹，读者识别后丧失沉浸感，直接影响完结率。详见 `references/humanizer-guide.md`。
- [ ] `/门禁检查` ⛔ — 脚本化校验发布标准（`gate_result.json` `passed: true` 方可解锁下一章）。**跳过后果**：违反 Iron Law，流程强制中断。

**为什么不能跳过**：长篇小说的设定矛盾和风格漂移会随章节指数级放大。门禁每章多花10分钟，可以避免后期30章的全面返工。

### `/节奏审查` 执行规范（Claude Code 自身作为审查 Agent）

执行 `/节奏审查` 时，**不需要任何外部 API**，由当前 Claude Code 实例直接读取章节正文并执行以下四项语义判断，将结果写入产物文件：

**产物路径**：`04_editing/gate_artifacts/<chapter_id>/pacing_review.md`

**输出模板**（严格按格式填写，便于脚本解析）：

```markdown
# 节奏审查报告

## 一、档位判断
- **本章档位**：[慢档 / 中档 / 快档]
- **判断依据**：[1-2句：主要场景类型、核心矛盾推进幅度]

## 二、A/B/C 配额核查
- **A（主线矛盾实质推进）**：[触发 / 未触发] — [简要说明]
- **B（主要关系决定性升级）**：[触发 / 未触发] — [简要说明]
- **C（核心秘密完整揭露）**：[触发 / 未触发] — [简要说明]
- **配额违规**：[是 / 否]（同时触发 ≥2项 = 违规）

## 三、章末悬念质量
- **悬念等级**：[强 / 中 / 弱 / 无]
- **具体悬念内容**：[用一句话描述章末留下的钩子]

## 四、隐性加速检测
- **是否存在关键词未覆盖的隐性加速**：[是 / 否]
- **说明**：[如有，描述具体表现；无则写"无"]

## 综合结论
节奏审查: [通过 / 失败]
失败原因: [若失败，填写具体原因；通过则填"无"]
```

**审查判断标准**：
- A 触发 = 本章主线格局发生实质性、不可逆的改变（非小摩擦）
- B 触发 = 主要角色关系到达决定性节点（结盟/决裂/告白/宣战等）
- C 触发 = 核心秘密在本章被完整揭露（非暗示）
- **结论为"失败"的条件**：A/B/C 同时触发 ≥2项 **或** 存在隐性加速 **或** 章末悬念等级为"无"且非慢档收尾

## 5. 低上下文策略

- 写前默认只读：`00_memory/novel_plan.md`、`00_memory/novel_state.md`
- 新剧情优先执行 `/剧情检索`，只读取 `next_plot_context.md` 推荐的 Top 片段
- 单章前置读取上限：**最多 4 个文件**
- 每 10 章做一次深度压缩与深度风格校准

## 6. 五大工作模式

| 模式 | 流程 | 适用场景 | 状态 |
|------|------|---------|------|
| 从模糊想法 | `/脑洞建图` → `/一键开书` → `/继续写` → 章节闭环 | 只有一个灵感 | `/脑洞建图` 规划中，其余已实现 |
| 从样章仿写 | `/仿写` → `/风格提取` → `/题材选风格` → `/继续写` → 章节闭环 | 模仿已有作品 | 部分实现 |
| 已有项目续写 | `/续写` → `/继续写` 或 `/批量写作` → 章节闭环 | 中断后恢复 | 已实现 |
| 中途改纲 | `/改纲续写` → 级联更新 → `/继续写` → 章节闭环 | 剧情走向需要调整 | 已实现 |
| 全自动 | `/一键写书` → 系统自动循环至目标字数 | 完全托管 | 部分实现（调度框架就绪） |

详细步骤教程见 `references/user-guide.md`。

## 7. 长篇强约束机制

以下机制为300万字级别长篇的核心保障，详细规范见各参考文档。

### 7.1 知识图谱（替代平面文件）

用图结构（节点+边+版本）管理角色、事件、伏笔、世界观规则。每章写后自动提取信息回写图谱，改纲时级联更新。
→ 详见 `references/story-graph-schema.md`

### 7.2 大纲锚点与进度配额

每章写前读取全局进度条，动态注入约束（"当前第X章，距离目标还有200章，本章严禁超过当前节点剧情"）。越界直接触发门禁失败。
→ 详见 `references/outline-anchor-quota-spec.md`

### 7.3 多步流水线写作

将"写一章"拆解为：生成 Beat Sheet（分镜头）→ 按 Beat 扩写血肉 → 串联合成。强制限制单次生成的剧情跨度，让每个场景充分展开。
→ 详见 `references/beat-pipeline-spec.md`

### 7.4 反向刹车 + 事件冷却 + 节奏配额

- **节奏三档制**：慢档（铺垫/羁绊，每3-4章≥1章，主线零推进）/ 中档（次要矛盾升温未爆发，≥60%）/ 快档（主线突破，每卷≤2-3次，快档后必须有慢/中档缓冲）
- **配额硬上限**（Iron Law第6条）：每章至多触发 A/B/C 中1项；触发后逐章冷却
- **章末强制自检**：① 主线核心矛盾仍未解决？② 章末具体悬念是什么（不得模糊）？
- 非终局章节禁止解决主线核心冲突；事件分类池冷却；非冲突场景强制埋微型伏笔
→ 详见 `references/anti-resolution-cooldown-spec.md`

### 7.5 跨Agent双智能体审核

- 逐章审核：写作工具完成 → 不同工具审核（Claude写Codex审，反之亦然）
- 批处理审核：每10章由"极严苛老书虫"人设审核官做三维度体检（逻辑硬伤/阅读体验/去AI化）
- 防死循环：单章最多3轮审核，连续3章"有条件通过"则强制暂停请求人工介入
→ 详见 `references/cross-agent-review-protocol.md`

### 7.6 真相文件系统（两阶段写作）

将"写一章"拆解为两个阶段：
- **Phase 1 创意阶段**：搜索+过滤+生成正文
- **Phase 2 状态沉淀**：Observer 从正文中提取结构化事实 → Reflector 更新7个真相文件

每章写完后自动沉淀状态，消除"AI写了但忘了"的问题。
→ 详见 `references/truth-file-system.md`

## 8. 命令表

### 新手命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/一键开书` | 自动完成开书全流程 | 第一次开项目 |
| `/继续写` | 引导剧情走向 → 自动串行完整章节流程 | 日常推进章节 |
| `/修复本章` | 门禁失败后自动修复 | 门禁返回失败后 |
| `/新手模式` | 切换简化/高级交互层 | 按需 |

### `/继续写` 的续写前引导机制

每次执行 `/继续写` 时，系统在写作前自动执行：

1. **引导提问**：向用户询问本章的剧情走向偏好（"你希望本章发生什么？有什么新的脑洞吗？"）
2. **脑洞拓展**：基于当前大纲和知识库，提供 2-3 个可能的剧情走向供选择
3. **用户确认**：用户选择一个方向，或提供自己的想法
4. **兜底机制**：如果用户回复"不确定"/"随便"/"自动"，则按 `novel_plan.md` 当前节点自动推进，无需人工干预
5. **全自动模式**：如果在开书确认卡中选择了"全自动"等级，跳过引导直接按大纲写作
6. **节奏预检（⛔ BLOCKING，写作开始前必须声明）**：① 本章节奏档位（慢档/中档/快档）及依据；② 近3章配额触发记录，确认本章 A/B/C 至多触发1项；③ 章末保留的具体悬念是什么。预检未通过时禁止进入写作。

### 创作命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/写全篇` | 模糊想法 → 百万字路线图 | 开新书或大纲重建 |
| `/写作` | 生成单章草稿并触发闭环 | 手动推进单章 |
| `/续写` | 恢复会话状态并继续 | 中断后恢复 |
| `/批量写作` | 连续生成多章 | 快速推进 |
| `/修改章节` | 修订已写章节并级联更新 | 章节返工 |
| `/改纲续写` | 中途改纲 + 锚点重算 + 图谱级联 + RAG 重建 | 调整主线走向后继续写作 |
| `/一键写书` | 全自动写作调度 | 完全托管 |
| `/填充配置 <文件名> <碎片想法>` | 碎片想法 → 配置文件自动填充 | 有灵感时快速录入 |
| `/构思大纲` | AI 自动生成完整大纲 | 开书后快速产出大纲 |
| `/修订大纲 <变更说明>` | 根据意图修订大纲 | 大纲局部调整 |
| `/自评 <章节号>` | 章节自评打分（1-5）+ 优劣分析 | 写完章节后复盘 |
| `/复盘` | 汇总自评数据，生成复盘报告 | 定期回顾质量趋势 |
| `/反思 <内容>` | 记录创作反思到反思日志 | 随时记录感悟 |
| `/导入数据 <文件> --type <类型>` | 外部文本 → 通用层数据库 | 导入素材 |

### 命令体系速查

| 类别 | 命令 |
|------|------|
| 构思 | `/填充配置` `/填充风格` `/填充技巧` `/填充原型` `/构思大纲` `/修订大纲` |
| 写作 | `/继续写` `/批量写作`(≤3) `/修复本章` `/修改章节` `/反思` |
| 评估 | `/自评` `/复盘` `/趋势` `/数据面板` |
| 管理 | `/新建项目` `/切换项目` `/项目列表` `/项目状态` `/角色状态` `/伏笔状态` `/风格校准` `/知识图谱` |
| 数据库 | `/导入数据 <文件> --type <类型>`（web_novel/motif/character/technique/style） |

**哲学对齐触发条件：** 不每章弹出。触发条件：(1) 门禁检测到本章与核心命题无关联；(2) 每 10 章强制深度回顾。

**存储分层：**
- 热数据（每章读）：character_tracker / foreshadowing / world_state / 上章摘要 / outline / style_anchor
- 温数据（按需触发）：4 个通用层库 + motifs.md + world_texture.md
- 冷数据（几乎不读）：archive + 旧版文件

### `/改纲续写` 使用说明

**适用场景**：发现主线走向需要调整，修改了 `novel_plan.md` 之后，必须通过此命令重新对齐系统的三层索引（大纲锚点 + 知识图谱 + RAG 索引），然后才能继续写作。

**执行前置条件**（顺序不可颠倒）：
1. 手动编辑 `00_memory/novel_plan.md`，完成改纲内容
2. 确认改纲影响的起始章节（`--from-chapter`），即从第几章开始剧情走向已发生变化

**三步级联流程**：
1. **锚点重算**（必须成功，否则中止）：备份当前 `outline_anchors.json` → 从修改后的 `novel_plan.md` 重新计算所有大纲锚点
2. **图谱级联标记**（依赖锚点重算成功）：将 `last_updated >= from_chapter` 的知识图谱节点标记为 `cascade_pending=True`，生成级联影响报告
3. **RAG 索引重建**（依赖锚点重算成功）：调用 `plot_rag_retriever.py build` 全量重建检索索引

**脚本执行**：
```bash
python3 scripts/novel_flow_executor.py revise-outline \
  --project-root <项目目录> \
  --from-chapter <起始章节号> \
  --change-description "<本次改纲的简要说明>" \
  [--emit-json]
```

**成功判定**：`ok = anchors_recalculated AND report_written`

**产物**：
- `.flow/backup_anchors_<时间戳>.json`：改纲前的锚点备份
- `00_memory/outline_anchors.json`：重算后的新锚点
- `00_memory/revise_outline_report.md`：本次改纲影响范围报告

**改纲后续操作**：检查报告确认级联节点无误 → 对 `cascade_pending=True` 的节点做人工审核或自动修正 → 执行 `/继续写` 恢复正常写作流程

### 质量命令（每章必经）

| 命令 | 功能 |
|------|------|
| `/更新记忆` | 同步状态追踪器 |
| `/检查一致性` | 检查剧情/设定/时间线冲突 |
| `/节奏审查` | 语义级节奏审查，写入 pacing_review.md（Claude Code 自身执行，无需外部 API） |
| `/风格校准` | 检测文风偏移 |
| `/校稿` | 去AI味润色 |
| `/门禁检查` | 脚本化校验发布标准 |

### 检索与记忆命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/更新剧情索引` | 扫描章节建立索引 | 门禁通过后 |
| `/剧情检索` | RAG 检索相关片段 | 每章写前 |
| `/检索记忆` | 按关键词搜索记忆 | 定位历史设定 |
| `/伏笔状态` | 查看伏笔埋设/回收/超期 | 写前确认 |
| `/角色状态` | 汇总角色当前状态 | 群像章节前 |
| `/时间线` | 查看事件时间顺序 | 跨章跳时叙事 |
| `/联网调研` | 联网搜索补充知识库 | 知识缺口补充 |

### 风格命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/题材选风格` | 按题材矩阵选择基线风格 | 开书定风格 |
| `/风格提取` | 从样章提取风格到库 | 用户提供样章 |
| `/风格迁移` | 将风格档案应用到章节 | 切换文风 |
| `/风格库检索` | 检索可复用风格 | 选风格困难时 |

### 分析命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/拆书` | 拆解作品结构，提炼爽点钩子 | 学习目标作品 |
| `/仿写` | 提取写法模板与风格特征 | 模仿样章文风 |

## 9. 脚本入口

### 新增参数（2026-05-09 修复）

| 脚本 | 新增参数 | 说明 |
|------|---------|------|
| chapter_gate_check.py | `--auto-create-missing` | 自动创建缺失的门禁产物文件（占位模板） |
| plot_rag_retriever.py query | `--min-score` | 最低得分阈值（默认0.0），低于此分数的结果被过滤 |
| novel_flow_executor.py one-click | `--avg-chars-per-chapter` | 章均字数（默认2500，基于番茄巅峰榜基准） |
| style_fingerprint.py | 子命令模式 `extract` | 从位置参数改为子命令，`--project-root` 改为 required |
| anti_resolution_guard.py | `--chapter int` | 从 `--chapter-file`（路径）改为 `--chapter`（整数） |

| 脚本 | 用途 |
|------|------|
| `python3 scripts/novel_flow_executor.py one-click` | `/一键开书` |
| `python3 scripts/novel_flow_executor.py continue-write --project-root <目录> --query "<新剧情>"` | `/继续写` |
| `python3 scripts/novel_flow_executor.py revise-outline --project-root <目录> --from-chapter <N> --change-description "<说明>"` | `/改纲续写` |
| `python3 scripts/plot_rag_retriever.py build/query` | `/更新剧情索引` `/剧情检索` |
| `python3 scripts/chapter_gate_check.py` | `/门禁检查` |
| `python3 scripts/gate_repair_plan.py` | `/修复本章` |
| `python3 scripts/auto_novel_writer.py` | `/一键写书` |
| `python3 scripts/style_fingerprint.py` | `/风格提取` |
| `python3 scripts/research_agent.py` | `/联网调研` |
| `python3 scripts/benchmark_novel_flow.py` | `/评测基线` |
| `python3 scripts/story_graph_builder.py` | 知识图谱 CRUD / 校验 / Mermaid 导出 |
| `python3 scripts/outline_anchor_manager.py` | 大纲锚点初始化 / 配额检查 / 推进 |
| `python3 scripts/event_matrix_scheduler.py` | 事件矩阵冷却 / 推荐 / 记录 |
| `python3 scripts/anti_resolution_guard.py` | 反向刹车校验 / 约束 prompt 生成 |
| `python3 scripts/beat_sheet_generator.py` | Beat Sheet 生成 / 扩写提示 / 校验 |
| `python3 scripts/chapter_synthesizer.py` | 章节合成 / 合成稿质量校验 |
| `python3 scripts/cross_agent_reviewer.py` | 跨Agent审核任务生成 / 结果记录 |
| `python3 scripts/story_graph_updater.py` | 章节完成后自动提取信息更新图谱 |
| `python3 scripts/interactive_ideation_engine.py` | 交互式脑洞引导 5 轮收敛 / 产出物生成 |
| `python3 scripts/text_humanizer.py` | AI痕迹检测 / 两遍式润色 prompt 生成 |
| `python3 scripts/editorial_team_manager.py` | 编辑团队状态管理 |
| `python3 scripts/fill_config.py` | `/填充配置`（7种配置文件） |
| `python3 scripts/outline_generator.py generate/revise` | `/构思大纲` `/修订大纲` |
| `python3 scripts/self_review.py start/submit` | `/自评` |
| `python3 scripts/review_panel.py summary` | `/复盘` |
| `python3 scripts/reflection.py new` | `/反思` |
| `python3 scripts/novel_ingest.py` | `/导入数据`（统一入口，零token） |

**`continue-write` 标准用法（全功能默认开启）：**

```bash
# 标准用法：知识图谱/大纲锚点/Beat Sheet/AI痕迹纠正/风格更新均自动激活
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <项目目录> --query "<新剧情>"

# 高级用户：按需关闭部分功能
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <项目目录> --query "<新剧情>" \
  --no-beat-sheet --no-constraints --no-graph-update
```

完整参数说明见 `references/command-playbook.md`。

## 10. 工作流

### 节奏分析工作流

从已下载的番茄小说（TXT/EPUB）中逐章提取节奏数据，填充 `pacing_template/` 通用层。

**触发条件**：用户说"分析节奏""解析pacing"等，且有已下载的小说文件。

**工具**：
- 统一入口：`scripts/novel_ingest.py --type web_novel`（零token，纯脚本）
- 详细流程与 pitfalls：`references/novel-ingest-pipeline.md`
- 基准数据：`assets/pacing_template/real-data-pacing-benchmark.md`（v4, 14本分析）

**四种巅峰榜节奏模式**：
- A 低钩子反转（修仙/玄幻）：钩子率12-18%，power_up驱动，对话22-27%
- B 高钩子问号（悬疑/无限流）：钩子率22-34%，question驱动，对话29-37%
- C 零钩子内容驱动（信息密集型）：钩子率0%，长章节3000字
- D 低对话描写（描写驱动型）：对话比例7%，克制情绪

**跨榜不变量**：reveal + power_up 永远是爽点前两名；省略号为零是巅峰榜强特征。

详见 `references/rhythm-analysis-workflow.md`

**中后期节奏**：100-150章与前50章对比，节奏模式基本稳定。唯一显著变化是山野村夫钩子率翻倍（18%→35%），但钩子类型（reversal）不变。

### 节奏模板扩充工作流（从热门作品反向提取）

> 将真实热门小说的节奏模式提取为 `pacing_template/` 通用模板

**触发条件**：用户说"分析节奏""提取节奏模板""拆解热门作品节奏"等。

**流程**：
1. **下载目标作品**：用 TomatoNovelDownloader 下载榜单热门小说（建议 2-3 本不同题材）
2. **分章读取**：TXT 按章节分割，每 10-15 章为一个分析批次
3. **逐章标注节奏维度**：章节字数、情绪强度(1-10)、章末钩子类型、爽点位置与类型、付费点设计
4. **提取节奏模式**：标注高潮/低谷章节编号，绘制情绪曲线
5. **与现有模板对比**：对照 `pacing-curve.md`、`golden-three-chapters.md` 等现有模板
6. **写入新模板**：创建 `pacing_template/<题材>-<风格>-pacing.md`

**终止条件**：连续 10 章无新节奏模式发现 → 模式已稳定，停止分析。

**Pitfall**：
- 节奏 ≠ 内容：分析的是"什么时候给什么情绪"，不是"讲了什么故事"
- 避免一次性读太多章爆 context，分批读 + 分批总结
- 不同题材节奏差异大（都市悬疑 vs 玄幻升级），需分别建模板

### 文献解析入库工作流

用户可以上传参考书籍（PDF/epub/txt/截图），AI 解析后结构化填充到数据库。

**流程：** 用户上传 → 指定目标库 → AI 解析提取 → 结构化填充 → 用户审阅锁定

**文献→目标库映射：**
| 文献类型 | 目标库 |
|---------|--------|
| 原型参考（《史记》《人物原型45种》） | `character_archetypes/` |
| 叙事技法（《故事》《救猫咪》） | `technique_library/` |
| 母题模式（《千面英雄》《金枝》） | `motif_library/`（通用层） |
| 经典叙事作品 | `motif_library/`（补充经典案例字段） |
| 文学批评/哲学著作 | `philosophy.md` |
| 番茄头部作品原文 | `style_library/` |
| 网文套路指南 | `pacing_template/` |

详细管线见 `references/motif-extraction-pipeline.md`

**Pitfall：** 大文件需要分章节解析，不能一次性全量喂入。OCR 对扫描版有错误，需用户抽查。

### 跨库反向提取模式

从已入库的通用层资产中反向提炼其他库的内容。

**典型场景**：从 `motif_library/` 的 178 个母题中反向提炼 `character_archetypes/`。

**流程**：
1. 扫描源库文件，识别与目标库相关的条目
2. 按模板创建目标库文件
3. 交叉引用源库条目（在"经典案例"字段中标注来源母题）

**已验证**：从 178 个母题中提炼出 20 个角色原型（Campbell 框架 9 类、中国神话 5 类、民间故事 4 类、Frazer 2 类）。

### 文本风格分析工作流

从参考作品逐章解析写作风格，填充 `style_library/`。

**触发条件**：用户说"分析风格""解析写法""提取风格"等。

**流程**：`markitdown` 转 markdown → 逐章阅读总结风格特征 → 连续 10 章无新元素 → 停止 → 写综合风格分析文件

**分析维度**：叙事视角、语言特征、恐怖/情感处理、信息密度、章节结构、角色塑造、世界观展示、节奏控制

**实际验证**：惊悚乐园 34 章、诡秘之主 110 章，两部作品风格在 20-30 章内基本稳定。

详见 `references/style-analysis-workflow.md`（如有）

### 番茄小说数据采集

详见 `references/fanqie-scraping.md`（含 TomatoNovelDownloader 输出格式、API 测试、OCR 方案）

**关键 pitfall：** 番茄用自定义字体反爬，API 不公开。批量下载用 TomatoNovelDownloader（Rust TUI），输出格式特殊（`--------` 分隔章、无对话引号），分析脚本必须适配。详见 `references/novel-pacing-analysis.md`。

**下载工具对比**：

| 工具 | 适用场景 | 优劣 |
|------|---------|------|
| **TomatoNovelDownloader** (Rust TUI) | 批量下载完整小说 | ✅ 完整文本、速度快、支持榜单搜索 ❌ 需要交互式 TUI 操作 |
| 截图 + macOS Vision OCR | 单章/片段采集 | ✅ 无需安装、实时数据 ❌ 手动操作、OCR 有误差 |

**TomatoNovelDownloader 使用**（v2.4.9+，macOS arm64）：
```bash
cd ~/Downloads
chmod +x TomatoNovelDownloader-macOS_arm64-v2.4.9
./TomatoNovelDownloader-macOS_arm64-v2.4.9
```

### 番茄小说平台写作规范

| 规范 | 要求 |
|------|------|
| 每章字数 | 2000-3000 字 |
| 前 3 章 | 定生死，必须有悬念 |
| 章末 | 必须留钩子 |
| 更新频率 | 日更最佳 |
| 模式 | 免费阅读，广告分成 |

## 17. Claude Code 协作工作流

当需要修改 novel-base 代码时，采用以下工作流：

**角色分工**：
- **Hermes（我）**：统筹规划、需求分析、最终验收
- **Claude Code**：代码实现、自测、推送 Git

**流程**：
1. **多轮讨论**：Hermes 将 issues/需求发给 Claude Code，每轮传递完整上下文（Claude Code 无跨轮记忆）。讨论至无新内容产生。
2. **项目规划**：将讨论结果转为可落地的项目规划（分优先级 P0-P3，含工时估算），与 Claude Code 确认。
3. **分批实现**：按 P0→P1→P2→P3 顺序，每批完成后 ECC 回归测试。
4. **推送 Git**：Claude Code 提交并推送到 `BillChen-29/novel-base`。
5. **验收**：Hermes `git pull` 最新代码，运行 ECC 验证，用 `grep` 确认每处改动落地。

**关键 Pitfall**：
- Claude Code 会 `git stash` 但不 `pop`——每次 delegate_task 后检查 `git stash list`
- Claude Code 不会完全实现所有修改——要求 5 处可能只落地 3 处，必须 grep 验证
- 每轮 delegate_task 无记忆，需传完整上下文（前几轮讨论结果 + 代码位置 + 期望改动）
- `delegate_task` 的 `acp_command` 参数在 CLI 2.1.119 无效，直接用默认方式
- **用户工作流偏好**：讨论→规划→实现全交 Claude Code，我统筹+验收。不要自己生成代码，让 Claude Code 写。

详见 `references/script-fixes-2026-05-09.md`（修复记录）。

## 18. 参考文档导航

根据你的场景选择对应文档：

| 你想做什么 | 读哪个文档 |
|-----------|-----------|
| 第一次使用，从零开书 | `references/user-guide.md` |
| 查看某个命令的完整参数 | `references/command-playbook.md` |
| 理解门禁产物和通过标准 | `references/gate-artifacts-spec.md` |
| 规划百万字级别的卷章结构 | `references/million-word-roadmap.md` |
| 选择合适的写作风格 | `references/genre-style-matrix.md` |
| 理解 RAG 检索的设计原理 | `references/rag-consistency-design.md` |
| 使用联网调研功能 | `references/research-guide.md` |
| 使用全自动写书功能 | `references/auto-write-guide.md` |
| 执行 /校稿 去AI味润色 | `references/humanizer-guide.md` |
| 了解知识图谱数据结构 | `references/story-graph-schema.md` |
| 了解大纲锚点与进度配额 | `references/outline-anchor-quota-spec.md` |
| 了解多步流水线写作 | `references/beat-pipeline-spec.md` |
| 了解反向刹车与事件冷却 | `references/anti-resolution-cooldown-spec.md` |
| 了解跨Agent审核协议 | `references/cross-agent-review-protocol.md` |
| 了解脑洞引导流程 | `references/interactive-brainstorming-playbook.md` |
| 仿写或魔改已有小说 | `references/adaptation-workflow.md` |
| 了解编辑团队架构与工作协议 | `references/editorial-team-protocol.md` |
| 了解真相文件系统 | `references/truth-file-system.md` |
| 了解统一搜索架构 | `references/unified-search-architecture.md` |
| 了解知识过滤设计 | `references/knowledge-filtering.md` |
| 了解 Hook Ledger 设计 | `references/truth-file-hook-ledger-design.md` |
| 了解架构设计方案 | `references/architecture-plan.md` |
| 了解执行计划 | `references/execution-plan.md` |
| 了解母题提取管线 | `references/motif-extraction-pipeline.md` |
| 了解节奏分析流程 | `references/rhythm-analysis-workflow.md` |
| 了解番茄数据采集 | `references/fanqie-scraping.md` |
| 了解技法库结构 | `references/technique-library-structure.md` |
| 了解集成测试结果 | `references/integration-test-findings-2026-05.md` |
| 了解脚本审计报告 | `references/script-audit-2026-05.md` |
| 了解集成测试报告（2026-05） | `references/integration-test-2026-05.md` |
| 了解知乎内容抓取方案 | `references/zhihu-content-extraction.md` |
| 了解集成测试结果（2026-05） | `references/integration-test-2026-05.md` |
| 了解知乎盐选下载工具 | `references/zhihu-salt-downloads.md` |
| 了解集成测试发现（CLI语法/pitfalls） | `references/integration-test-findings-2026-05.md` |
| 了解 InkOS 分析 | `references/inkos-ai-novel-generator-analysis.md` |
| 了解脚本修复记录（2026-05-09） | `references/script-fixes-2026-05-09.md` |
| 了解知乎盐选节奏基准数据 | `references/zhihu-pacing-benchmark.md` |
| 了解知乎盐选字体加密问题 | `references/zhihu-font-encryption.md` |
| 了解知乎盐选平台支持计划 | `/tmp/zhihu_plan_final.md`（待实施） |
| 了解小说工具对比 | `references/novel-tools-comparison.md` |
| 了解多工具安装 | `references/multi-tool-install.md` |
| 了解拆书工作流 | `references/book-extraction-workflow.md` |
| 了解 novel-creator 命令详情 | `references/novel-creator-commands.md` |
| 了解 novel-creator v8 原版文档 | `references/novel-creator-skill-v8.md` |
| 了解 ingest 管线 | `references/novel-ingest-pipeline.md` |
| 了解节奏分析详细流程 | `references/novel-pacing-analysis.md` |

## 12. Agent 编辑团队（`/启动编辑团队`）

### 12.1 为什么需要编辑团队

单 Agent 写作存在三个根性问题：
1. **AI 幻觉**：写作 Agent 可能捏造从未出现过的地名、人名、设定规则
2. **角色错乱**：角色被放错位置、被赋予其不具备的能力、或语气风格全部雷同
3. **Agent 思路污染正文**：写作过程中的分析思路、角色定位说明、meta注记渗入小说正文

编辑团队通过职责严格分离，在生产流程中内建三道防火墙。

### 12.2 团队架构（真实报社模型）

```
用户
  │
  ▼
总编辑（Claude Code 主 Agent）
  │  协调所有子 Agent，汇总报告，作最终裁判
  ├──► 策划主编（planning-editor）
  │     读规划文件 → 生成 Chapter Brief → 传给写作特工
  │
  ├──► 写作特工（novelist）
  │     只接收 Brief，只输出纯正文，严格隔离 meta 信息
  │
  ├──► 反AI编辑（anti-ai-editor）      ┐ 并行
  └──► 连载核实官（consistency-reviewer）┘ 审核
```

### 12.3 触发命令

```
/启动编辑团队 [--项目路径 <路径>] [--章节 <N>] [--模式 单章|批量]
```

### 12.4 正文隔离协议（防止 Agent 思路污染正文）

| Agent | 允许的输出内容 | 严禁的输出内容 |
|-------|--------------|--------------|
| 写作特工 | `NOVEL_TEXT_START` 到 `NOVEL_TEXT_END` 之间的纯小说正文 | 分析说明、角色定位、写作思路 |
| 反AI编辑 | 报告 + `HUMANIZED_TEXT` 标记内的净化正文 | 在润色后正文中插入注释 |
| 连载核实官 | 结构化核查报告 | 直接修改正文 |
| 总编辑 | 最终章节包 | 将审核意见混入正文区 |

**P0 检测触发器**：正文中出现 `[` `]` 括号说明、`（注：）`、`TODO`、`作者按`等，立即触发 P0 强制重写。

### 12.5 状态管理脚本

```bash
# 生成上下文快照
python3 scripts/editorial_team_manager.py snapshot --project-root <路径>

# 记录审核结果
python3 scripts/editorial_team_manager.py record-review \
  --project-root <路径> --chapter N --stage final --verdict pass --p0 0 --p1 2 --p2 3

# 检测是否需要人工介入
python3 scripts/editorial_team_manager.py need-human --project-root <路径>
```

## 13. 自动化分析脚本

| 脚本 | 功能 |
|------|------|
## 工作流：与 Claude Code 协作

当需要对 novel-base 做代码修改时，采用以下流程：
1. **我统筹规划**：讨论方案、制定计划、确认优先级
2. **Claude Code 实现**：通过 delegate_task 派发代码任务，每轮传完整上下文
3. **ECC 自验**：Claude Code 推 git 前必须跑 `test_novel_flow_executor.py` 全部通过
4. **我验收**：pull 最新代码，grep 验证每处改动是否真正落地
5. **Push**：确认无误后由 Claude Code 推送

**重要**：delegate_task 每次是全新会话，无跨轮记忆。多轮讨论时我做 orchestrator，把前轮结论打包进 context。

### Pitfall: Claude Code git stash 忘记 pop
Claude Code 在测试时可能 `git stash`，但忘记 `git stash pop`。验收时必须检查 `git stash list`。

### Pitfall: Patch 工具静默失败
用 patch() 批量修文件时，old_string 不匹配不会报错。每次批量 patch 后必须用 grep 验证每个改动是否真正落地。

## 已知 Issues 和测试报告

集成测试报告见 `references/integration-test-report-2026-05-09.md`。

关键遗留问题：
- `--draft-provider template` 生成器质量差（零故事信息，纯占位符）
- `chapter_gate_check` 需要预生成门禁产物（不能独立调用）
- #2 跨章一致性检查需新建脚本（5h+）
- #8 CJK 字数统计：count_chars 已导入但未启用（与 template 生成器不兼容）

## 使用方法

### 快速初始化
```bash
python3 scripts/one-click_novel_flow.py --title "小说标题" --genre "题材" --target-words 1000000
```
类型：`web_novel` / `motif` / `character` / `technique` / `style`

详细用法见 `references/novel-ingest-pipeline.md`

## 14. 集成测试发现（2026-05-09）

> 40章/114k字完整测试验证，以下为实测发现的脚本问题。

### P0 阻断性问题

| # | 脚本 | 问题 | 状态 |
|---|------|------|------|
| 1 | chapter_gate_check.py | 单独调用时6个产物文件必须预存在，否则报"文件不存在"。需 `--auto-create-missing` | 待修复 |
| 2 | 无对应脚本 | 跨章节一致性检查缺失（角色性别漂移、设定规则违反无法检测） | 待新建 |

### P1 功能问题

| # | 脚本 | 问题 | 状态 |
|---|------|------|------|
| 3 | novel_flow_executor.py | `generate_draft_text()` 模板模式生成通用填充，不读 novel_plan/character_tracker | 待修复 |
| 4 | plot_rag_retriever.py | `query()` 索引构建成功但查询返回0（触发条件+评分阈值双重问题） | 待修复 |
| 5 | novel_flow_executor.py | `init_project_files()` 硬编码 VOL1_END=120，忽略 target_words。公式应为 `target_words // 2500`（番茄巅峰榜基准） | 待修复 |

### P2 代码质量

| # | 脚本 | 问题 | 状态 |
|---|------|------|------|
| 6 | 多个脚本 | CLI参数不统一（style_fingerprint 用位置参数，anti_resolution 用 --chapter-file，其余用 --chapter） | 待统一 |
| 7 | novel_flow_executor.py | `AI_PHRASE_BLACKLIST` 漏检"微微""深吸一口气" | 待补充 |
| 8 | common.py | `evaluate_quality()` 未调用 `count_chars()`，直接 `len(re.sub(...))` 含标点 | 待修复 |

### P3 流水线完善

| # | 脚本 | 问题 | 状态 |
|---|------|------|------|
| 9 | novel_flow_executor.py | chapter_observer/reflector 未集成到 continue-write 流程 | 待集成 |
| 10 | novel_flow_executor.py | `--auto-graph-update` 实际默认 True（非 False），缺 dry-run 和计数反馈 | 待增强 |

### 关键 Pitfall

- **大纲计算公式**：`target_words // 3500` 错误，应为 `// 2500`（番茄巅峰榜章均字数）。推荐榜 2355，新书榜 2610，巅峰榜 2516
- **图谱自动更新**：`--auto-graph-update` 默认是 True（开启），不是 False。v1 分析曾误判
- **RAG 双重零结果路径**：(A) `analyze_query_trigger()` 关键词未命中时跳过检索 (B) `retrieve()` 的 `> 0` 阈值过滤掉所有无交集结果
- **字数统计陷阱**：`count_chars(cjk_only)` 函数存在但 `evaluate_quality()` 没调用它，用的是 `len(re.sub(r"\s+","",body))`（含标点+英文）
- **Claude Code ACP 调用**：`claude --acp --stdio` 在 CLI 2.1.119 不支持，`delegate_task` 的 `acp_command` 参数无效

### 完整修复方案

详见 `/Users/chenzefeng/.hermes/projects/novel-test/project_plan_final.md`

## 15. Pitfall

### 流程 Pitfall
- `novel_flow_executor.py continue-write` 的完整链路依赖 LLM API 调用，本地测试时需要 mock 或跳过写作步骤
- 门禁检查是纯本地的（正则+文件校验），不走 API，可独立测试
- RAG 索引构建需要至少 1 个已写章节，空项目时 `build` 会返回空索引
- **模板写作模式质量极差**：`--draft-provider template` 生成完全通用的模板文本，不含任何故事相关内容（角色名、地点、情节均未使用）。实际使用必须配合 LLM 或手动写作
- **门禁产物必须预生成**：`chapter_gate_check.py` 单独调用时，6个产物文件不存在就报"文件不存在"。已修复：新增 `--auto-create-missing` 参数
- **大纲计算已修复但仍有限制**：`one-click` 的 VOL1_END/VOL2 现已动态计算（基于 target_words/2500），但 2500 是番茄巅峰榜基准，其他平台需手动调整
- **continue-write 测试脆弱**：3 个 continue-write 测试容易因模板文本触发 anti_resolution_guard 误报而失败，这是已有问题而非新引入的
- **Claude Code 会 stash 改动**：当 delegate_task 中的 Claude Code 在调试时执行 `git stash`，改动会从工作目录消失。检查 `git stash list` 可以找回
- **continue-write --draft-provider template 生成完全通用模板**：不含任何故事相关内容（角色名、地点、情节），只是 query 文本的扩展填充。不能用于实际写作，只能用于测试流水线
- **chapter_gate_check 单独调用需 6 个预生成产物**：直接调用 gate_check 时，memory_update.md / consistency_report.md / style_calibration.md / copyedit_report.md / publish_ready.md / quality_report.md 必须预先存在，否则报"文件不存在"。用 `--auto-create-missing` flag 可自动创建占位文件（2026-05 新增）
- **RAG query 返回 0 的两个路径**：(A) `analyze_query_trigger()` 查询未命中角色名/关键词且 <18字时跳过检索；(B) 评分公式 `score > 0` 阈值过滤掉所有得分为0的候选。用 `--min-score 0.0` 可放宽
- **one-click 大纲卷计算曾硬编码**：VOL1_END=120 不随 target_words 变化（已修复为动态计算：target_words / 2500）
- **evaluate_quality 的 char_count 与模板生成器的统计方式不一致**：evaluate_quality 用 `len(pure)`（去空白后所有字符），count_chars() 函数可做 CJK-only 统计但需同步修改模板生成器阈值，否则 3 个 continue-write 测试失败
- **模板文本可能触发 anti_resolution_guard 误报**：模板生成的通用文本中可能包含 forbidden_reveals 列表中的词（如"终极BOSS身份"），导致门禁失败
- **style_fingerprint.py CLI 已重构为子命令模式**：从位置参数改为 `extract` 子命令，--project-root 从 optional 改为 required
- **anti_resolution_guard.py --chapter-file 改为 --chapter int**：文件路径由脚本内部从章节号推导
- **RAG build 成功但 query 返回 0 结果**：索引摘要质量可能不足，BM25 无法匹配。待调查
- RAG 索引构建需要至少 1 个已写章节，空项目时 `build` 会返回空索引
- **CLI 参数格式不统一**：各脚本子命令和参数名不一致。outline_anchor_manager 用 `advance --to-chapter`，anti_resolution_guard 用 `check --chapter-file`，style_fingerprint 用 `--profile-name` + 位置参数 files，cross_agent_reviewer 需要 `--chapter` 和 `--chapter-file` 两个参数。详见 `references/integration-test-findings-2026-05.md`
- **Python 版本**：Hermes venv 使用 Python 3.11.15，PEP 604 语法（`str | None`）可用
- **中文变量名**：所有脚本变量名必须用 ASCII 英文，中文变量名在某些 Python 版本报 SyntaxError
- **输出格式不一致**：`style_fingerprint.py` 的 JSON 输出缺少 `ok` 字段，下游消费者可能依赖此字段
- **路径常量分散**：目录名在 25+ 个脚本中以字符串字面量硬编码，修改目录名需改 25+ 个文件
- **子代理并发限制**：`delegate_task` 最多 3 个并发子代理，多于 3 个需分批启动
- **清理前比对内容**：删除重复文件前，必须 `wc -c` 比较大小 + `head -20` 抽查内容

### 数据 Pitfall
- **TomatoNovelDownloader 输出格式**：TXT 输出中所有 `""「」` 被去除，对话比例分析必须用 EPUB 格式
- **QMD 增量索引**：`qmd update` 支持增量检测，不需要全量 rebuild
- **QMD collection add 路径陷阱**：`qmd collection add` 会忽略 path 参数，创建后必须用 `qmd collection show` 验证
- **markitdown PDF 依赖**：需 `uv tool install markitdown --force --with "markitdown[pdf]"`
- **扫描版 PDF OCR**：macOS Vision 框架（pyobjc）可做中英文 OCR

### 真相文件系统 Pitfall
- **Observer/Reflector 字段名不匹配**：hook_operations 使用 `"operation"` 字段，不是 `"op"`
- **load_truth 返回 tuple**：`truth_manager.load_truth()` 返回 `(data, errors)` 元组，需解包
- **迁移脚本 schema 匹配**：用户自定义的 memory 文件名可能不匹配 schema，迁移时会跳过

### 设计 Pitfall
- **执行计划设计原则**：新建模块不修改原有大文件（novel_chapter_writer.py 57KB、novel_flow_executor.py 134KB）
- **统一CLI入口对Hermes无价值**：Hermes调用脚本时直接读SKILL.md的命令映射
- **Hermes skill的数据库管理设计原则**：用户手动标记文本类型，脚本按类型路由分析，不做自动分类
- **style_library 清理策略**：两套命名时保留更大的版本，但需检查互补内容

### 集成测试 Pitfall（2026-05 新增）
- **template 字数统计不兼容 CJK-only**：`generate_draft_text()` 用 `len(re.sub(r'\s+', '', text))` 统计（含标点），`count_chars()` 只计 CJK 字符。改一边不改另一边会导致门禁阈值不匹配，3 个 continue-write 测试失败。
- **大纲卷计算硬编码**：`init_project_files()` 中 `VOL1_END="120"` 是硬编码的，不跟 target_words 联动。已修复为动态计算。
- **RAG 查询静默跳过**：`analyze_query_trigger()` 在查询不匹配预设关键词时返回 `should_trigger=False`，导致查询返回空结果而无任何提示。已加 >=8 字默认触发。
- **门禁产物必须预生成**：`chapter_gate_check.py` 直接调用时需要 6 个产物文件存在。已加 `--auto-create-missing`。
- **Claude Code 会 stash git 变更**：subagent 调试时会 `git stash`，完成后不 pop。需手动 `git stash pop` 恢复。
- **Claude Code 不会完全实现请求的修改**：要求 5 处修改可能只落地 3 处。每次实现后必须用 `grep` 验证每处改动。

## 15. 集成测试结果（2026-05-09）

通过 40 章小说全流程测试，12/17 脚本验证通过。关键修复已推送到 GitHub。
详见 `references/integration-test-findings-2026-05.md`。

**已修复的问题**：
- 门禁产物预生成（`--auto-create-missing`）
- 大纲卷计算动态化（基于 target_words / 2500）
- RAG 查询精度（`--min-score` + BM25 回退）
- CLI 标准化（style_fingerprint 子命令化, anti_resolution_guard `--chapter` int）
- AI 词表扩展（微微、深吸一口气等）
- 真相系统集成（observer prompt 自动生成）
- 图谱更新反馈（graph_update_count + dry-run）

**已知遗留**：
- template 模式内容质量差（通用模板，不读 novel_plan.md）
- 跨章节一致性检查缺失（需新建脚本）
- CJK 字数统计与 template 生成器不兼容（count_chars 已导入未启用）

## 16. 技能安装说明

本仓库同时是一个 Hermes Agent skill。`SKILL.md` 作为 skill 文件，安装后在对话中触发 `/一键开书`、`继续写` 等命令。安装脚本支持 Claude Code、Codex、OpenCode、Gemini CLI、Antigravity 五个工具。

```bash
bash scripts/install-portable-skill.sh --tool claude-code --force
```
