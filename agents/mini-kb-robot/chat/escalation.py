"""High-risk keyword detection for two categories that must never wait on
model judgment: self-harm crisis signals, and regulatory/media escalation
threats. Both short-circuit chat/engine.py before any LLM call.

Also detects reflexive "transfer me to a human" requests with no explained
problem - those don't short-circuit, they drive a code-owned 2-strike counter
(chat/engine.py) so the first ask gets redirected and only a second ask is
actually honored, regardless of whether the model complies with the redirect.
"""

from __future__ import annotations

from typing import Literal

HighRiskCategory = Literal["self_harm", "regulatory"]

# 自伤/自杀类信号 - 命中即用固定安全话术，不经过模型生成。
_SELF_HARM_PHRASES = (
    "自杀", "跳楼", "自残", "割腕", "轻生", "寻短见", "喝药",
    "上吊", "死在门店", "出人命", "猝死",
)

# 监管投诉/媒体升级类信号 - 命中即用固定话术转人工，不经过模型生成。
_REGULATORY_PHRASES = (
    "12315", "市场监管", "消协", "12345", "信访", "工商局",
    "市监局", "税务稽查", "12305", "12366", "找媒体", "投诉315",
)

# 无头无尾要求转人工 - 第一次先引导说明问题，第二次才真正放行。
# 精准匹配：整条消息(去空白后)完全等于这些词才算命中 - 避免"人工"/"客服"这类
# 短词出现在无关长句子里被误判(例如"之前客服跟我说过..."不该算转人工请求)。
_TRANSFER_EXACT_WORDS = (
    "人工", "客服", "真人", "人工客服", "在线客服", "工作人员",
    "客服人员", "专员", "顾问", "举报", "人工服务",
)
_TRANSFER_EXACT_PINYIN = (
    "rengongkefu", "转rengong", "zhuanrengong", "rengong",
)

# 包含匹配：这些短语本身已经足够具体，出现在消息任意位置就算命中。
_TRANSFER_CONTAINS_PHRASES = (
    "转人工", "转人工客服", "帮我转人工", "请转人工", "我要人工", "我要找人工",
    "接入人工", "转真人", "转客服", "人工介入", "需要人工介入", "我要投诉",
    "我要举报", "转人",
)


def detect_high_risk(text: str) -> HighRiskCategory | None:
    if any(p in text for p in _SELF_HARM_PHRASES):
        return "self_harm"
    if any(p in text for p in _REGULATORY_PHRASES):
        return "regulatory"
    return None


def is_transfer_request(text: str) -> bool:
    stripped = text.strip()
    if stripped in _TRANSFER_EXACT_WORDS:
        return True
    if stripped.lower() in _TRANSFER_EXACT_PINYIN:
        return True
    return any(p in text for p in _TRANSFER_CONTAINS_PHRASES)


# Safety net for when is_transfer_request misses a second, differently-worded
# insistence ("你解决不了，给我转") and the model tells the user it escalated
# anyway despite the redirect note - the reply must never claim a handoff the
# system state doesn't also record, so this reconciles the two after the fact.
_ESCALATION_CLAIM_PHRASES = (
    "已经为您转", "已为您转", "已经为你转", "已为你转",
    "已经转接人工", "已转接人工", "转接人工客服", "已经帮您转接", "已经帮你转接",
    "已经为您接入人工", "人工客服会尽快",
)


def reply_claims_escalation(reply_text: str) -> bool:
    return any(p in reply_text for p in _ESCALATION_CLAIM_PHRASES)
