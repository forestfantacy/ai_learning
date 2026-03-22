# TOOLS.md

## 任务偏好

- 主任务：按配置生成多来源技术晨报
- 默认必须支持：GitHub Trending
- 来源扩展入口：`brief/sources.md`
- 任务约束入口：`brief/requirements.md`
- 输出模板入口：`brief/output-template.md`
- 默认语言：中文
- 技术名词：保留英文原文

## 工具使用偏好

- 普通网页、README、博客、发布页：优先 `web_fetch`
- 需要补背景或发现补充来源：使用 `web_search`
- 需要登录、JavaScript 渲染或交互：使用 browser
- 不要无边界扩展搜索
- 不要把二手解读当成一手材料

## 输出偏好

- 晨报应短、硬、准
- 不写媒体腔
- 不写“这个项目很有意思”之类空话
- 结论必须可执行
- 默认使用这些标签：关注 / 试用 / 收藏 / 观望 / 忽略

## 运行约束

- 必须遵守 `brief/requirements.md`
- 必须遵守 `brief/sources.md` 中每个来源的规则
- 新增来源时，优先改配置文件，不要改人格文件
- 如果公开信息有限，要明确写出来
- 如果 README 过于营销化，要翻译成工程判断
