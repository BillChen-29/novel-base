# Agent 编辑团队

> 从 SKILL.md 移出的编辑团队详细文档。

## 为什么需要编辑团队

单 Agent 写作存在三个根性问题：
1. **AI 幻觉**：写作 Agent 可能捏造从未出现过的地名、人名、设定规则
2. **角色错乱**：角色被放错位置、被赋予其不具备的能力、或语气风格全部雷同
3. **Agent 思路污染正文**：写作过程中的分析思路、角色定位说明、meta注记渗入小说正文

编辑团队通过职责严格分离，在生产流程中内建三道防火墙。

## 团队架构（真实报社模型）

```
用户
  │
  ▼
总编辑（Claude Code 主 Agent）
  │  协调所有子 Agent，汇总报告，作最终裁判
  ├──► 策划主编（planning-editor）
  │     读规划文件 → 生成 Chapter Brief → 传给写作特工
  │
  ├──► 写作特工（novelist）
  │     只接收 Brief，只输出纯正文，严格隔离 meta 信息
  │
  ├──► 反AI编辑（anti-ai-editor）      ┐ 并行
  └──► 连载核实官（consistency-reviewer）┘ 审核
```

## 触发命令

```
/启动编辑团队 [--项目路径 <路径>] [--章节 <N>] [--模式 单章|批量]
```

## 正文隔离协议（防止 Agent 思路污染正文）

| Agent | 允许的输出内容 | 严禁的输出内容 |
|-------|--------------|--------------|
| 写作特工 | `NOVEL_TEXT_START` 到 `NOVEL_TEXT_END` 之间的纯小说正文 | 分析说明、角色定位、写作思路 |
| 反AI编辑 | 报告 + `HUMANIZED_TEXT` 标记内的净化正文 | 在润色后正文中插入注释 |
| 连载核实官 | 结构化核查报告 | 直接修改正文 |
| 总编辑 | 最终章节包 | 将审核意见混入正文区 |

**P0 检测触发器**：正文中出现 `[` `]` 括号说明、`（注：）`、`TODO`、`作者按`等，立即触发 P0 强制重写。

## 状态管理脚本

```bash
# 生成上下文快照
python3 scripts/editorial_team_manager.py snapshot --project-root <路径>

# 记录审核结果
python3 scripts/editorial_team_manager.py record-review \
  --project-root <路径> --chapter N --stage final --verdict pass --p0 0 --p1 2 --p2 3

# 检测是否需要人工介入
python3 scripts/editorial_team_manager.py need-human --project-root <路径>
```
