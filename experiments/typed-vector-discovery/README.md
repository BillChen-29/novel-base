# 分类型检索与本地向量实验

结果见 [RESULTS.md](RESULTS.md)。本目录比较相同前文与查询下的关键词、向量、混合排序，以及全局结果和母题／情境分类结果。完整池审核和实际检索命中分别保存，不能用审核答案给漏检方法补候选。

## 输入与文件

- `input-public.json`：两个原创连续截点及上一轮已冻结的查询。原文、项目身份、截点和查询证据都有内容绑定。
- `assessment-protocol.json`：当前结构、特定片段、证据不足、矛盾及人物知情的判定约定。
- `reviews-public.json`：当前 AI 的审核结果；重跑会检查来源，但不会重新调用 AI。
- `adjudication.json`：独立复核后发生的三项修订，原始审核另存于本地忽略目录。
- `results-summary.json`：六例匿名结果；`public-results-summary.json`：两例原创数据的独立重放。
- 固定资料清单沿用 `../candidate-discovery/corpus.json`，共 26 份。完整评审覆盖其中 12 份母题／情境；其他类型没有本轮语义准确率标签。

## 重跑公开案例

从仓库根目录执行。每次使用一个未存在的输出目录。Python 使用标准库；向量步骤依赖已经安装的本地 QMD、node-llama-cpp 和指定 GGUF 文件，不自动联网安装。

```bash
python3 experiments/typed-vector-discovery/run_experiment.py prepare \
  --cases experiments/typed-vector-discovery/input-public.json \
  --output runtime-data/typed-vector-discovery/public-replay

/opt/homebrew/bin/node scripts/retrieval_pilot_embed.mjs \
  --input runtime-data/typed-vector-discovery/public-replay/embedding-input.json \
  --output runtime-data/typed-vector-discovery/public-replay/embeddings.json \
  --model "$HOME/.cache/qmd/models/hf_ggml-org_embeddinggemma-300M-Q8_0.gguf" \
  --qmd-root /opt/homebrew/lib/node_modules/@tobilu/qmd \
  --gpu metal --threads 4

python3 experiments/typed-vector-discovery/run_experiment.py evaluate \
  --run-dir runtime-data/typed-vector-discovery/public-replay \
  --reviews experiments/typed-vector-discovery/reviews-public.json \
  --output runtime-data/typed-vector-discovery/public-replay-results
```

以上路径是本轮 macOS 本地环境的配置。模型文件 SHA-256 固定为 `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63`。实际编码使用 QMD 2.1.0、node-llama-cpp 3.18.1、Node 26.0.0，Metal，4 线程，2048 上下文，768 维。长输入会拒绝，不会静默截断。

公开案例只有 2 个截点，因此实际编码为 339 个资料片段加 4 个查询输入，共 343 个；完整六例是 357 个。公开案例预期没有当前母题／情境结构阳性，召回率为 null，不应强行生成母题承接。

## 结果边界与模块接口

`scripts/typed_knowledge_discovery.py` 提供 `prepare_embedding_dataset` 与 `rank_typed` 两个纯函数：输入源资料、独立故事快照、查询及向量，返回带来源的六路排名；不访问网络、不修改记忆，也不依赖前端。它是可复用引擎的一部分，还不是安装型插件。

`run_experiment.py` 校验语料清单、实际输入文件散列、完整向量 ID、模型指纹、审核包及引文，再生成：

- `rankings`：六路全局与分类候选。
- `judgments`：完整母题／情境池的导入审核。
- `assessed_pool_proposals`：全池中有依据的未来提案，仅作评估参考。
- `retrieved_proposals_by_method`：对应方法实际取回且审核允许的提案。不能借用完整池答案补齐漏检。
- `summary`：匿名结果，未知与未评审分开；没有阳性的案例召回率为 null。

所有提案均为待选未来内容，`memory_write_allowed` 为 false。后续若接受提案、生成正文并更新故事记忆，还需要单独验证这一闭环。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p 'test_typed_*.py'
```

单元测试验证输入、隔离、证据和排序契约；推荐效果以实际实验和审核结果为依据。
