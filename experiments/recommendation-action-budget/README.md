# 给当前动作分配候选名额

此模块复用 [十二卡共享索引实验](../recommendation-shared-index/README.md) 的前文、知识卡、审核状态和向量。新增可选策略 `action_compatible`；原来的 `global` 仍是默认策略。实际对照与限制见 [RESULTS.md](RESULTS.md)。

例如，前文已经写明主人公读懂取件编号，下一步可以使用它。两种策略都按同一完整目录计算相似度。原策略先取前两张卡，再检查它们能不能匹配“使用”。新策略先找出当前视角人物可推进的动作：只有同一变体同时匹配操作和已审核动作状态的卡，才能占用这两个名额。卡片能否用在这个故事里，仍由原文和角色知情审核决定。

| 规则 | `global` | `action_compatible` |
|---|---|---|
| 排序 | 完整知识目录 | 同一完整目录，沿用原分数与顺序 |
| 取前 `top_k` 张卡 | 先占名额，再检查动作 | 排除不兼容卡后再占名额 |
| 语义审核 | 每个有效的动作与卡片配对分别审核 | 相同 |
| 无可推进动作 | 可能返回卡片，不产生实例 | 返回空候选和空实例 |

BM25 没有正词面命中时不会填满名额；混合检索在完整榜单上融合，再筛选。一个项目内所有当前动作共享卡片名额；同一张卡与两个动作兼容时，要审核两个实例。不保证每个动作都能得到一个名额。

## 宿主调用

```python
request = prepare_recommendations(
    session, catalog, repo_root, top_k=2,
    retrieval_method="hybrid", embedding_artifact=artifact,
    candidate_policy="action_compatible",
)
# 仅审核 request["instances"]。审核时会按请求的策略重新生成候选，
# 并核对项目、版本、目录、状态和编码产物。
session = review_recommendations(
    session, request, instance_reviews, catalog, repo_root,
    embedding_artifact=artifact,
)
writer_input = session["current_batch"]["writer_packet"]
```

省略 `candidate_policy` 可沿用原接口。候选池和排序属于作者审计信息，写作模型只接收 `writer_packet`。切换名额策略无需重新编码知识或小说查询；新的请求和提案 ID 会反映不同的选择依据。

## 重放公开十例

在仓库根目录运行。以下关键词例子无需模型；准备目录必须是新目录。

```bash
export NOVEL_ACTION_RUN="$PWD/runtime-data/recommendation-action-budget/demo-source"
python3 experiments/recommendation-vector/run_experiment.py prepare \
  --fixtures experiments/recommendation-vector/fixtures-public.json \
  --state-reviews experiments/recommendation-vector/state-reviews-public.json \
  --catalog experiments/recommendation-shared-index/catalog-expanded.json \
  --output-dir "$NOVEL_ACTION_RUN"

python3 experiments/recommendation-action-budget/run_experiment.py replay \
  --run-dir "$NOVEL_ACTION_RUN" --method bm25 \
  --candidate-policy action_compatible \
  --candidate-reviews experiments/recommendation-action-budget/candidate-reviews-bm25-public.json
```

使用 `vector` 或 `hybrid` 时，需要与这些输入严格匹配的 `embeddings.json`。可以直接将 `--run-dir` 指向上一轮已完成的十二卡公开运行目录（本轮实际使用的方式），或按[共享缓存说明](../recommendation-shared-index/README.md)准备向量。相应地切换 `--method` 和同名审核文件。要比较基线，改为 `--candidate-policy global` 并使用 `experiments/recommendation-shared-index/candidate-reviews-<method>-public.json`。仅查看实际待审核包时用 `candidates` 子命令并省略 `--candidate-reviews`。

公开文件仅适用于同一目录、前文及完整实例审核包。使用别的小说时，应对新包重新审核；完整输出含作者原文，保存在本地忽略目录。新入口只提供读取现有实验的 `candidates` 和 `replay`，不启动模型或写入作品。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest discover \
  -s scripts/tests -p 'test_recommendation_action_budget*.py'
```
