# InkOS + AI_NovelGenerator 对比分析

> 2026-05-07 生成，用于指导 novel-creator-skill 的改进方向

## 项目概况

| 项目 | Stars | 语言 | 架构 | 特点 |
|------|-------|------|------|------|
| **InkOS** | - | TypeScript/Node.js | 10 Agent 管线 + TUI + Studio Web UI | 最成熟的系统，Hook Ledger + 7真相文件 + 33维审计 |
| **AI_NovelGenerator** | 4.8k | Python | Gradio GUI + 向量检索 | 知识过滤 + 章节距离规则 + 结构化元数据 |

## InkOS 核心设计

### 10 Agent 管线
```
Radar → Planner → Composer → Architect → Writer → Observer → Reflector → Normalizer → Auditor → Reviser
```

### 三阶段写作
- **Phase 1（创意，temp 0.7）**：Planner 生成 chapter intent + hook agenda → Composer 选择上下文 → Writer 生成正文
- **Phase 2（状态沉淀，temp 0.3）**：Observer 提取9类事实 → Reflector 输出 JSON delta → 代码层 Zod schema 验证 + 不可变更新
- **Phase 3（质量循环）**：Normalizer 调整长度 → Auditor 33维检查 → Reviser 自动修复 → 循环直到通过

### 7个真相文件（Long-Term Memory）
| 文件 | 内容 | 我们的对应 |
|------|------|-----------|
| World State | 地图、地点、科技水平、魔法体系 | world_state.md |
| Character Matrix | 姓名、关系、弧光、动机 | character_tracker.md |
| Resource Ledger | 物品、金钱、力量等级 | ❌ 缺失 |
| Chapter Summaries | 事件、进展、伏笔 | chapter_summaries/ |
| Subplot Board | 活跃/休眠的支线、钩子 | ❌ 缺失 |
| Emotional Arcs | 角色情感进展 | ❌ 缺失 |
| Pending Hooks | 未解决的悬念和对读者的承诺 | foreshadowing_tracker.md |

### Hook Ledger 系统
- **操作语义**：upsert（新增）/ mention（提及）/ resolve（回收）/ defer（延期）
- **健康检查**：stale_debt（过期债务）、burst_detection（同章回收过多）、no_advance（长期未提及）
- **准入控制**：防止重复/同族钩子膨胀
- 我们的 foreshadowing_tracker.md 是手动的，没有这些语义

### 33维质量审计
包含：节奏、对话、世界观、大纲遵循度、钩子健康度等
我们的 5 步门禁更简单

## AI_NovelGenerator 核心设计

### 知识库三级过滤
```python
# knowledge_filter_prompt
冲突检测：删除与已有摘要重复度>40%的内容
价值评估：关键价值点(❗) vs 次级价值点(·)
结构重组：按"情节燃料/人物维度/世界碎片/叙事技法"分类
```

### 章节距离规则
```python
# apply_content_rules
距离<=2章：跳过（避免重复）
距离3-5章：修改≥40%才能用
距离>5章：正常引用核心设定
```

### 章节元数据
```python
chapter_info = {
    "chapter_role": "转折",          # 开场|铺垫|转折|高潮|收尾
    "chapter_purpose": "揭示真相",
    "suspense_level": "高",          # 低|中|高
    "foreshadowing": "回收第3章伏笔",
    "plot_twist_level": 4,           # 1-5星
    "characters_involved": [...],
    "key_items": [...],
    "scene_location": "...",
    "time_constraint": "..."
}
```

### 搜索关键词自动生成
从 chapter_info 自动生成 QMD 搜索关键词，而不是直接用原始 query

## 我们的优势（两个项目都没有）

| 特性 | 说明 |
|------|------|
| 通用层数据库 | 261个资产（178母题+45原型+26技法+11风格+5节奏模板） |
| QMD 语义搜索 | BM25+向量+reranking，6 collection 376文档 |
| 场景串联 | 10个场景文件交叉引用5层数据库 |
| 真实数据基准 | 14本番茄小说节奏分析 |
| 多项目复用 | 通用层资产跨项目共享 |
| 人机协作 | 对话式，不强制全自动 |

## 值得借鉴的改进

### 从 InkOS 借鉴
1. **Hook Ledger**：upsert/mention/resolve/defer 语义 + 健康检查
2. **真相文件 Schema 化**：JSON + schema 验证 + markdown 投影
3. **Resource Ledger**：追踪物品/金钱/力量等级
4. **Emotional Arcs**：追踪角色情感进展
5. **Subplot Board**：追踪活跃/休眠支线
6. **两阶段写作**：创意阶段 + 状态沉淀阶段

### 从 AI_NovelGenerator 借鉴
1. **三级知识过滤**：冲突检测 → 价值评估 → 结构归类
2. **章节距离规则**：近章跳过、中距离改写、远距离引用
3. **章节元数据结构化**：chapter_role/purpose/suspense/foreshadowing/twist
4. **搜索关键词自动生成**：从元数据生成 QMD 查询

## 定位差异

| 维度 | InkOS | AI_NovelGenerator | 我们 |
|------|-------|-------------------|------|
| 架构 | TypeScript CLI | Python GUI | Python Hermes Agent |
| 使用方式 | `inkos write next` | Gradio 界面 | 对话式 |
| 定制性 | 固定管线 | 固定管线 | 完全可定制 |
| 知识库 | 项目内 | 项目内 | 通用层+项目内 |
| 搜索 | SQLite 时序 | 向量检索 | QMD+plot_rag |
| 适合场景 | 全自动批量 | 全自动批量 | 人机协作迭代 |

**核心理念**：借鉴 InkOS 的状态管理精度，保留我们的人机协作灵活性和通用层知识库优势。

## 综合改进计划

详见 `.hermes/plans/novel-creator-skill-comprehensive-improvement.md`
执行计划详见 `.hermes/plans/novel-creator-skill-execution-plan.md`
