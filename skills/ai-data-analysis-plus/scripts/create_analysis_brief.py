#!/usr/bin/env python3
"""为 AI 数据分析 SOP 生成 Markdown 报告骨架。"""

from __future__ import annotations

import argparse
from pathlib import Path


TEMPLATE = """# {title}

## 决策目标
| 项目 | 内容 |
|-|-|
| 使用者 | {stakeholder} |
| 要支持的决策 | {decision} |
| 可能影响的动作 |  |
| 关键假设 |  |

## 数据盘点和质量
| 数据集 | 行数 | 粒度 | 时间范围 | 关联键 | 质量说明 |
|-|-|-|-|-|-|

## 候选分析目标
| 排名 | 目标 | 业务价值 | 数据支持度 | 可行动性 | 为什么现在看 |
|-|-|-|-|-|-|

## 指标契约
| 指标 | 业务对象 | 粒度 | 分子 | 分母 | 时间口径 | 过滤条件 | 数据源 | 口径风险 |
|-|-|-|-|-|-|-|-|-|

## 业务模型
- 业务实体：
- 结果指标：
- 过程指标：
- 基础字段：
- 分析维度：
- 关键公式：

## 关键发现
| 发现 | 数据事实 | 业务解释 | 置信度 | 替代解释 |
|-|-|-|-|-|

## 归因证据
| 发现 | 当前证据 | 候选原因 | 需要验证 | 置信度 | 下一步 |
|-|-|-|-|-|-|

## 预测或情景分析
| 情景 | 假设 | 预期影响 | 风险 |
|-|-|-|-|

## 行动方案
| 目标问题 | 建议动作 | 负责人 | 预期效果 | 验证指标 | 风险 | 复盘时间 |
|-|-|-|-|-|-|-|

## 可复现性
- 使用文件/数据表：
- 过滤条件：
- 清洗步骤：
- 脚本/查询：
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 AI 数据分析 SOP 报告骨架。")
    parser.add_argument("--title", required=True, help="报告标题。")
    parser.add_argument("--stakeholder", default="", help="主要使用者或决策者。")
    parser.add_argument("--decision", default="", help="本次分析要支持的决策。")
    parser.add_argument("--output", required=True, help="输出 Markdown 路径。")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出文件。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output)
    if output.exists() and not args.overwrite:
        raise SystemExit(f"拒绝覆盖已存在文件：{output}")

    content = TEMPLATE.format(
        title=args.title.strip(),
        stakeholder=args.stakeholder.strip(),
        decision=args.decision.strip(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

