# 推荐核心的本地向量接入

这一版在原有可嵌入核心中增加 `vector` 与 `hybrid` 两种检索入口。默认仍为 `bm25`，已有审核、采纳与版本控制保持兼容。向量只决定取回哪些卡片，不能代替动作状态、指代、角色知情和承接条件的判断。

结果见 [RESULTS.md](RESULTS.md)。本轮没有构建界面、调用远程模型或更改 QMD 的 collection/SQLite 索引。

## 宿主接口

从仓库 `scripts` 导入 `recommendation_engine`：

```python
bundle = prepare_retrieval_embeddings(session, catalog, repo_root)
# 用 recommendation_retrieval.encoded 将两项保存成邻接文件：
# dataset.json 和 embedding-input.json，然后调用已有本地编码脚本。
artifact = {
    "dataset": dataset_json,
    "embedding_input": input_json,
    "embeddings": embeddings_json,
}
request = prepare_recommendations(
    session, catalog, repo_root, top_k=2,
    retrieval_method="hybrid", embedding_artifact=artifact,
)
# 宿主仅审核 request.instances；相同实例包可复用相同审核。
session = review_recommendations(
    session, request, imported_reviews, catalog, repo_root,
    embedding_artifact=artifact,
)
writer_input = session["current_batch"]["writer_packet"]
```

`prepare_retrieval_embeddings` 不启动模型。本轮它导出目录中四张卡的标题／检索描述，以及当前已审且视角人物知情的基础事实查询。正文原文、未审命题、卡片条件问题、提案和作者采纳意图均不进入查询。

| 方法 | 排序依据 | 取回后怎样处理 |
|---|---|---|
| `bm25` | 现有中文二元词／英文词面匹配 | 无词面命中允许返回空集合 |
| `vector` | 本地向量归一化后的余弦相似度 | 最近邻仍需通过原有全部条件 |
| `hybrid` | 完整关键词榜单与完整向量榜单的 RRF，参数 60 | 融合后再统一截取 `top_k` |

分数不是语义正确性或文学质量概率。缺失／损坏缓存会报错，不会悄悄切换检索方法。空基础状态查询返回空候选；非空查询但 `top_k=0` 仍会校验向量缓存。

## 本地重放

需已安装 Node、QMD 及 node-llama-cpp，且模型已下载。本轮固定：QMD **2.1.0**、node-llama-cpp **3.18.1**、EmbeddingGemma 300M Q8_0、**768 维**；模型 SHA-256 为 `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63`。其他模型或 formatter 版本需要重新定义并验证编码契约。

以下在仓库根目录运行；每次准备新实验使用一个尚不存在的目录。

```bash
export NOVEL_VECTOR_RUN="$PWD/runtime-data/recommendation-vector/my-run"

python3 experiments/recommendation-vector/run_experiment.py prepare \
  --fixtures experiments/recommendation-vector/fixtures-public.json \
  --state-reviews experiments/recommendation-vector/state-reviews-public.json \
  --output-dir "$NOVEL_VECTOR_RUN"

# 对 prepare 返回的每个 case 运行一次，下面以 letter_1 为例。
node scripts/retrieval_pilot_embed.mjs \
  --input "$NOVEL_VECTOR_RUN/letter_1/embedding-input.json" \
  --output "$NOVEL_VECTOR_RUN/letter_1/embeddings.json" \
  --model "$HOME/.cache/qmd/models/hf_ggml-org_embeddinggemma-300M-Q8_0.gguf" \
  --qmd-root /opt/homebrew/lib/node_modules/@tobilu/qmd \
  --gpu metal --threads 4

python3 experiments/recommendation-vector/run_experiment.py candidates \
  --run-dir "$NOVEL_VECTOR_RUN" --method vector

python3 experiments/recommendation-vector/run_experiment.py replay \
  --run-dir "$NOVEL_VECTOR_RUN" --method vector \
  --candidate-reviews experiments/recommendation-vector/candidate-reviews-vector-public.json
```

将 method 和审核文件中的 `vector` 同时改成 `bm25` 或 `hybrid` 即可对照。BM25 重放无需编码；向量／混合重放前必须完成所有公开 case 的编码。保存的候选审核只适用于这些固定输入，改小说或资料后需重新生成并审核实例。编码脚本使用已有本地模型，禁止自动下载／构建，输入过长明确报错，不静默截断。

运行器在全量验证输入后，才创建 `runtime-data` 下的新目录；拒绝覆盖和符号链接绕过。`candidates` 与 `replay` 只读输入并输出 JSON。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest discover \
  -s scripts/tests -p 'test_recommendation*.py'
```

## 缓存和证据边界

缓存绑定项目 ID、正文版本／散列、已审状态、目录、准确查询和卡片文本。模型、维数、formatter 与运行时版本也须匹配；不完整、缺行、多行、错误维数、零向量、布尔或非有限数值均被拒绝。即使改动后的向量碰巧给出相同排序，原审核请求也不能继续使用。

每种方法只审核自己实际取回且动作门槛允许的实例。向量内容留在本地缓存，作者审计保留排序与来源散列，写作输入仍只有已审命题、匿名证据引用和未来提案。哈希用于一致性核对，不认证审核者身份。

## 当前规模

这一版先按正文截点保存独立向量快照，四张卡在每个快照中重新编码。它尚未实现跨版本共享知识索引或增量复用；未来扩大知识库时需补这一层，避免重复编码全部卡片。已核验状态查询也仍由当前 AI 整理和审核后导入。当前成果是向量检索进入了同一条可检查的推荐流程，不是全库自动化或长篇效率已经验证。
