# novel-creator-skill v8.0 参考手册

> Phase 0 探针验证结果（2026-05-06）
> 仓库：https://github.com/leenbj/novel-creator-skill
> 安装路径：~/.hermes/skills/novel-creator-skill

## 核心脚本速查

```bash
# 一键开书
python3 scripts/novel_flow_executor.py one-click \
  --project-root <dir> --title <title> --genre <genre> --idea <idea>

# 继续写作（全链路）
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <dir> --query "<新剧情>"

# 门禁检查（纯本地，不走 API）
python3 scripts/chapter_gate_check.py \
  --project-root <dir> --chapter-file <file>

# RAG 索引构建/查询
python3 scripts/plot_rag_retriever.py build --project-root <dir>
python3 scripts/plot_rag_retriever.py query --project-root <dir> --query "<query>" --top-k 4

# 风格指纹提取
python3 scripts/style_fingerprint.py --profile-name <name> <files...>

# 知识图谱
python3 scripts/story_graph_builder.py add-node --project-root <dir> --type character --name "<name>"
python3 scripts/story_graph_builder.py export --project-root <dir> --format mermaid

# 大纲锚点
python3 scripts/outline_anchor_manager.py init --project-root <dir>
python3 scripts/outline_anchor_manager.py check --project-root <dir> --chapter-num 5

# 章节写作（多 LLM）
python3 scripts/novel_chapter_writer.py --project-root <dir> --provider kimi --dry-run

# 一键写书调度
python3 scripts/auto_novel_writer.py plan --synopsis "<简介>" --target-chars 2000000 --genre <genre>
python3 scripts/auto_novel_writer.py run --project-root <dir> --synopsis "<简介>"
```

## 门禁流程（6 步）

1. `/更新记忆` → `memory_update.md`
2. `/检查一致性` → `consistency_report.md`
3. `/风格校准` → `style_calibration.md`
4. `/校稿` → `copyedit_report.md` + `publish_ready.md`
5. `/门禁检查` → `gate_result.json`（passed=true 才解锁下一章）
6. 失败时 → `repair_plan.md`

## 两级 RAG 检索

- **粗筛：** BM25 风格 TF-IDF，取 candidate-k（默认 8）候选
- **精排：** 片段级语义重排，返回 top-k（默认 4）结果
- **条件触发：** 轻场景（日常/过渡）自动跳过检索
- **查询缓存：** 相同 query 命中缓存跳过重算

## style_anchor.md 模板字段

```markdown
## 风格DNA
- 叙事视角：人称 / 叙事距离 / 时态
- 句式特征：平均句长 / 长短句比例 / 段落平均长度 / 对话占比
- 语言风格：用词倾向 / 修辞密度 / 感官偏好 / 幽默程度
## 风格样本（3-5段）
- 样本1：动作/战斗场景
- 样本2：日常/对话场景
- 样本3：心理/内心独白
```

## 依赖

- Python 3.9+（纯标准库，零外部依赖）
- 10 个回归测试：`PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_novel_flow_executor.py`
