---
name: kudi-report
description: 生成库迪助手报表（默认B端+C端，支持全渠道）并导出CSV与截图
user-invocable: true
metadata: {"openclaw":{"emoji":"📊","homepage":"https://docs.openclaw.ai/tools/skills"}}
---

# 库迪助手报表 Skill

当用户请求“库迪助手报表”时，执行本技能脚本生成报表。

执行规则：
- 用户消息包含“库迪助手报表 全渠道”或参数里包含“全渠道/full/all”时，运行全量模式。
- 否则运行默认模式（仅 B 端 + C 端）。
- 兼容旧叫法 `session-stats`，但回复中优先使用“库迪助手报表”。

请通过命令行执行：

```bash
bash {baseDir}/run_kudi_report.sh "<用户原始请求或参数>"
```

默认目录：
- 输出：`{baseDir}/outputs/YYYY-MM-DD/`
- 临时文件：`{baseDir}/tmp/YYYY-MM-DD/`
- 日志：`{baseDir}/logs/`

可选环境变量：
- `OPENCLAW_REPORT_OUTPUT_DIR`（输出根目录）
- `OPENCLAW_REPORT_TMP_DIR`（临时目录根）
- `OPENCLAW_REPORT_LOG_DIR`（日志目录）
- `OPENCLAW_REPORT_MEDIA_DIR`（附件中转目录）
- `OPENCLAW_REPORT_RETENTION_DAYS`（输出保留天数，默认 14）
- `OPENCLAW_REPORT_TMP_RETENTION_DAYS`（临时文件保留天数，默认 3）
- `OPENCLAW_REPORT_LOG_RETENTION_DAYS`（日志保留天数，默认 14）

执行完成后，向用户回传关键产物路径（默认输出目录）：
- `{baseDir}/outputs/YYYY-MM-DD/session-stats_summary_<run-id>.csv`
- `{baseDir}/outputs/YYYY-MM-DD/session-stats_summary_<run-id>.json`
- `{baseDir}/outputs/YYYY-MM-DD/session-stats_b_channel_<run-id>.png`
- `{baseDir}/outputs/YYYY-MM-DD/session-stats_c_channel_<run-id>.png`
- 全渠道模式额外包含 `{baseDir}/outputs/YYYY-MM-DD/session-stats_all_channels_<run-id>.png`

重要：本技能的成功回复必须包含图片附件回传（默认 B/C 两张，全渠道模式三张）。
文件发送统一使用 `message` 工具，不再依赖内联 `MEDIA:` 文本方案。

发送规则（强制）：
- 从脚本输出中读取 `FILE:` 行，使用这些路径作为附件来源（默认位于 `{baseDir}/outputs/staging-media/`，可被 `OPENCLAW_REPORT_MEDIA_DIR` 覆盖）。
- 对每个图片文件都调用一次 `message` 工具发送：
  - `action=send`
  - `target` 或 `to` 使用当前用户/会话目标
  - `message` 写简短说明（如“B端报表请查收”）
  - `media` 传本地文件路径（优先 `FILE:` 对应路径）
- 若 `media` 发送失败，仅允许一次同路径重试：改用 `filePath`（或 `path`）字段。
- 严禁只回文字路径、只发 Markdown 图片链接、或宣称“已发送”但未实际调用工具。

CSV 数据回传规则（强制）：
- 必须读取本次 run-id 对应 `session-stats_summary_<run-id>.csv` 的实际内容，不能只回 CSV 路径。
- 最终文字回复中必须包含一段 Markdown 表格，表头与 CSV 首行一致，数据行按 CSV 全部行输出（默认 2 行；全渠道 3 行）。
- 禁止只写“详见 CSV/见附件”而不贴表格内容。
- 读取 CSV 失败时，必须明确报错原因并重试一次；若仍失败，回传 CSV 文件附件并说明“文本表格解析失败”。
- 推荐同时发送 CSV 附件（`message action=send` + `media=<FILE:...csv>`），便于用户下载。

最终回复要求：
- 先给简短文字结论（模式、CSV 路径、关键指标）。
- 必须紧跟 CSV 的 Markdown 表格正文（完整行，不省略）。
- 图片通过 `message` 工具逐个发送完成后，再给一句“已回传附件（含图片/CSV）”的确认。
- 不要在最终文本中输出 `MEDIA:` 行作为主要发送方式。
- 若图片未通过工具成功发出，或缺少 CSV 表格正文，则视为本技能执行不完整，需要补发。

若执行失败，明确说明失败步骤与缺失产物。
