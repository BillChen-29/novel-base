# 真相文件 + Hook Ledger 设计

> 综合 InkOS（最成熟系统）和 AI_NovelGenerator（4.8k star）的设计理念
> 2026-05-07 生成

## 7个真相文件（InkOS 设计）

| 文件 | 内容 | Schema |
|------|------|--------|
| WorldState | 地图、地点、科技水平、魔法体系 | Dict |
| CharacterMatrix | 姓名、关系、弧光、动机 | Dict |
| EmotionalArcs | 角色情感进展 | Dict[str, CharacterArc] |
| ResourceLedger | 物品、金钱、力量等级 | List[Resource] |
| SubplotBoard | 活跃/休眠的支线 | List[Subplot] |
| HookLedger | 钩子账本（upsert/mention/resolve/defer） | List[Hook] |
| ChapterSummaries | 章节摘要 | List[ChapterSummary] |

## Hook Ledger 操作语义

```python
# 操作
upsert_hook(project_root, chapter, description, **kwargs) → Hook  # 新增钩子
mention_hook(project_root, chapter, hook_id) → bool               # 提及钩子
resolve_hook(project_root, chapter, hook_id) → bool               # 回收钩子
defer_hook(project_root, hook_id, new_deadline) → bool            # 延期钩子

# 健康检查
check_health(project_root, current_chapter) → HookHealth
# - stale_debt：deadline < 当前章节 且 status=open
# - burst_warning：同一章 resolve > 3
# - no_advance：>10章未 mention 且 status=open
```

## JSON + Markdown 投影

真相文件以 JSON 为权威来源，自动生成 markdown 投影供人类阅读：
- `00_memory/truth/hook_ledger.json` → `00_memory/foreshadowing_tracker.md`
- `00_memory/truth/character_matrix.json` → `00_memory/character_tracker.md`
- 保留旧 .md 文件作为 fallback

## 两阶段写作（InkOS 设计）

```
Phase 1（创意，temp 0.7）：
  → 读取真相文件 + QMD搜索 + plot_rag
  → 生成正文

Phase 2（状态沉淀，temp 0.3）：
  → 从正文提取事实（Observer）
  → 更新真相文件（Reflector）
  → 生成 markdown 投影
  → 健康检查
```

## 知识过滤（AI_NovelGenerator 设计）

```
三级过滤：
1. 冲突检测：和已有章节摘要比对，删除重复度>40%的内容
2. 价值评估：标记为❗（核心）或·（参考）
3. 结构归类：按情节燃料/人物维度/世界碎片/叙事技法分类

章节距离规则：
- 距离<=2章：降低权重或跳过（避免重复）
- 距离3-5章：标记"需改写≥40%"
- 距离>5章：正常引用
```

## 与 InkOS 的定位差异

| 维度 | InkOS | 我们的 Skill |
|------|-------|-------------|
| 架构 | Node.js/TypeScript，独立CLI | Python，Hermes Agent skill |
| 使用方式 | `inkos write next` 命令行 | 对话式，Hermes 自动调用 |
| 定制性 | 固定管线，配置驱动 | 完全可定制，脚本可改 |
| 知识库 | 项目内 | 通用层（261资产）+ 项目内 |
| 搜索 | SQLite 时序记忆 | QMD（BM25+向量+reranking）+ plot_rag |
| 适合场景 | 全自动批量生成 | 人机协作，迭代创作 |

**核心理念**：借鉴 InkOS 的状态管理精度，保留我们的人机协作灵活性和通用层知识库优势。
