# 架构 V3 — 项目配置优先设计

> 日期: 2026-05-09
> 核心变更: --platform 变为可选，项目级配置作为最高优先级

## 设计动机

当前 --platform 是必选参数（choices=["fanqie", "zhihu"]，default="fanqie"）。
这导致所有小说都被强制绑定到某个平台预设，独立小说也需要假装选择一个平台。

## 三层加载优先级

```
项目配置 00_memory/platform_config.json
    ↓ null/缺失
平台预设 assets/platforms/<name>/config.json
    ↓ 不存在
硬编码默认值
```

## --platform 参数变更

```python
# V2: 必选
choices=["fanqie", "zhihu"], default="fanqie"

# V3: 可选
choices=["fanqie", "zhihu", "standalone"], default=None
```

- `fanqie` → 用番茄预设初始化项目配置
- `zhihu` → 用知乎预设初始化项目配置
- `standalone` → 不生成配置文件，纯默认值
- 不指定 → 默认 fanqie，生成配置文件

## 项目级配置 Schema

`00_memory/platform_config.json`:

```json
{
  "_meta": {
    "version": 1,
    "created_at": "2026-05-09T20:00:00+08:00",
    "source": "platform_preset",
    "platform_base": "fanqie"
  },
  "platform": "fanqie",
  "avg_chars_per_chapter": 2500,
  "default_min_chars": null,
  "default_min_paragraphs": null,
  "default_min_dialogue_ratio": null,
  "default_max_dialogue_ratio": null,
  "default_min_sentences": null,
  "default_beat_count": null,
  "pacing_mode": null,
  "narrative_voice": null,
  "style_perspective": null
}
```

null 值表示"回退到平台预设/默认值"，允许部分覆盖。

## 三个新函数

1. `load_project_config(project_root)` — 读取项目配置
2. `resolve_platform_config(project_root, args_platform)` — 三层优先级解析
3. `save_project_config(project_root, platform_name, source, overrides)` — 保存配置

## 迁移步骤

### Phase 0: 前置准备
- 0.1: 创建 runtime-data/ 目录结构
- 0.2: 创建 assets/platforms/fanqie/config.json
- 0.3: 创建 assets/platforms/zhihu/config.json
- 0.4: pacing_template/ → pacing/ 重命名
- 0.5: .gitignore 追加 runtime-data/

### Phase 1: 核心改造
- 1.1: novel_ingest.py 第 41 行路径修复 + 第 43-49 行 TARGETS 更新
- 1.2: PLATFORM_PRESETS 改为 config.json 数据驱动（第 84-109 行）
- 1.3: genre-style-matrix.md 迁移到 platforms/fanqie/
- 1.4: 新增 load/resolve/save_project_config 三个函数
- 1.5: --platform 参数改为可选 + standalone
- 1.6: init_project_files() 生成 platform_config.json
- 1.7: continue_write() 读取项目配置

### Phase 2: db-maintain 实现
- 2.1: argparse 框架
- 2.2: list-assets 子命令
- 2.3: list-platforms 子命令
- 2.4: add-platform 子命令
- 2.5: validate 子命令
- 2.6: ingest --type web_novel 子命令

### Phase 3: 文档分流
- 3.1: B 类文件分类确认
- 3.2: zhihu-pacing-benchmark.md 迁移
- 3.3: .gitignore 追加

## 关键 Pitfall

- pacing_template 是通用理论，不是平台专属，不应移到 platforms/
- PLATFORM_PRESETS 从硬编码改为函数加载，需保持向后兼容
- null 值语义：字段为 null 时回退到下一层，不是使用 null
- 旧项目没有 platform_config.json 时正常回退到平台预设
