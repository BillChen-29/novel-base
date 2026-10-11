# Novel Base 项目工作流

## 目录结构

```
<workdir>                                      # 项目工作区（代码 + assets 通用知识库）
~/.hermes/skills/creative/novel-base/           # Hermes Skill 目录（运行时）
```

## 工作流

### 代码修改流程
```
1. Claude Code 在 <workdir> 修改代码
2. git add -A && git commit -m "..." && git push origin main
3. Hermes 执行: cd ~/.hermes/skills/creative/novel-base && git pull origin main
4. 验证: python3 scripts/test_novel_flow_executor.py
```

### 数据修改流程
```
1. assets/ 通用知识库随 GitHub 仓库发布，在项目工作区维护并审查后提交。
2. runtime-data/ 和具体小说项目、正文、记忆、审核产物保留在本地。
3. 更新 assets/ 时同步 docs/data/asset-manifest.json 中的文件清单、大小和 SHA-256。
```

## 注意事项

- 克隆项目包含代码和 assets/，不包含个人 runtime-data/ 和小说项目。
- Claude Code 只修改项目目录，不直接修改 skill 目录
- 代码与通用资产变更通过 GitHub 中转：项目目录 → push → skill 目录 pull。
- 更新已有运行目录前备份本地 assets/；同名未跟踪文件可能阻止 pull，应先逐项比较并保存本地修改。
- 运行时数据变更直接在 skill 目录操作（runtime-data/ 等）。
- 资产范围与来源说明见 [docs/data/asset-library.md](docs/data/asset-library.md)。
