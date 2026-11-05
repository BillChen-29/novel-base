# 小规模检索实验

这个模块用现有原始资料测试检索与切片方式，帮助确定下一步需要统一哪些字段。它与[离线叙事推荐小样](../../examples/narrative-prototype/README.md)分别运行，尚未把检索结果接入自动续写。

先读[本轮结果与格式建议](RESULTS.md)。样本、查询和原文引文固定在 [fixture.json](fixture.json)，标注口径见 [LABELS.md](LABELS.md)，可提交的数值摘要见 [results-summary.json](results-summary.json)。

## 比较什么

- 同一批 20 篇资料、24 条查询；开发组 12 道有答案题＋2 道无答案题，保留组 8＋2。
- 固定窗口：每块最多 800 个 Unicode 字符，重叠 120 字符。
- 结构分块：按 Markdown 标题和行首加粗字段划分；长小节再按最多 800 字符、重叠 120 字符切开，优先段落或换行；不跨小节拼接。两种方案同时改变边界、长度和上下文保留量。
- 关键词基线：本脚本实现的中文双字 BM25（k1=1.2，b=0.75），并非 QMD 原生 FTS。英文按词匹配。
- 向量检索：本机已有的 EmbeddingGemma 300M Q8_0，768 维；逐块余弦相似度精确排序。本轮没有建立近似最近邻数据库。
- 混合检索：各路先按文档去重，再以 RRF（k=60）融合。最终每份文档只展示一个片段，选择单路排名较高的片段；平局保留 BM25 片段。没有合并证据、重排或查询扩展。

文档编码输入使用 QMD 的 `title: ... | text: ...`，查询使用 `task: search result | query: ...`；BM25 也读取标题和正文。标题层级保留为元数据，没有额外拼入编码文本。

## 在桌面仓库复跑

以下命令在仓库根目录执行，需要 Python 3.10+、Node.js、已经安装的 QMD 及其 `node-llama-cpp` 依赖、已经下载的本地 GGUF 模型。本轮实际环境为 QMD 2.1.0、node-llama-cpp 3.18.1、Metal；脚本不自动安装或下载依赖。

每次新实验选择一个空目录；保留旧目录方便对照。

```bash
cd /path/to/novel-base

python3 scripts/retrieval_pilot.py prepare \
  --fixture experiments/retrieval-pilot/fixture.json \
  --output-dir runtime-data/retrieval-pilot/pilot-v2

node scripts/retrieval_pilot_embed.mjs \
  --input runtime-data/retrieval-pilot/pilot-v2/embedding-input.json \
  --output runtime-data/retrieval-pilot/pilot-v2/embeddings.json \
  --model "$HOME/.cache/qmd/models/hf_ggml-org_embeddinggemma-300M-Q8_0.gguf" \
  --qmd-root /opt/homebrew/lib/node_modules/@tobilu/qmd \
  --gpu metal --threads 4

python3 scripts/retrieval_pilot.py evaluate \
  --output-dir runtime-data/retrieval-pilot/pilot-v2
```

其他机器需要替换实际安装和模型路径；无 Metal 时可用 `--gpu false`，并要求已经有兼容的预编译运行库。本轮结果仍以记录的 Metal 环境为准。

如只改报告或评分代码，用已有 `pilot-v1` 目录执行最后一条 `evaluate` 即可，无需重新编码。修改资料、查询、分块或编码参数时，建立新实验目录。

编码中途退出后可复用每 8 条保存的 checkpoint。若留下 `embedding.lock`，再次运行会检查锁的 PID：进程已退出时，错误信息给出带唯一令牌的 `retrieval_pilot_lock.mjs recover` 命令，执行后再重试。活跃或无法确认的锁不会删除；旧版空锁需核实所有者，或直接使用新的实验目录。

## 输出与核查

输出目录包含 `dataset.json`（原文片段、位置和来源哈希）、`embedding-input.json`、`embeddings.json`、`results.json` 和独立的 `report.html`。HTML 可直接用浏览器打开，也可在本机预览：

```bash
python3 -m http.server 8766 --bind 127.0.0.1 \
  --directory runtime-data/retrieval-pilot/pilot-v1
```

然后访问 `http://127.0.0.1:8766/report.html`。如果端口已被本次报告服务占用，直接打开地址即可。

所有生成数据写入已被 Git 忽略的 `runtime-data/`。原始 `assets/` 只读；脚本调用本地模型和 QMD 的文本格式函数，不使用现有 QMD 数据库或索引。向量数据不是源数据，应能从资料、参数和模型重建。

每个片段包含 `document_id`、`chunk_id`、`source_path`、`source_sha256`、字符区间 `[start,end)`、1 起算的原文行号、`title`、`heading_path`、`text`、`scope`、`project_id`、`chunker_version`。当前所有片段均为共享创作知识（`scope=shared`），没有导入任何小说项目的故事记忆。

指标口径：Recall/MRR 以 Top-5 不重复文档计算；引文覆盖按唯一 `(path, quote)` 精确匹配后逐题平均，齐备率计算所有标注引文均出现的题目比例。无答案题单独报告返回行为。精确引文指标用于定位缺失上下文，不等于答案质量；相关性和引文仍需要作者复核。

## 离线测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s scripts/tests -p 'test_retrieval_pilot*.py' -v

node --test scripts/tests/test_retrieval_pilot_lock.mjs
```

标签由代理依据资料编写，存在选材和措辞偏差。小样用于形成下一版实验假设，不能据此宣称全库召回率、真实用户效果或续写质量。源文中的平台统计、案例和创作判断也未因被检索而获得事实验证。
