# ai-data-analysis-plus

`ai-data-analysis-plus` 是一个 Claude Code skill，用于把“分析一下这份数据”这类模糊请求，推进成面向决策、有证据链、可验证、可行动的业务数据分析流程。

它不是一个独立的数据分析程序，而是一套给 agent 使用的工作规范、参考资料和辅助脚本。实际分析由 Claude Code / agent 执行，skill 负责规定触发条件、分析步骤、追问规则、质量闸门和报告结构。

## 目录结构

```text
ai-data-analysis-plus/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── interaction.md
│   ├── quality-gates.md
│   ├── report-templates.md
│   └── sop.md
└── scripts/
    └── create_analysis_brief.py
```

## 文件职责

- `SKILL.md`：skill 入口文件，包含 `name`、`description`、核心规则、主工作流和参考资料加载策略。
- `agents/openai.yaml`：可选 UI 元数据，用于展示名称、简介和默认 prompt；不是 skill 的核心触发依据。
- `references/sop.md`：完整分析 SOP，包括目标发现、决策目标、业务模型还原、异常检测、归因证据链、预测和行动闭环。
- `references/interaction.md`：多轮交互协议，规定什么时候追问用户、如何索取缺失数据、用户补充数据后如何从阻塞点继续。
- `references/quality-gates.md`：质量闸门，包括指标契约、统计严谨性、可追溯性、结论压力测试和图表适配。
- `references/report-templates.md`：分析方案、指标契约、归因证据表、最终报告和短回答模板。
- `scripts/create_analysis_brief.py`：可选辅助脚本，用于生成中文 Markdown 分析报告骨架。

## 触发机制

Claude Code / agent 会根据 `SKILL.md` frontmatter 中的 `name` 和 `description` 判断是否触发 skill：

```yaml
---
name: ai-data-analysis-plus
description: 当用户需要 AI 辅助的数据分析 SOP 时使用...
---
```

典型触发请求包括：

- “帮我分析这份销售数据”
- “老板让我分析一下问题在哪”
- “这份数据能看出什么业务问题”
- “帮我做归因分析”
- “帮我输出一份有行动建议的数据分析报告”
- “销售额下降了，帮我找原因”

触发后，agent 会先读取 `SKILL.md`，再根据当前任务阶段按需读取 `references/` 下的具体文件。

## 分层加载流程

这个 skill 采用渐进加载设计，避免每次把所有细节都塞进上下文。

```text
用户提出数据分析请求
-> agent 命中 ai-data-analysis-plus
-> 读取 SKILL.md 主流程
-> 按任务阶段读取 references 中的细则
-> 必要时运行 scripts/create_analysis_brief.py 生成报告骨架
-> agent 填入真实计算、证据、置信度和行动建议
```

参考资料加载规则：

| 场景 | 加载文件 |
|-|-|
| 做完整分析或设计分析方案 | `references/sop.md` |
| 需要追问、等待补充数据、恢复中断分析或更新置信度 | `references/interaction.md` |
| 计算指标、验证结论、异常检测、归因或推荐图表 | `references/quality-gates.md` |
| 起草分析报告或结构化交付物 | `references/report-templates.md` |

## 多轮交互能力

skill 本身不会主动弹窗或保存会话状态；多轮交互由 agent 执行。`references/interaction.md` 规定了 agent 在信息不足时应该如何和用户互动。

当缺失数据阻塞下一步分析时，agent 应该输出：

1. 当前已经确认的事实。
2. 当前结论置信度。
3. 不能继续确认的原因。
4. 最少需要补充的 1-3 类数据。
5. 用户补充后将继续执行的分析步骤。

用户补充数据后，agent 应从上一次阻塞点继续：

1. 复述收到的补充内容。
2. 更新数据盘点和指标契约。
3. 重新计算受影响指标。
4. 更新归因证据表和置信度。
5. 说明哪些旧结论被保留、修正或撤回。

## Python 脚本运行时机

`scripts/create_analysis_brief.py` 不会自动运行，也不是分析引擎。它只在需要生成标准 Markdown 报告骨架时，由 agent 或用户显式调用。

适合运行的场景：

- 用户要求“先给我一个分析框架”。
- 用户要求“生成一份分析报告模板”。
- 数据还不完整，但需要先形成分析方案文档。
- 已完成分析，需要把结果整理成结构化报告。

示例：

```bash
python3 ai-data-analysis-plus/scripts/create_analysis_brief.py \
  --title "销售额下降诊断" \
  --stakeholder "运营负责人" \
  --decision "判断优先介入哪个渠道" \
  --output analysis_brief.md
```

脚本输出的是中文 Markdown 骨架，不会读取数据、不会计算指标、不会自动归因。最终内容必须由 agent 基于真实数据和证据补全。

## 核心分析原则

这个 skill 的核心原则是：不要从一个可见变化直接跳到原因。

完整分析应拆开六件事：

1. 决策目标：谁要基于分析做什么判断。
2. 指标契约：定义、过滤条件、粒度、时间窗口、数据源和口径风险。
3. 数据事实：从数据中实际计算或观察到了什么。
4. 业务解释：为什么可能发生，必须标注推断和假设。
5. 证据强度：置信度、替代解释、缺失数据和下一步验证。
6. 行动闭环：负责人、建议动作、预期效果、验证指标、风险和复盘时间。

