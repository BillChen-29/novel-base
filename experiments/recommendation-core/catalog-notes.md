# 动作绑定目录说明

新文件：`recommendation/action-catalog.json`。继承 `experiments/stage-card-pilot/catalog.json` 的四张卡片及完整来源路径、SHA-256、原文区间和引句，未改写旧目录或原始素材。

- 上游目录 SHA-256：`2713b2114234fd5d420a5b3a50b64ad9a27fd42f97a2b3c379486aa79234ebc1`。
- 新目录 SHA-256：`65c51ee0c6b39e021f68879deaaaca6c136d8d0c6f543e38f7b17a4ca252f886`。
- 规模：4 张卡片、10 个变体；`schema_version: 1`，`stage_mode: alternatives`。
- 校验：原仓库 `motif_matcher._validate_catalog` 通过，包括每份原始素材哈希及逐字引文区间；另行检查所有条件和提案模板恰好使用 `actor`、`target`、`task`、`action` 四种占位符，并核对操作和状态枚举。

## 角色和状态

所有卡片使用 `actor: character`、`target: object`、`task: object`、`action: object`。每条条件直接限定具体目标、任务、行动，不再使用泛指的 `focus` 或“有一个待办”的存在性条件。

`operations` 仅取 `read/use/check/respond/investigate`；开始变体的 `action_states` 为 `proposed/pending`，继续变体仅为 `in_progress`。这是变体适用范围，不是从故事事实推断行动状态的规则。`origin=proposed` 不能替代历史状态；旧行动是否完成、放弃、冲突以及角色身份匹配均由适配层处理。

`proposal` 保留为旧引擎需要的静态建议；新增 `proposal_template` 供适配层在身份绑定、状态过滤及条件审阅通过后填充。模板分别以“开始{action}”或“继续{action}”开头，完整绑定四个角色，保留未知结果，不指定阅读位置或核对结论。

## 卡片的附加门槛

| 卡片 | 操作及变体 | 附加条件 |
| --- | --- | --- |
| `dialogue_active` | `respond_begin / respond_continue` | 对应交涉已有具体分歧、交涉仍开放、既有对话对象当前可回应、同一争议尚未解决 |
| `truth_trigger` | `begin / continue` | 对应疑点已经发现、对该任务与疑点已有持续追查承诺、同一问题未解决 |
| `carrier_process` | `read / read_continue / use / use_continue` | 本任务事项未完成；开始读取须可访问且未读，继续读取须可访问且未读完；使用须具体内容已理解且用途已知 |
| `clue_check` | `verify / verify_continue` | 对应线索当前可访问、同一问题未解决、这项核对当前可执行 |

表中变体使用各卡片 ID 前缀；对话完整 ID 为 `dialogue_active_respond_begin` 和 `dialogue_active_respond_continue`。没有先前计划并不妨碍提出新的具体步骤。追查承诺要求的是任务级持续追查决定，不是先前已计划该具体调查动作。

“未读”和“未读完”必须由对应证据支持，不能以缺少完成记录推定。继续读取不从未读阶段进入；开始和继续核对也不以未见检查记录推出从未检查。来源与作者设计的区别保留在每卡 `basis` 和 `operationalization_note` 中：载体通用流程不计为织物传书母题命中，局部核对不计为完整悬念阶梯，追查卡只对应原文触发阶段。
