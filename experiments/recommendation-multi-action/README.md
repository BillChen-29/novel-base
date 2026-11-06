# 小说推荐核心验收与复现

[验收报告](RESULTS.md)记录了前文审核、知识检索、动作推荐、作者采纳、节奏建议、续写交接和正文更新的实测结果。[一次实际续写](writing-handoff.json)可以查看作者选择、写作输入、新正文和下一轮判断。

## 一次重放六组公开对照

在本机仓库根目录运行。该命令读取已有向量、六个原创截点和已保存的语义审核，分别执行三种检索方法和两种候选策略，并逐项校验输出。

```bash
python3 experiments/recommendation-multi-action/replay.py \
  --run-dir runtime-data/recommendation-multi-action/2026-11-06-v1/public \
  --expect experiments/recommendation-multi-action/results-public.json
```

在新设备上，可使用以下命令从本目录的原创资料准备输入，然后按[共享知识索引说明](../recommendation-shared-index/README.md)为每个截点准备与输入绑定的 `embeddings.json`。已有相同模型和知识索引时，每个新截点仅需编码自己的查询。`candidate-reviews-public.json` 按完整审核包去重。

```bash
export NOVEL_MULTI_RUN="$PWD/runtime-data/recommendation-multi-action/my-source"
python3 experiments/recommendation-vector/run_experiment.py prepare \
  --fixtures experiments/recommendation-multi-action/fixtures-public.json \
  --state-reviews experiments/recommendation-multi-action/state-reviews-public.json \
  --catalog experiments/recommendation-shared-index/catalog-expanded.json \
  --output-dir "$NOVEL_MULTI_RUN"
```

## 对接宿主

`prepare_recommendations` 提供三种 `candidate_policy`。`global` 使用全局前列。`action_compatible` 在完整榜单上选择可匹配当前动作的卡。`action_coverage` 在相同卡数上限内优先选择可以覆盖更多尚未获得候选的动作的卡，同样的增益按原排名选择，最后按原序提交审核。每个动作与卡片的组合各自审核。同一张卡可以服务两个动作。

采纳之后，宿主可以给作者显示场景级节奏参考。例如 `threads` 指定作者打算继续处理的线索，其中的铺垫或答案 ID 必须来自当前已审且视角人物知情的基础事实。

```python
from recommendation_scene_advice import prepare_scene_advice
from recommendation_session import source_token

advice = prepare_scene_advice(
    accepted_session, proposal_id, repo_root,
    expected_token=source_token(accepted_session),
    expected_batch_sha256=accepted_session['batch_sha256'],
    goal_id='recover_and_investigate', threads=threads,
)
```

作者侧输出列出策略、排序依据和来源。策略使用场景强度、作者目标、已知铺垫和揭示许可计算。写作端使用当前批次的 `writer_packet` 和作者选中的提案。新的正文进入 `append_scene` 后，宿主重新整理并审阅该版本的事实与动作。会话、知识向量和审核判断均可由宿主分别保存。

核对新接口的针对性测试可以在仓库根目录执行。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest discover \
  -s scripts/tests -p 'test_recommendation_multi_action.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python3 -m unittest discover \
  -s scripts/tests -p 'test_recommendation_scene_advice.py'
```
