# 共享知识向量与独立项目查询

本轮在本地向量入口前增加可复用缓存，不改变推荐核心的动作、事实、知情、采纳和旧版本拒绝规则。结果见 [RESULTS.md](RESULTS.md)。

## 两类缓存

通用知识索引只存知识卡的标题、检索描述、原始向量、内容散列和来源作业散列。相同编码配置和相同内容只需编码一次；卡片 ID 不同但标题及描述相同可以共用向量。修改标题或描述产生新内容 ID。旧文档可以留存，实际排名只使用当前目录里的卡片。

查询快照独立保存，绑定项目 ID、正文版本和散列、已审状态、完整目录、实际查询文本和编码配置。即使两个项目写出相同查询，也不能跨项目复用。正文版本、状态或目录变化时需要重新编码该项目的查询。缺少这些绑定的输入会被拒绝。

共享索引不保存项目正文、查询文本或项目身份。混合编码任务及查询快照包含私有输入，必须留在本地 `runtime-data/`。模型为已缓存的 EmbeddingGemma 300M Q8_0、768 维，沿用上一轮固定的 QMD 2.1.0 和 node-llama-cpp 3.18.1 配置。

## 宿主 API

将 `scripts` 加入 Python 模块搜索路径：

```python
from recommendation_engine import prepare_retrieval_embeddings
from recommendation_embedding_cache import plan_embeddings, complete_embeddings

bundle = prepare_retrieval_embeddings(session, catalog, repo_root)
plan = plan_embeddings(bundle, knowledge_index, private_query_snapshot)
# plan["embedding_input"]["items"] 非空时，保存 dataset.json、
# embedding-input.json，再由本地编码脚本生成 embeddings.json。
# 三个解析后的 JSON 组成 delta_artifact；全命中时传 None。
result = complete_embeddings(
    bundle, knowledge_index, private_query_snapshot, delta_artifact,
)
knowledge_index = result["index"]
private_query_snapshot = result["query_snapshot"]
artifact = result["artifact"]
# 把 artifact 传给原有 prepare_recommendations / review_recommendations。
```

`empty_index()` 创建空索引。`import_artifact(bundle, old_artifact, index)` 先完整验证上一版产物，再提取知识向量和当前项目的查询快照；无需重新运行模型。来源摘要指向原始编码作业。组装产物明确标记 `assembly`，不把旧耗时等记录伪装成一次新的全量编码。

函数不执行文件、模型或网络操作，不修改输入对象。同一文档 ID 导入不同原始向量会报冲突；损坏行（包括当前未使用的行）、非法向量、错误模型配置和不完整编码均被拒绝。散列用于一致性检查，不证明是谁生成了内容。

## 本地命令

以下在仓库根目录运行。`BUNDLE` 指向上一轮 `run_experiment.py prepare` 生成的某个 case 目录，其内有 `dataset.json` 和 `embedding-input.json`。

```bash
export NOVEL_CACHE_RUN="$PWD/runtime-data/recommendation-shared-index/my-run"

# 首次不传 --index 和 --query-snapshot；后续传上一次完成的快照。
python3 experiments/recommendation-shared-index/cache_cli.py plan \
  --bundle-dir "$BUNDLE" \
  --output-dir "$NOVEL_CACHE_RUN/job"

# 仅当 plan 返回的 stats.total_inputs > 0 时执行：
node scripts/retrieval_pilot_embed.mjs \
  --input "$NOVEL_CACHE_RUN/job/embedding-input.json" \
  --output "$NOVEL_CACHE_RUN/job/embeddings.json" \
  --model "$HOME/.cache/qmd/models/hf_ggml-org_embeddinggemma-300M-Q8_0.gguf" \
  --qmd-root /opt/homebrew/lib/node_modules/@tobilu/qmd \
  --gpu metal --threads 4

python3 experiments/recommendation-shared-index/cache_cli.py complete \
  --job-dir "$NOVEL_CACHE_RUN/job" \
  --output-dir "$NOVEL_CACHE_RUN/completed"
```

完成目录包含 `knowledge-index.json`、`query-snapshot.json`、`artifact.json`、`stats.json`。后续 `plan` 可加 `--index .../knowledge-index.json --query-snapshot .../query-snapshot.json`；输出须换用新目录。已有完整旧产物可使用 `import --bundle-dir OLD --output-dir NEW [--index INDEX]`。

CLI 在完整验证后创建新目录，拒绝覆盖、路径越界及符号链接输出。目录权限为 0700，文件为 0600；通过目录文件描述符写入，最后发布清单。失败后没有完整清单的目录不能继续使用。每个输出是独立快照，宿主负责选择当前版本；没有并发覆盖同一个全局索引的功能。文件操作依赖本轮 macOS 的 POSIX 接口，尚未适配 Windows。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest discover \
  -s scripts/tests -p 'test_recommendation_embedding_cache*.py'
```

## 实验与规模边界

[catalog-expanded.json](catalog-expanded.json) 保留原四卡，加入八张有精确来源的实验卡。[catalog-notes.json](catalog-notes.json) 区分源文结构与作者设计的适用门槛。这些新卡用于检索竞争和实际候选审核，不表示八种模式已全部经过正例验证。默认 `recommendation/action-catalog.json` 保持原样。

本轮实现的是增量编码和内容复用。索引仍是 JSON 快照，读取、校验和排序仍遍历数据；不是已经验证的大规模向量数据库。没有自动回收旧内容，也没有自动合并并发分支。扩大长篇使用时还需评测磁盘、内存和索引更新成本。
