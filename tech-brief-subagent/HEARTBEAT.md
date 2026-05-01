# HEARTBEAT.md

这个 agent 的核心任务由 cron 驱动，不由 heartbeat 驱动。

规则：

- 不主动抓取 GitHub Trending
- 不主动生成技术晨报
- 不重复执行当天已经由 cron 完成的晨报任务
- 如果没有明确的额外维护任务，回复 HEARTBEAT_OK

只有在以下情况才行动：

- 用户明确要求你临时补发一份晨报
- 用户要求你复盘当天或最近几天的技术趋势
- 需要整理或压缩 memory 中的历史笔记

如果只是普通 heartbeat，默认回复 HEARTBEAT_OK。
