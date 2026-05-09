# Novel Base 项目工作流

## 目录结构

```
/Users/chenzefeng/Desktop/project/novel-base/   # Claude Code 工作区（代码-only）
~/.hermes/skills/creative/novel-base/           # Hermes Skill 目录（运行时）
```

## 工作流

### 代码修改流程
```
1. Claude Code 在 /Users/chenzefeng/Desktop/project/novel-base/ 修改代码
2. git add -A && git commit -m "..." && git push origin main
3. Hermes 执行: cd ~/.hermes/skills/creative/novel-base && git pull origin main
4. 验证: python3 scripts/test_novel_flow_executor.py
```

### 数据修改流程
```
1. 数据文件在 ~/.hermes/skills/creative/novel-base/assets/（本地-only）
2. 数据文件在 ~/.hermes/skills/creative/novel-base/runtime-data/（本地-only）
3. 不上 GitHub，不通过项目目录
```

## 注意事项

- 项目目录是代码-only 的 clone，不含 assets/ 和 runtime-data/
- Claude Code 只修改项目目录，不直接修改 skill 目录
- 代码变更通过 GitHub 中转：项目目录 → push → skill 目录 pull
- 数据变更直接在 skill 目录操作（assets/, runtime-data/）
