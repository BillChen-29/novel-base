# 真实前文、母题分层与记忆能力审计

2026-10-24 更新：已完成第一轮续写边界修复，当前能力审计为 18 PASS / 2 FAIL。请先读 [修复结果与用法](REPAIR-2026-10-24.md)。以下保留 2026-10-19 的实验背景与复现流程。

2026-10-19。本轮回答三个问题：现有母题资料能否拆成不同作用的数据；原有历史检索、图谱和事实引用能否支持有截点的续写；用真实小说前文检索时会发生什么。

先看 [RESULTS.md](RESULTS.md)。知识分层提案见 [KNOWLEDGE-SPLIT.md](KNOWLEDGE-SPLIT.md)，带原文位置的数据见 [knowledge-map.json](knowledge-map.json)。这些分类尚未接入自动写作。

## 本轮产物

| 内容 | 位置 | 状态 |
| --- | --- | --- |
| 10 份资料的来源核对、61 条分层记录 | `knowledge-map.json` | 分类与条件是待审提案，153 条唯一引文定位已验证 |
| 现有代码的 20 项能力审计 | `audit_runtime.py` | 7 PASS / 13 FAIL / 0 ERROR；真实缺口保留为失败 |
| 两本小说、四个截点的检索实验 | `../../scripts/continuity_experiment.py` | 全本地 BM25 与向量检索；不生成小说 |
| 可提交的无正文结果摘要 | `experiment-summary.json`、`runtime-summary.json` | 不含小说全文、前文片段或封存后文 |
| 完整选段、引文、排名和 HTML | `../../runtime-data/continuity-audit/` | 本地生成，Git 忽略 |

2026-10-19 基线试验在原 novel-base 内运行，当时未修改生产检索／写作模块或原始 assets，使用独立项目快照避开未来文本。2026-10-24 已修复主要时点与提示传递缺口；事实语义和知情标注核验仍未实现。

## 复现

从仓库根目录执行。能力审计使用合成样本，不需要小说或模型：

```bash
python3 experiments/continuity-audit/audit_runtime.py --report-dir runtime-data/continuity-audit/recheck
```

这是保留的旧接口调用方式；其结果不能直接与新接口的 18 / 2 结果混比。2026-10-19 基线记录了 13 项未满足要求。新接口复验须添加 `--current-contract --run-date 2026-10-24`，仍因两项语义能力缺口返回非零退出码。它是显式运行的能力审计，不放进普通回归测试发现目录，不使用 `expectedFailure` 隐藏缺口。

实验工具的契约测试应通过：

```bash
python3 -m unittest scripts.tests.test_continuity_experiment -v
```

真实小说实验需要本地 `source-selection.json`、其所指向的合法可用 TXT 文件，以及已安装的 QMD 运行库和已缓存 GGUF。这些本地材料未随仓库发布；只克隆仓库不能重跑同一小说样本。本地数据契约包含来源 SHA-256、原始解码字符位置、顺序审阅、前文、单独后文、人物稳定 ID、带引文和信息类型的状态标注。更换材料需重新逐段审阅，不能只替换书名。

```bash
python3 scripts/continuity_experiment.py prepare \
  --selection runtime-data/continuity-audit/source-selection.json \
  --output-dir runtime-data/continuity-audit/run-v2

node scripts/retrieval_pilot_embed.mjs \
  --input runtime-data/continuity-audit/run-v2/embedding-input.json \
  --output runtime-data/continuity-audit/run-v2/embeddings.json \
  --model "$NOVEL_EMBEDDING_MODEL" --qmd-root "$NOVEL_QMD_ROOT" \
  --gpu metal --threads 4

python3 scripts/continuity_experiment.py evaluate \
  --output-dir runtime-data/continuity-audit/run-v2
```

两个环境变量分别指向已有模型文件和 QMD 安装目录。工具不下载模型。每轮使用新运行目录；已评价的前文快照不覆盖。输入与资料哈希改变时拒绝继续评价。封存后文没有进入向量输入；离线后文对照在输入冻结后完成，也未反哺查询。

## 阅读结果时的边界

- 178 个原条目、791 个情境／案例段是按来源标题结构抽取的候选，并非已审校的 178 个纯母题和 791 个纯情境。
- 四个截点来自两个局部事件段，同书截点共享前缀，不是四个独立泛化样本。
- 本轮状态由 AI 代理阅读标注，没有实现自动状态抽取，也没有独立人工相关性金标。
- 历史检索每个项目只含一个连续片段，因此只能检查接口与片段覆盖，不能证明长篇小说检索质量。
- 图谱内容由实验标注种入。引文检查只检查位置和字符串，不证明事实语义、角色知情标注正确。
- 向量余弦分数不是母题适用概率。原作者后续也不是唯一合理续写。
