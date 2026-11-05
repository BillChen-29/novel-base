# 可嵌入的推荐核心 v0.3

这一版把阶段卡实验接成了独立项目内的完整流程：前文 → 已审基础状态 → 知识检索 → 具体动作的条件审核 → 提案 → 作者采纳 → 新正文 → 新状态与再次推荐。没有界面依赖，不调用额外模型接口。

代码在 `scripts/recommendation_session.py` 和 `scripts/recommendation_engine.py`。继续复用原来的事实／知情审核、候选准备、母题匹配及 BM25，不使用旧图谱的关键词猜测更新作为事实入口。可由桌面软件或插件的 Python 服务调用；本轮没有制作宿主插件或桌面壳。

## 重放已完成的审核

在仓库根目录运行：

```bash
python3 experiments/recommendation-core/replay.py replay \
  --state-reviews experiments/recommendation-core/state-reviews-public.json \
  --candidate-reviews experiments/recommendation-core/candidate-reviews-public.json
```

输出包括七个原创截点的结果和两个项目的完整会话 JSON。所有函数返回新对象，调用方自行保存。涉及自己的小说时，将完整输出保存在被忽略的 `runtime-data/` 或自己的作品目录；完整会话包含作者知道而角色未必知道的正文、审核和历史版本。

其他入口：

```bash
# 生成基础事实、指代及动作状态的审核请求
python3 experiments/recommendation-core/replay.py prepare-states

# 导入第一轮审核，生成实际检索所得卡片的条件审核请求
python3 experiments/recommendation-core/replay.py prepare-candidates \
  --state-reviews experiments/recommendation-core/state-reviews-public.json

# 机制回归测试
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s scripts/tests -p 'test_recommendation*.py'
```

审核文件是本轮当前 AI 阅读后产生的输入，不是程序假装调用模型得到的结果。重放是在验证这些已保存判断的执行过程。

## 宿主调用顺序

将本仓库 `scripts` 目录加入 Python 模块搜索路径，然后调用：

```python
from recommendation_session import new_session, source_token, append_scene
from recommendation_engine import (
    prepare_state, review_state, prepare_recommendations,
    review_recommendations, accept_current,
)

session = new_session(raw_project)
state_request = prepare_state(session, annotations)
# 宿主将 state_request 交给审核者；这一步不由模块自动调用 AI。
session = review_state(session, state_request, imported_state_review)
request = prepare_recommendations(session, catalog, repo_root, top_k=2)
# 只审核 request.instances 中实际取回的候选；无实例时传 {}。
session = review_recommendations(session, request, imported_instance_reviews,
                                 catalog, repo_root)
writer_input = session['current_batch']['writer_packet']
# 作者明确选择当前批次中的一个 proposal_id。
session = accept_current(session, proposal_id, source_token(session),
                         session['batch_sha256'], catalog, repo_root)
# 作者写入实际正文后，旧状态和推荐立即失效。
session = append_scene(session, new_scene, source_token(session))
# 从 prepare_state 开始，重新整理并审阅当前完整前文。
```

`replace_source` 支持编辑旧正文，同样生成新版本并清空当前派生状态。采纳只产生 `accepted_intent`；不能完成动作、解决任务、填写结局或把计划加入事实。追加正文也不意味着被采纳动作一定发生。

## 数据层与审核职责

| 层 | 内容 | 权限和来源 |
|---|---|---|
| 通用知识 | 来源原文、卡片条件、操作化变体 | 四张卡从旧目录另行派生，原始 271 份资料不改动 |
| 项目正文 | 项目 ID、人物、当前截点内的场景 | 版本快照，严格按调用方提供的前文范围 |
| 候选标注 | 基础事实；人物／对象／任务／动作的稳定 ID | 由作者或语义提供方整理，尚非确定事实 |
| 已审状态 | 确定且 POV 可知的事实、动作状态、对象区别、重试依据 | 单独审核世界命题与角色知情，保留精确引文 |
| 推荐批次 | 检索卡、实例审核、具体提案与证据引用 | 绑定正文版本、状态、目录和审核；无全池答案回填 |
| 采纳记录 | 作者选择的提案及其原始版本 | 未来意图，独立于事实和动作状态 |

基础事实的“收到纸条”“别人说里面是编号”“亲眼读到编号”应分别写成原子命题。卡片生成的条件问题、未来提案和内部动作状态问题不进入基础状态检索查询。

`annotations` 的准确格式见公开 `fixtures-public.json`：

- `facts` 沿用旧事实格式，带场景、精确引文、字符位置和待审知情者。
- `registry.characters/entities/tasks` 使用 `id` 与 `label`。
- `registry.actions` 明确 `actor_id / target_ids / task_id / operation / description`，另有 `origin / status / anchor`。
- `origin=proposed` 必须配 `status=proposed`，不能伪装成已经发生的待办状态。
- 新提案也需单独审核这一次操作尚未开始；新建动作编号、遗漏完成记录都不能充当依据。此门槛不要求人物已经制定计划。
- `origin=observed` 可配 `pending / in_progress / completed / cancelled / unknown`；只有当前审核支持的状态才生效。
- 同一对象的新一轮操作使用 `repeat_of` 关联先前动作，并提供 `retry_reason`；依据需通过当前正文和知情审核。

对象 ID 不是语义证明。对于同一人物的同类动作，目标不同还需审核“确实是不同对象”；未知或同物别名不会放行。重复判定不依赖动作 ID、任务 ID 或描述换名。目标集合重叠时保守阻止重复，应先拆成单独动作；重试目前要求与父动作使用相同目标集合。

ID 和定义在一个会话中保持稳定，登记过的身份不能被悄悄删除或换绑；状态可以重审为未知。纠正早期身份定义目前需重建会话并重审，尚无自动合并／拆分身份迁移工具。它不会利用旧状态替代新版本的重新审核。

## 接入边界

只把 `current_batch.writer_packet` 交给写作模型。它只含已审可知命题、匿名证据编号和未来提案；原文大段引句、审计理由、注册表及内部编号留在作者端。哈希用于内容一致性和旧版本拒绝，不是审阅者身份认证。低层 `install_state/install_batch` 属于可信宿主接口；外部审核应通过 engine 的审核入口导入。

当前稳定闭环使用 BM25。此前本地向量检索实验仍保留，尚未作为这一会话模块的可选检索后端接入。扩大目录、换检索器或接 AI 提供方时，应保持“只审实际候选、证据门槛独立于相似度”的契约。

本轮验证的是有限目录下的机制和来源边界，不是自动抽取、文学质量、全库召回或长篇性能的完成证明。案例限于局部顺叙前文；本轮没有增加自动插叙／倒叙时间线推理。新增正文是预先写好的原创例子，并非写作模型自动生成。

结果见 [RESULTS.md](RESULTS.md)，卡片改动见 [catalog-notes.md](catalog-notes.md)，初审分歧见 [adjudication.json](adjudication.json)。
