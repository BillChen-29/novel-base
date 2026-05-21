# Pitfalls

> 从 SKILL.md 移出的完整 Pitfall 文档。合并了原"20. Pitfall（补充）"和"15. Pitfall"两处内容。

## Pitfall 补充

### 选题 Pitfall
- **选题必须和用户讨论确定**：即使用户说"完全由你定"，也应先提方案让用户确认。不能自作主张选择题材。
- **用户会把方案发给其他 AI 审查**：多轮迭代模式，批判性采纳外部建议。

### 项目工作流 Pitfall
- **Claude Code 工作目录**：`~/Desktop/project/novel-base/`（代码-only clone），不直接改 skill 目录
- **代码变更流程**：项目目录改 → push GitHub → Hermes pull skill 目录
- **数据变更**：直接在 skill 目录的 assets/ 和 runtime-data/ 操作，不上 GitHub
- **Git 身份**：必须用 BillChen-29 noreply（`git config user.name "BillChen-29"` + `user.email "BillChen-29@users.noreply.github.com"`），禁止暴露真实姓名

### 门禁 Pitfall（2026-05-09 修复）
- **quality_baseline 占位文件检测**：quality_report.md 为占位文件（含"自动创建的占位文件"或 char_count=0）时跳过检查
- **anti_resolution_guard 参数**：SimpleNamespace 传入 `chapter=整数` 而非 `chapter_file=字符串`
- **stub 文件自动清理**：continue_write 写入实际章节后自动删除同章节号的"待写"文件
- **字数截断**：LLM 生成内容超过 max(target*1.5, target+3000) 时在句号处截断

### GitHub 隐私 Pitfall
- **绝对不能上传知乎盐选数据**：故事文本、节奏基准、下载记录等有版权风险
- **.gitignore 规则**：`references/zhihu-*.md`, `runtime-data/`
- **Claude Code 会自行添加文件**：验收时必须 `git diff --stat` 检查新增文件

### 知乎盐选 Pitfall
- **动态字体加密**：每次加载映射不同，无法静态解码
- **采集策略**：用户手动下载文本，不做自动化抓取
- **Playwright 被检测**：知乎反爬会检测无头浏览器
- **Chrome AppleScript 控制**：可以提取加密文本，但无法解码

### Claude Code 工作流 Pitfall（补充）
- **讨论→规划→实现全交 Claude Code**：MiMo 统筹+验收，不自己生成代码
- **每轮 delegate_task 无记忆**：需传完整上下文（前几轮讨论 + 代码位置 + 期望改动）
- **微步骤拆分**：大任务拆成 3-5 步微步骤，每步有明确验证方法
- **行号验证**：Claude Code 无法访问本地文件验证行号，需本地 grep 二次确认
- **多轮审查**：第一轮出方案 → 第二轮审查 → 第三轮整合修正 → 实施

---

## Pitfall

### 流程 Pitfall
- **novel_flow_executor.py 是核心，不能删除**：所有命令最终都走这个脚本，它负责协调写作、门禁、检索等全流程。其他脚本是辅助。
- **Hermes skill 模式 vs standalone**：Hermes 读 SKILL.md 后解析并执行。standalone 模式下用 `python3 scripts/novel_flow_executor.py ...` 直接调用。
- **章节号必须从 1 开始连续**：不能跳号。如果删除已写章节，后续章节号不会自动调整。
- **改纲后续写必须用 `/改纲续写`**：不能直接 `/继续写`，否则 RAG 索引和大纲锚点不会更新，导致剧情漂移。

### 数据 Pitfall
- **通用层数据库不能删**：`assets/` 下的 376 个文档是核心资产。删除后需要重新导入。
- **知乎盐选数据不能上 GitHub**：知乎内容有版权，必须在 .gitignore 中排除。
- **风格指纹依赖样本章节**：`style_fingerprint.py` 需要至少 3 章样本文本才能工作。
- **知识图谱增量更新**：`story_graph_updater.py` 是增量更新，不会清空已有数据。手动修改图谱后需运行 `story_graph_builder.py validate` 校验。

### 真相文件系统 Pitfall
- **Observer/Reflector 字段名不匹配**：hook_operations 使用 `"operation"` 字段，不是 `"op"`
- **load_truth 返回 tuple**：`truth_manager.load_truth()` 返回 `(data, errors)` 元组，需解包
- **迁移脚本 schema 匹配**：用户自定义的 memory 文件名可能不匹配 schema，迁移时会跳过

### 设计 Pitfall
- **执行计划设计原则**：新建模块不修改原有大文件（novel_chapter_writer.py 57KB、novel_flow_executor.py 134KB）
- **统一CLI入口对Hermes无价值**：Hermes调用脚本时直接读SKILL.md的命令映射
- **Hermes skill的数据库管理设计原则**：用户手动标记文本类型，脚本按类型路由分析，不做自动分类
- **style_library 清理策略**：两套命名时保留更大的版本，但需检查互补内容

### 集成测试 Pitfall（2026-05 新增）
- **template 字数统计不兼容 CJK-only**：`generate_draft_text()` 用 `len(re.sub(r'\s+', '', text))` 统计（含标点），`count_chars()` 只计 CJK 字符。改一边不改另一边会导致门禁阈值不匹配，3 个 continue-write 测试失败。
- **大纲卷计算硬编码**：`init_project_files()` 中 `VOL1_END="120"` 是硬编码的，不跟 target_words 联动。已修复为动态计算。
- **RAG 查询静默跳过**：`analyze_query_trigger()` 在查询不匹配预设关键词时返回 `should_trigger=False`，导致查询返回空结果而无任何提示。已加 >=8 字默认触发。
- **门禁产物必须预生成**：`chapter_gate_check.py` 直接调用时需要 6 个产物文件存在。已加 `--auto-create-missing`。
- **Claude Code 会 stash git 变更**：subagent 调试时会 `git stash`，完成后不 pop。需手动 `git stash pop` 恢复。
- **Claude Code 不会完全实现请求的修改**：要求 5 处修改可能只落地 3 处。每次实现后必须用 `grep` 验证每处改动。
