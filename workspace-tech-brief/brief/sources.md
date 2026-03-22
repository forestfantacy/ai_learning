# sources.md

下面定义技术晨报的来源清单。后续新增来源时，直接追加即可。

---

## Source: github-trending

- enabled: true
- type: ranking
- url: https://github.com/trending
- fetch: web_fetch
- priority: high

### Rules

- 分析页面上当天全部上榜项目
- 保持页面顺序
- 每个项目至少输出：项目、看点、判断、建议
- 如果页面项目数不是 10，则按实际数量全量分析

---

## Source: hacker-news

- enabled: false
- type: discussion
- url: https://news.ycombinator.com/
- fetch: web_fetch
- priority: medium

### Rules

- 默认只看首页前 20 条
- 过滤纯八卦、融资、求职类条目
- 优先保留工程、基础设施、数据库、编译器、AI infra、工具链相关内容
- 如果和其他来源重复，作为补充背景，不单独成段

---

## Source: lobsters

- enabled: false
- type: discussion
- url: https://lobste.rs/
- fetch: web_fetch
- priority: medium

### Rules

- 优先关注高技术密度帖子
- 重点看工程实现、架构、系统、工具链
- 低信噪比话题直接忽略

---

## Source: official-releases

- enabled: false
- type: release
- fetch: web_fetch
- priority: high

### Targets

- https://github.com/openclaw/openclaw

### Rules

- 只关注最近 24 小时内的发布
- 优先关注 breaking changes、新能力、弃用、基础设施变化
- 若无实质变更，不强行写入晨报
