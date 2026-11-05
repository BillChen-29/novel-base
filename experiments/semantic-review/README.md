# 事实审核 → 角色知情 → 后续计划（2026-10-25）

先看 [实际结果](RESULTS.md)：32 条候选、62 项知情主张已完成当前 AI 审阅，并进入真实推荐流程。

本轮新增“导入 AI 审核结果”的工作流。当前 AI 阅读固定截点前文，逐条判断候选事实和角色知情；程序验证审核是否属于同一个项目、同一份前文及同一个截点，然后将通过的内容送入原有推荐器。未调用额外模型接口。

## 这一步解决什么

此前，“引文在原文中”和“known_by 填了某个角色”就足以让候选进入推荐。这能检查引用位置，却不能说明引文真的支持候选，也不能说明角色确实知情。

新流程拆成两种判断：

| 判断 | 输出 | 用途 |
| --- | --- | --- |
| 这条候选是否被前文支持？ | 支持／矛盾／证据不足，以及确定事实／转述／推断／未明 | 只有“支持＋确定事实”进入可用事实集合 |
| 每个所列角色是否有依据知道它？ | 逐角色的支持／矛盾／证据不足 | 只保留审核支持的知情者；不会因角色在场而自动放行 |

“某人说过 X”“某人提出 X 假说”可以是已经发生的言说事件；这不等于 X 本身已被证实。证据不足的候选保存在审核记录中，不改写成假事实，也不进入写作输入包。

审核依据包含完整的允许前文，不能只看候选自带的一句引文。角色后来得知信息、信息尚未传达，以及相邻句中的否定，都可能改变结论。

## 可运行的接口

新模块位于 `scripts/semantic_review.py`：

1. `prepare_review`：按场景与字符截点产生审核包，包含候选、角色和允许原文。
2. `apply_review`：核对项目／审核包哈希、每条判断与精确证据，生成派生的已审核视图和隔离记录，不改原项目。
3. `run_reviewed_pipeline`：将派生视图送入真正的 `narrative_prototype.run_pipeline`，产生推荐、拒绝原因及实际写作输入。

缺审的事实或角色不会退回原标签。判断引用截点之后的内容、未知候选或角色，重复判断，错误的字符位置，以及修改前文后继续使用旧审核，都会被拒绝。被隔离的候选和审核理由不会混入 `writer_prompt`。如果某条线索的必要铺垫被隔离，该线索不能靠删掉条件重新获得揭示资格。

审核包的哈希证明输入与版本对应，不证明判断正确，也不是审核者身份认证。判断内容仍需接受作者或独立审阅者核查。

## 本轮样本和方法

- 三组可公开原创样本，18 条候选：铜钥匙、门内与门外、温热的门把。
- 两本本地小说各一个已审顺叙截点，14 条候选；原书与上一轮来源 SHA-256 一致。
- 总计 32 条候选、62 个角色知情主张。部分候选故意改成相反陈述、过早完成的事件或缺乏依据的结论。
- 输入冻结后，将事实编号替换成中性编号。独立 AI 审阅者只读取审核包，没有查看后文、推荐结果、编号映射或预设答案。
- 软件测试使用模拟审核响应，验证门控逻辑；本轮实验另行导入实际 AI 阅读产生的判断。两者分别记录。

实验对比审核前后的事实集合、角色知情范围和现有策略卡。关注错误前提是否被挡住、正确事实是否保留，以及实际写作提示中用了什么依据，不强求所有样本的排名改变。结果不是准确率评测；本轮没有独立人工金标。

## 无需下载小说的公开复跑

仓库中的 `fixtures.json` 是原创样本，`reviews-public.json` 是本轮 AI 对这些冻结输入作出的判断。以下是重放已有判断，不会重新调用模型：

```bash
python3 experiments/semantic-review/run_experiment.py prepare \
  --output runtime-data/semantic-review/public-input-new \
  --run-date 2026-10-25

python3 experiments/semantic-review/run_experiment.py evaluate \
  --input runtime-data/semantic-review/public-input-new \
  --reviews experiments/semantic-review/reviews-public.json \
  --output runtime-data/semantic-review/public-result-new \
  --run-date 2026-10-25
```

每次使用新目录。改变样本后，旧审核会失效，需要重新阅读新的 `review-input.json` 并生成匹配的新判断。

本地完整实验可在 `prepare` 时加 `--selection runtime-data/continuity-audit/source-selection.json --source-dir /path/to/local-novels`。详细前文、审核、引文与写作包仅保存在 `runtime-data/semantic-review/`，不会随仓库发布。公开摘要不包含小说片段或私人路径。

## 单项目使用

```bash
python3 scripts/semantic_review.py prepare \
  --project /path/to/story.json \
  --cutoff-scene-id s03 --cutoff-offset 600 \
  --output runtime-data/semantic-review/packet.json

# 当前 AI 或作者阅读 packet.json，另行提供 review.json。
python3 scripts/semantic_review.py recommend \
  --project /path/to/story.json \
  --packet runtime-data/semantic-review/packet.json \
  --review /path/to/review.json \
  --output runtime-data/semantic-review/recommendation.json
```

字符位置为原始文本解码后的 `[0, offset)`，不是字节位置。完整审核 JSON 的字段示例可见 `reviews-public.json`，各条证据必须精确匹配审核包中的场景文本。

## 当前范围

推荐仍使用原有四张策略卡：处理后果、对话试探、增加压力、揭示真相。分数仍是人工规则优先级。知识库中的母题、情境与变体条件没有在本轮变成自动判定规则，61 条分层提案仍待审。

这条新路径完成了“AI 审阅结果 → 来源校验 → 可用事实与知情范围 → 推荐输入”。默认写作主流程尚未自动调用语义模型，旧的 20 项自动能力审计仍保留 18 项通过、2 项未实现。下一步可用审核后的状态，逐条标注母题的适用条件、当前阶段和可承接变体，再测试候选匹配。
