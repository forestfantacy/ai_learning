---
name: gp
version: 1.0.0
description: "分析当前代码修改，生成合适的提交信息并推送到远程仓库。当用户想要快速提交所有更改时使用，替代手动 git add/commit/push 流程。"
metadata:
  requires: {}
---

# GG - 自动提交并推送

智能分析当前修改，生成 commit message 并推送到远程仓库。

## 命令

```bash
# 1. 查看未暂存的修改
git diff --stat

# 2. 查看已暂存的修改
git diff --cached --stat

# 3. 获取最近的提交风格作为参考
git log --oneline -5

# 4. 分析修改内容，生成合适的 commit message
# 5. 提交并推送
git add -A
git commit -m "<分析得出的提交信息>"
git push
```

## 执行流程

1. 运行 `git status` 查看当前状态
2. 运行 `git diff --stat` 分析未暂存的修改
3. 运行 `git diff --cached --stat` 分析已暂存的修改
4. 根据修改内容生成合适的中文 commit message：
   - 新功能: `feat: <功能描述>`
   - 修复bug: `fix: <修复内容>`
   - 文档: `docs: <文档变更>`
   - 重构: `refactor: <重构内容>`
   - 测试: `test: <测试相关>`
   - 其他: `chore: <其他变更>`
5. 执行 add → commit → push
6. 显示提交结果（commit hash 和推送状态）

## 注意事项

- 如果没有修改，返回"没有需要提交的更改"
- 如果是纯配置文件修改（如 package.json, pom.xml），使用 `chore` 类型
- 优先使用中文提交信息