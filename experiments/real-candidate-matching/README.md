# 真实前文的固定候选检验

2026-10-26。[实际结果](RESULTS.md)记录这一轮的失败、修正及最终对照；[数据契约 v0.1](FORMAT-v0.1.md)用于下一轮完整使用流程。

## 范围

使用此前核对过的两个真实小说截点和两个原创对照，共同检查五项资料：真相追寻、身份面具、模仿巫术、悬念阶梯、揭秘情境。它们分别属于母题、技巧与情境，类型保留到输出。本轮候选集由我们选定，未自动从全库召回，也未进行文学质量排名。

真实前文分别为 299 字的监控观察、1246 字的验尸推断。程序核对冻结项目哈希、源书完整哈希和局部片段的唯一连续位置。实际 AI 只获得允许前文和待审核命题；后续未进入审核输入。原文和完整审核保存在本机 `runtime-data/`。

条件准备器根据角色绑定与原文上下文生成待审核问题，作者无需逐字拼接条件文本。上下文只提供审阅位置，不能自动证明条件。缺失条件可以保持未知。条件满足后，还要检查当前角色是否知情，才能进入写作包。

## 不需要下载小说的复跑

```bash
python3 experiments/real-candidate-matching/run_experiment.py prepare \
  --run-date 2026-10-26 \
  --output runtime-data/real-candidate-matching/public-input-new

python3 experiments/real-candidate-matching/run_experiment.py evaluate \
  --input runtime-data/real-candidate-matching/public-input-new \
  --reviews experiments/real-candidate-matching/reviews-public.json \
  --run-date 2026-10-26 \
  --output runtime-data/real-candidate-matching/public-result-new
```

每次使用新目录。输出包含完整 JSON、无原文摘要和可展开的 HTML 报告。以上重放已保存的实际 AI 判断，不会调用模型或重新作出语义判断。

公开对照包含回溯描述，其全局顺序审核保留为证据不足；这里只核对当前状态，不把它们称为顺序衔接通过的样本。需要事件顺序的阶段仍必须提供发生锚点和顺序审核。

## 在本机加入两个真实截点

```bash
python3 experiments/real-candidate-matching/run_experiment.py prepare \
  --include-real --source-dir /path/to/local-novels \
  --run-date 2026-10-26 \
  --output runtime-data/real-candidate-matching/real-input-new
```

此命令复用此前冻结的 `runtime-data/semantic-review/2026-10-25-input-v1` 项目与来源哈希。只有源书匹配时才生成两个真实审核包。新克隆没有这些私人数据时，可以运行上面的公开对照。

两个分开的审核输入为 `review-input-real.json`、`review-input-public.json`，让独立审阅者只看对应材料。真实审核结果留在本机；评估时通过 `--reviews` 传入真实审核文件和公开审核文件。修改条件或前文后，需要与新审核包对应的判断，不能直接套用旧绑定。

## 可复用接口

- `knowledge_candidate_preparer.prepare_candidates`：实例化待审核条件，保留未绑定项；生成派生输入，不写正式记忆。
- `semantic_review.prepare_review / apply_review`：绑定项目与截点，审核事实及逐人知情。
- `motif_matcher.match_motifs`：执行进展阶段或独立操作入口的条件，区分共享前提和整体适用状态。
- `writer_packet`：只含当前视角可用事实和创作提案；本实验补入已审核的具体原始事实，避免只给出“已确认答案”却没有答案内容。

`recipes.py` 是本轮四个固定案例的人工／AI 辅助绑定，不是通用小说解析器。自由前文的归纳与候选绑定，在下一轮使用流程中由明确的审核步骤接入。

```bash
python3 -m unittest scripts.tests.test_knowledge_candidate_preparer \
  scripts.tests.test_motif_matcher scripts.tests.test_real_candidate_matching -q
```

源知识文档和正式写作主流程均未由本轮重写。下一轮直接整合导入、审核、选择、编辑与确认写回，不再另开同类孤立小样。
