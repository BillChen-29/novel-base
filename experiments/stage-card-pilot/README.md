# 阶段卡实验

本轮验证当前状态与下一步动作，结果见 [RESULTS.md](RESULTS.md)，数据说明见 [FORMAT-v0.2.md](FORMAT-v0.2.md)。

目录包含四卡 `catalog.json`、预先固定的 `PLAN.md`、六个原创连续截点 `fixtures-public.json`、当前 AI 审核 `reviews-public.json`、两项裁定及匿名结果。真实小说选段和完整运行数据存于仓库忽略的 `runtime-data/stage-card-pilot/`。

## 重跑公开六例

从仓库根目录执行。输出目录必须尚未存在。Python 使用标准库；向量步骤使用已经安装的本地 QMD、node-llama-cpp 与模型，不自动安装或联网下载。

```bash
python3 experiments/stage-card-pilot/run_experiment.py prepare \
  --output runtime-data/stage-card-pilot/public-replay-input

python3 experiments/stage-card-pilot/run_experiment.py inputs \
  --prepared runtime-data/stage-card-pilot/public-replay-input/prepared.json \
  --reviews experiments/stage-card-pilot/reviews-public.json \
  --output runtime-data/stage-card-pilot/public-replay-vector

/opt/homebrew/bin/node scripts/retrieval_pilot_embed.mjs \
  --input runtime-data/stage-card-pilot/public-replay-vector/embedding-input.json \
  --output runtime-data/stage-card-pilot/public-replay-vector/embeddings.json \
  --model "$HOME/.cache/qmd/models/hf_ggml-org_embeddinggemma-300M-Q8_0.gguf" \
  --qmd-root /opt/homebrew/lib/node_modules/@tobilu/qmd \
  --gpu metal --threads 4

python3 experiments/stage-card-pilot/run_experiment.py evaluate \
  --prepared runtime-data/stage-card-pilot/public-replay-input/prepared.json \
  --reviews experiments/stage-card-pilot/reviews-public.json \
  --run-dir runtime-data/stage-card-pilot/public-replay-vector \
  --output runtime-data/stage-card-pilot/public-replay-results
```

以上路径对应本轮 macOS 本地配置：QMD 2.1.0、node-llama-cpp 3.18.1，4 线程、2048 上下文。模型 SHA-256 固定为 `b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63`。超长输入会拒绝，不静默截断。

重放导入既有 AI 审核，不重新进行语义分析。各项目和截点的内容绑定、源文引文、模型及向量输入都会重新核验。

## 调用边界

`prepare_cases` 对所有案例使用同一组卡，不按案例挑选候选；所有前文在调用前已经截断。`prepare_embedding_inputs` 根据完整原文和审核后的基础事实生成两组查询。`evaluate_run` 排序后只输出对应路线实际取回且满足条件的提案。

完整池诊断位于 `cases[].assessed_pool`；真正允许交给写作方的内容位于 `cases[].methods[method].writer_packet`，并明确 `memory_write_allowed: false`。完整池诊断不能作为漏检路线的补充答案。

新代码是实验适配层，复用旧核验器；还不是可安装插件。自动状态抽取、具体动作绑定、作者采纳后的正文与记忆更新需继续验证。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s scripts/tests -p test_stage_card_pilot.py
```
