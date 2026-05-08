# 统一搜索架构（unified_search）

> 2026-05-07 实现

## 两套搜索系统的分工

| 系统 | 索引范围 | 搜索范围 | 调用方式 |
|------|---------|---------|---------|
| plot_rag_retriever.py | 项目内章节 | 单项目 | Python 函数直接调用 |
| QMD | 通用层资产 | 跨项目 | subprocess 调 CLI |

## unified_search() 函数

**位置**：`scripts/common.py`（~110行）

**调用方式**：
```python
from common import unified_search

results = unified_search(
    query="废柴逆袭",
    project_root="/path/to/novel",  # 可选，搜项目内
    collections=None,               # 可选，指定 collection
    top_k=3,
)
```

**返回格式**（按来源分组，不混排分数）：
```python
{
    'plot_context': [...],  # 项目内上下文（来自 plot_rag）
    'motifs': [...],        # 母题建议（来自 QMD motif-library）
    'archetypes': [...],    # 角色原型建议（来自 QMD character-archetypes）
    'techniques': [...],    # 技法建议（来自 QMD technique-library）
    'styles': [...],        # 风格建议（来自 QMD style-library）
    'pacing': [...],        # 节奏模板建议（来自 QMD pacing-template）
}
```

## 设计决策

1. **按来源分组返回，不混排分数**：plot_rag 的 BM25 和 QMD 的向量分数不在同一量纲
2. **subprocess 调 QMD CLI**：timeout=10s，静默降级（QMD 不可用时不中断流程）
3. **QMD 结果章节级缓存**：通用层资产不变，同章不重复搜
4. **plot_rag 结果不缓存**：前文持续更新

## 场景串联文件

`technique_library/_scenarios/` 目录下 10 个场景文件，交叉引用四层数据库：

```
写"背叛场景"时：
  motif: brothers-betrayal.md          ← 发生什么
  character: trickster.md              ← 谁在背叛
  technique: suspense-laddering.md     ← 怎么写悬念
  style: 天渊-style.md                ← 什么语感
  pacing: chapter-hooks.md             ← 章末怎么留钩子
```

场景文件列表：
- opening.md（开场）
- climax.md（高潮）
- cliffhanger.md（章末悬念）
- character-intro.md（角色引入）
- world-building.md（世界观展示）
- fight-scene.md（战斗）
- dialogue-tension.md（对话张力）
- revelation.md（揭秘/反转）
- romance.md（感情线）
- training.md（修炼/升级）

## QMD 增量索引

`qmd update` 支持增量检测（"1 new, 0 updated, 178 unchanged"），写文件后执行：
```bash
qmd update        # 检测新增/修改
qmd embed -c <collection>  # 生成向量
```
不需要全量 rebuild。这是 `novel_ingest.py --sync-qmd` 的技术基础。
