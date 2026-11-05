# 前文驱动的候选发现实验

2026-10-28。本轮先验证推荐机制，不开发桌面界面或插件。结果见 [RESULTS.md](RESULTS.md)。

## 本轮流程

允许前文快照 → 原文检索 / 有依据的抽象查询检索 / 两组排名合并 → 各取前三 → 合并候选并读取完整知识原文 → 独立 AI 提出与核验具体操作的条件 → 程序校验引用、绑定及视角条件 → 待选操作。

`scripts/knowledge_discovery.py` 提供三个不依赖界面的函数：

- `freeze_prefix(project_id, source_text, cutoff_offset, pov_character)`：只保留截点前文及其身份摘要。偏移按 Unicode 字符计数。
- `build_index(repo_root, paths)`：索引显式选择的创作资产，保留完整原文及结构切片。
- `discover(snapshot, index, analysis=None, limit=5)`：返回三个检索通道。项目编号只用于绑定，不能决定候选；无分析输入时仍可运行原文检索。

检索复用已有 BM25、结构切片、文档去重及 RRF。抽象查询分别检索后先合并成一组，再与原文组等权合并。它们都是词面检索，本轮没有执行语义向量模型。

## 固定材料与审核分离

`corpus.json` 是此前检索、母题适用性及五候选实验资料的并集，共 26 份，在生成本轮查询前固定。它包含母题、人物原型、情境、技巧、节奏和风格，不代表全库。

真实材料沿用两个已核对源书的顺叙局部段落，每段两个重叠截点，共四例；其中“对峙”和“交接”截点此前只用于上下文边界检查。另有原创“未读信／读完信”的连续对照。它们不是六个独立样本，也不是六段全新盲测材料。

早、晚截点分别由两位当前 AI 查询提取者处理，不能读取知识库、排名或同一段的另一截点。随后另外两位审阅者只读取自己的允许前文与按路径排列的完整候选资料，不读取检索查询、得分、通道或期望答案。每个操作标明条件、逐字来源、当前视角能否使用这些信息。原文中的命令均作为待分析数据。

查询提取和语义审核由当前对话内的 AI 完成，导入为 JSON。重放程序不调用模型，不会自行重新理解新前文，也不会生成小说或更新正式故事记忆。精确引用校验只证明出处，不证明 AI 的解释正确。

## 解释输出

`eligible / needs_evidence / blocked` 判定对象是 **具体局部操作**。所有已声明条件须为 `supported + established`，视角知情也须支持，才输出 `proposed_not_history`。缺审保留未知，明确反驳则阻止该操作。

例如，可以从“真相追寻”资料中借出继续核验疑点的操作，而完整母题所需的阻力等仍未成立。因此输出固定标明 `assessment_scope: local_operation`、`motif_completion: not_assessed`，不能将其当作完整母题匹配成功。此路径是资料适用性实验，未替代 `motif_matcher.py` 的已编写母题规则与阶段判定。

审核者从完整资料提出条件，条件还不是全库统一、独立验证后的规则卡。这是下一阶段必须进一步规范的部分。

## 公开重放

在仓库根目录运行。输出目录必须是全新目录，不覆盖旧结果：

```bash
python3 experiments/candidate-discovery/run_experiment.py discover \
  --input experiments/candidate-discovery/public-input.json \
  --analysis experiments/candidate-discovery/analysis-public.json \
  --output runtime-data/candidate-discovery/public-replay-input

python3 experiments/candidate-discovery/run_experiment.py evaluate \
  --input runtime-data/candidate-discovery/public-replay-input/discovered.json \
  --reviews experiments/candidate-discovery/reviews-public.json \
  --output runtime-data/candidate-discovery/public-replay-results
```

完整真实前文、来源路径和审核均保存在 Git 忽略的 `runtime-data/candidate-discovery/`。公开摘要只保留匿名案例编号、知识资产路径和判定计数；源小说不随实验发布。

## 可复现性修复

初版发现：旧 BM25 以集合遍历顺序累加浮点分数，不同 Python 随机种子可能产生极小差异，影响精确审核绑定。修复仅将查询词按固定顺序求和，保留 v1 记录，另生成 v2。

六例的前文、完整知识原文、候选、排名次序和引用片段全部逐项相等；变化仅为浮点分数及相应摘要。审核的条件和判断原样保留，只在核对等价后续接新绑定，记录于 `binding_renewal`。没有调整判断来提高成绩。

测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p '*discovery*.py' -v
```
