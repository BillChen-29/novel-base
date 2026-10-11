# Novel Base 叙事知识库

这份知识库为中文小说策划、人物构建、风格讨论和写作流程提供可读取的参考材料，主要由中文 Markdown 文档组成，另有 JSON 平台配置和导入记录。它与项目代码一起发布，克隆仓库后可直接在 `assets/` 中查看。

本次快照日期为 2026-10-11，共 **271 个文件、870,885 字节**。发布前对 9 份文档清除了提取行号，并将一处旧电脑绝对路径改为相对文件名，保留叙事正文。原始资产总计 873,656 字节，格式整理记录与原文件校验值保存在清单中。数量按文件统计；同一文档可能包含多个案例，不代表相同数量的独立标注样本。

## 文件构成

| 目录或文件 | 数量 | 内容 |
|---|---:|---|
| `assets/motif_library/` | 178 | 叙事母题、结构模板与案例 |
| `assets/character_archetypes/` | 45 | 角色原型、动机与叙事功能 |
| `assets/style_library/` | 11 | 风格分析与写作参考 |
| `assets/technique_library/` | 27 | 场景、对话、悬念等技法文档 |
| `assets/pacing/` | 5 | 节奏与平台文本分析 |
| `assets/platforms/` | 3 | 两个平台配置和一份题材说明 |
| `assets/ai_patterns.md` | 1 | 文本模式与编辑提示 |
| `assets/ingest_manifest.json` | 1 | 已保留的部分导入记录 |

文件格式合计：268 份 Markdown，3 份 JSON。

## 来源与组织方式

这些资料包含上游保留的样例，以及项目维护者与 AI 协作完成的扩展整理。文档涉及叙事学与神话材料、经典文学、现代网络小说和写作经验；具体来源以各文件中的说明为线索。来源记录的详细程度不一，部分仅列作品名称，后续可补充版本、章节、页码及人工核对记录。

知识库用于参考、检索和提示词上下文。当前快照采用文件目录组织，没有统一的训练／验证／测试划分，也没有标准答案标签。

`ingest_manifest.json` 是现存的部分导入日志；完整发布清单是本目录下的 [`asset-manifest.json`](asset-manifest.json)。

文档中的作品名称、案例和引文保留其原有来源归属。项目代码的许可说明不改变第三方作品的权利；再利用具体引文或材料时应核对相应来源。

## 使用方式

从仓库根目录运行：

```bash
python3 scripts/novel_flow_executor.py db-maintain list-assets
python3 scripts/novel_flow_executor.py db-maintain list-platforms
python3 scripts/novel_flow_executor.py db-maintain validate
```

也可直接阅读 `assets/` 中的文档。`list-assets` 按子库统计（包含平台目录），显示 269 个文件；本文清单还计入根目录的模式文档与导入记录，合计 271 个。

自动格式校验用于发现空文档或缺失标题，内容准确性、引用出处和具体创作适用性需要结合原文判断。

## 快照校验

[`asset-manifest.json`](asset-manifest.json) 为每个文件记录仓库相对路径、字节数和 SHA-256。它覆盖本次发布的全部 271 个资产文件，说明文档与校验清单自身不计入资产数量。

在仓库根目录可以用下面的命令验证下载后的文件：

```bash
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

manifest = json.loads(Path('docs/data/asset-manifest.json').read_text(encoding='utf-8'))
expected = {item['path'] for item in manifest['files']}
actual = {p.as_posix() for p in Path('assets').rglob('*') if p.is_file()}
if expected != actual:
    raise SystemExit('Asset file list differs from the snapshot manifest')
for item in manifest['files']:
    content = Path(item['path']).read_bytes()
    if len(content) != item['bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
        raise SystemExit('Asset verification failed: ' + item['path'])
print('Verified', len(expected), 'asset files')
PY
```

本次保留了一组相同内容在不同子库中的文件：`pacing/real-data-pacing-benchmark.md` 与 `technique_library/real-data-pacing-benchmark.md`。清单记录了这组重复，以便下游统计时按需去重。

## 格式整理与来源补充

- 风格索引中一处旧电脑绝对路径已改为当前目录下的相对文件名。一份测试风格档案和节奏基准仍记录着历史临时样本路径；这些样本不在本次快照内，后续可补充可复现的输入。
- 9 份文档的“行号|”前缀已清理：角色目录中的 `lin-chong.md`、`lu-zhi-shen.md`、`shi-jin.md`、`song-jiang.md`、`wu-song.md`、`wu-yong.md`、`yang-zhi.md`，以及母题目录中的 `culture-hero.md`、`magical-duel.md`。清单的 `normalizations` 字段记录具体路径、修改类型及原文件校验值。
- 节奏基准提到的历史分析 JSON 与原始小说文本不在此快照中；复算报告数值需要补充相应输入和过程记录。

## 文本分析指标

节奏资料中报告的钩子、爽点等统计依赖标点与关键词规则。它们适合辅助观察文本特征；读者的悬念感、投入程度和阅读偏好需要另行评价。部分历史文本转换丢失对话引号，相关比例应结合文档中的格式说明解释。

## 维护范围

通用知识库 `assets/` 随仓库维护。个人正文、记忆、审核材料和自定义运行数据继续由 `.gitignore` 排除。更新资产后应重新生成快照清单，使其与新内容一致。

已有运行目录可能保存了同名未跟踪文件；更新前应备份并比较本地资产，再合并差异。
