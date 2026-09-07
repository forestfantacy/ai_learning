"""High-risk keyword detection for two categories that must never wait on
model judgment: self-harm crisis signals, and regulatory/media escalation
threats. Both short-circuit chat/engine.py before any LLM call.

Also detects two complaint categories - product-quality/food-safety and
service-attitude/harassment - that do NOT short-circuit. Instead
chat/engine.py counts occurrences per session and injects a system note
carrying grounding text for the model to compose from (rephrase for tone,
never drop a step), same pattern as the transfer-redirect note below.

Also detects reflexive "transfer me to a human" requests with no explained
problem - those don't short-circuit, they drive a code-owned 2-strike counter
(chat/engine.py) so the first ask gets redirected and only a second ask is
actually honored, regardless of whether the model complies with the redirect.
"""

from __future__ import annotations

from typing import Literal

HighRiskCategory = Literal["self_harm", "regulatory", "quality_complaint", "attitude_complaint"]

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

# 产品质量/食品安全投诉信号 - 命中后由 chat/engine.py 按会话内命中次数注入
# system note（带基准文案），模型据此组稿，不再直接短路返回固定字符串。
_QUALITY_COMPLAINT_PHRASES = (
    "卫生条件差", "卫生太脏", "卫生不敢恭维", "食品安全问题",
    "质量有问题", "质量堪忧", "产品质量差", "产品质量太差", "产品质量非常差",
    "店员不洗手", "店员美甲", "指甲油", "偷工减料",
    "喝出了虫子", "眼睫毛", "头发", "毛发", "玻璃片", "锡纸", "螺丝",
    "小生物", "蚊子", "小飞虫", "苍蝇", "脏东西",
    "肚子", "使用过期物料", "超保质期",
)

# 服务态度/骚扰类投诉信号 - 和 quality_complaint 一样，命中后由
# chat/engine.py 按会话内命中次数注入 system note，不短路。
_ATTITUDE_COMPLAINT_PHRASES = (
    "态度恶劣", "背后议论人", "在那摔东西", "拿东西噼里啪啦的", "脸色特难看",
    "口吐芬芳脏话", "激烈争执", "情绪激动", "恶意骚扰", "侵犯隐私",
    "阴阳怪气", "指桑骂槐", "电话骚扰", "短信骚扰", "辱骂",
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
    if any(p in text for p in _QUALITY_COMPLAINT_PHRASES):
        return "quality_complaint"
    if any(p in text for p in _ATTITUDE_COMPLAINT_PHRASES):
        return "attitude_complaint"
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
