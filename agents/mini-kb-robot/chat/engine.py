"""Core turn loop: user message in -> Ark call -> tool exec -> final reply.

Retrieval (which knowledge entry, if any) is decided entirely by the model's
closed-enum tool call (kb/tool.py) - this module never does its own text
matching. Image URLs are attached here, programmatically, straight from the
matched knowledge-base entry - never left to the model to type out, so it
can't hallucinate or mangle a URL.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from chat.escalation import detect_high_risk, is_transfer_request, reply_claims_escalation
from chat.sessions import SessionState, append_turn, get_or_create
from kb.loader import KnowledgeBase
from kb.tool import TOOL_NAME, build_lookup_faq_tool, execute_lookup_faq_tool
from llm.ark_client import build_client, chat_with_tools, stream_chat_with_tools
from llm.instructions import SYSTEM_PROMPT
from orders.tool import (
    ORDER_STATUS_TOOL_NAME,
    RECENT_ORDERS_TOOL_NAME,
    build_query_order_status_tool,
    build_query_recent_unfinished_orders_tool,
    execute_query_order_status,
    execute_query_recent_unfinished_orders,
)

logger = logging.getLogger("mini-kb-robot")

_URL_RE = re.compile(r"https?://\S+")

MAX_TOOL_ROUNDS = 4

# Existing FAQ entry ("客服电话") reused as the grounded text for every
# transfer-to-human reply - never invent a hotline/contact path of our own.
CUSTOMER_SERVICE_ENTRY_ID = "09566022959"

_SELF_HARM_REPLY = (
    "非常抱歉听到你现在这么难受，你的安全对我们很重要。如果你有伤害自己的想法，"
    "请立即拨打全国心理援助热线 12356，或拨打 120/110 寻求紧急帮助，"
    "也可以联系身边信任的人陪着你。我已经同时为你转接人工客服，会有人尽快跟进。"
)

_ATTITUDE_COMPLAINT_FIRST_TEXT = "抱歉给您带来不好的体验～我们非常重视您的反馈，后续会加强改进，期待下次为您提供更优质的服务～"
_ATTITUDE_COMPLAINT_REPEAT_TEXT = "感谢您的及时反馈，填写下方留言卡片，我们会立即核查处理~"

_QUALITY_COMPLAINT_FIRST_TEXT = (
    "您好，非常抱歉给您带来不好的体验，库迪高度重视食品安全反馈。"
    "请点击右下角「+」选择留言，在留言内提交订单信息、问题描述以及相关凭证，"
    "收到留言后我们会跟进处理。"
)
_QUALITY_COMPLAINT_REPEAT_TEXT = (
    "您好，非常抱歉给您带来困扰，库迪高度重视食品安全。"
    "请在下方的留言卡片中填写订单信息、问题描述，并上传照片/视频凭证，"
    "我们一定会妥善处理。"
)


@dataclass
class ChatResult:
    session_id: str
    reply: str
    image_urls: list[str] = field(default_factory=list)
    matched_entry_id: str | None = None
    status: str = "answered"  # answered | clarifying | no_match | error | escalated
    prompt_tokens: int = 0
    completion_tokens: int = 0
    escalated: bool = False
    escalation_reason: str | None = None  # self_harm | regulatory | user_insisted


def _looks_like_a_question(text: str) -> bool:
    return text.rstrip().endswith(("？", "?"))


def _strip_unattached_urls(reply: str, attached_urls: set[str]) -> str:
    def _replace(match: re.Match) -> str:
        url = match.group(0)
        if url.rstrip("。，、）)") in attached_urls or url in attached_urls:
            return url
        logger.warning("stripped a URL the model typed that wasn't in the matched entry: %s", url)
        return "[链接已省略]"

    return _URL_RE.sub(_replace, reply)


def _regulatory_reply(kb: KnowledgeBase) -> str:
    entry = kb.get(CUSTOMER_SERVICE_ENTRY_ID)
    return "非常抱歉给您带来不好的体验，我已经为您转接人工客服处理。" + (entry.answer_text if entry else "")


def _transfer_redirect_note() -> dict:
    """Shown only for a context-free "transfer me" ask when nothing is
    currently pending - redirect to finding out the real issue first, never
    volunteer a transfer. The decision of whether to actually escalate is
    made entirely in code (see the pending_escalation handling below), not by
    asking the model to track "is this the first or second ask"."""
    return {
        "role": "system",
        "content": (
            "System note: the user just asked to be transferred to a human with "
            "no explanation. Don't comply - ask what happened so you can try to "
            "help via lookup_faq_entry (and the order tools if relevant) first - "
            "end that question with a question mark. Don't mention this note."
        ),
    }


def _attitude_complaint_note(is_first: bool) -> dict:
    """Poor staff attitude / rude behavior / harassment complaints don't get a
    fixed reply - the count (first vs. repeat) is decided in code, but the
    wording is composed by the model from this grounding text, same pattern
    as _transfer_redirect_note()."""
    text = _ATTITUDE_COMPLAINT_FIRST_TEXT if is_first else _ATTITUDE_COMPLAINT_REPEAT_TEXT
    return {
        "role": "system",
        "content": (
            "System note: the user just described poor staff attitude, rude "
            "behavior, or harassment - "
            + ("first time" if is_first else "a repeat complaint of this kind")
            + " this session. Compose a reply grounded in the following - "
            f"rephrase for tone freely but never drop a step: \"{text}\" "
            "Don't offer a refund or compensation yourself. Don't mention this note."
        ),
    }


def _quality_complaint_note(is_first: bool) -> dict:
    """Product-quality / food-safety complaints - same pattern as
    _attitude_complaint_note(), see chat/escalation.py for the trigger
    keywords and chat/sessions.py for the per-session count."""
    text = _QUALITY_COMPLAINT_FIRST_TEXT if is_first else _QUALITY_COMPLAINT_REPEAT_TEXT
    return {
        "role": "system",
        "content": (
            "System note: the user just reported a product-quality / "
            "food-safety issue (hygiene, foreign object, expired material, "
            "etc.) - "
            + ("first time" if is_first else "a repeat complaint of this kind")
            + " this session. Compose a reply grounded in the following - "
            f"rephrase for tone freely but never drop a step: \"{text}\" "
            "Don't offer a refund or compensation yourself. Don't mention this note."
        ),
    }


FLAG_COMPLAINT_TOOL_NAME = "flag_complaint_category"


def build_flag_complaint_tool() -> dict:
    """Fallback for quality_complaint/attitude_complaint phrasing that
    detect_high_risk's keyword scan misses (e.g. "肚子开始疼了" doesn't
    contain the literal substring "肚子疼"). Only offered to the model when
    the keyword scan already came up empty (risk is None) - a keyword hit
    already injects a note and increments the counter, so offering this tool
    then would risk double-counting the same complaint."""
    return {
        "type": "function",
        "function": {
            "name": FLAG_COMPLAINT_TOOL_NAME,
            "description": (
                "Call this when the user's message describes a product-quality / "
                "food-safety issue (hygiene, a foreign object, expired material, "
                "feeling unwell after drinking, etc.) or poor staff attitude / rude "
                "behavior / harassment, and lookup_faq_entry has no better specific "
                "match for it. Returns grounding text to compose your reply from - "
                "rephrase for tone freely but never drop a step, and never offer a "
                "refund or compensation yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["quality_complaint", "attitude_complaint"],
                        "description": (
                            "quality_complaint for product-quality/food-safety issues, "
                            "attitude_complaint for staff attitude/rudeness/harassment."
                        ),
                    }
                },
                "required": ["category"],
            },
        },
    }


def execute_flag_complaint_category(state: SessionState, category: str) -> dict:
    if category == "quality_complaint":
        state.quality_complaint_count += 1
        is_first = state.quality_complaint_count == 1
        text = _QUALITY_COMPLAINT_FIRST_TEXT if is_first else _QUALITY_COMPLAINT_REPEAT_TEXT
    elif category == "attitude_complaint":
        state.attitude_complaint_count += 1
        is_first = state.attitude_complaint_count == 1
        text = _ATTITUDE_COMPLAINT_FIRST_TEXT if is_first else _ATTITUDE_COMPLAINT_REPEAT_TEXT
    else:
        return {"error": f"unknown category {category!r} - must be quality_complaint or attitude_complaint."}
    return {"must_ground_reply_in": text}


def _grounded_transfer_text(kb: KnowledgeBase) -> str:
    entry = kb.get(CUSTOMER_SERVICE_ENTRY_ID)
    return "非常抱歉还是没能帮您解决，我已经为您转接人工客服处理。" + (entry.answer_text if entry else "")


async def handle_message(kb: KnowledgeBase, session_id: str | None, message: str) -> ChatResult:
    resolved_session_id, state = get_or_create(session_id)
    turn_start = time.monotonic()

    risk = detect_high_risk(message)
    if risk == "self_harm":
        logger.warning("session %s: self-harm signal matched, short-circuiting", resolved_session_id)
        return ChatResult(
            session_id=resolved_session_id,
            reply=_SELF_HARM_REPLY,
            status="escalated",
            escalated=True,
            escalation_reason="self_harm",
        )
    if risk == "regulatory":
        logger.warning("session %s: regulatory-escalation signal matched, short-circuiting", resolved_session_id)
        return ChatResult(
            session_id=resolved_session_id,
            reply=_regulatory_reply(kb),
            matched_entry_id=CUSTOMER_SERVICE_ENTRY_ID,
            status="escalated",
            escalated=True,
            escalation_reason="regulatory",
        )
    was_pending = state.pending_escalation
    # A redirect turn only ever asks "what's wrong" - it never counts as a real
    # resolution attempt, so it must never arm pending_escalation, regardless of
    # how _looks_like_a_question happens to classify the model's phrasing.
    redirect_injected = not was_pending and is_transfer_request(message)

    attitude_note_injected = risk == "attitude_complaint"
    if attitude_note_injected:
        state.attitude_complaint_count += 1
    quality_note_injected = risk == "quality_complaint"
    if quality_note_injected:
        state.quality_complaint_count += 1

    tools = [build_lookup_faq_tool(kb), build_query_recent_unfinished_orders_tool(), build_query_order_status_tool()]
    # Only offered when the keyword scan found nothing - a keyword hit already
    # injects a note and increments the counter above, so offering this tool
    # too would risk the model double-flagging the same complaint.
    if risk is None:
        tools.append(build_flag_complaint_tool())
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *state.history]
    if redirect_injected:
        messages.append(_transfer_redirect_note())
    if attitude_note_injected:
        messages.append(_attitude_complaint_note(state.attitude_complaint_count == 1))
    if quality_note_injected:
        messages.append(_quality_complaint_note(state.quality_complaint_count == 1))
    messages.append({"role": "user", "content": message})

    client = build_client()
    new_messages: list[dict] = [{"role": "user", "content": message}]

    matched_entry_id: str | None = None
    complaint_flagged = False
    image_urls: list[str] = []
    links: list[str] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        round_start = time.monotonic()
        completion = await chat_with_tools(client, messages, tools)
        logger.info(
            "session %s round %d: %dms (tool_call=%s)",
            resolved_session_id,
            round_num,
            round(1000 * (time.monotonic() - round_start)),
            completion.choices[0].message.tool_calls is not None,
        )
        if completion.usage is not None:
            total_prompt_tokens += completion.usage.prompt_tokens
            total_completion_tokens += completion.usage.completion_tokens
        choice = completion.choices[0].message

        if not choice.tool_calls:
            reply_text = choice.content or ""
            new_messages.append({"role": "assistant", "content": reply_text})
            append_turn(state, new_messages)

            attached = set(image_urls) | set(links)
            reply_text = _strip_unattached_urls(reply_text, attached)

            status = "clarifying" if _looks_like_a_question(reply_text) else "no_match"
            if matched_entry_id is not None or attitude_note_injected or quality_note_injected or complaint_flagged:
                status = "answered"

            escalated_now = False
            escalation_reason: str | None = None

            if was_pending:
                if status == "answered":
                    state.pending_escalation = False
                elif status == "no_match":
                    escalated_now = True
                    escalation_reason = "unresolved_after_retry"
                    state.pending_escalation = False
                    reply_text = reply_text.rstrip() + "\n\n" + _grounded_transfer_text(kb)
                    status = "escalated"
                # status == "clarifying": still making progress, keep pending as-is.
            elif status == "no_match" and not redirect_injected:
                state.pending_escalation = True

            if not escalated_now and reply_claims_escalation(reply_text):
                logger.warning(
                    "session %s: reply claims an escalation the counter didn't grant - reconciling state",
                    resolved_session_id,
                )
                escalated_now = True
                escalation_reason = "model_claimed"
                status = "escalated"

            return ChatResult(
                session_id=resolved_session_id,
                reply=reply_text,
                image_urls=image_urls,
                matched_entry_id=matched_entry_id,
                status=status,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                escalated=escalated_now,
                escalation_reason=escalation_reason,
            )

        assistant_msg = {
            "role": "assistant",
            "content": choice.content,
            "tool_calls": [tc.model_dump() for tc in choice.tool_calls],
        }
        messages.append(assistant_msg)
        new_messages.append(assistant_msg)

        for tool_call in choice.tool_calls:
            args = json.loads(tool_call.function.arguments or "{}")
            name = tool_call.function.name

            if name == RECENT_ORDERS_TOOL_NAME:
                result = execute_query_recent_unfinished_orders(resolved_session_id)
            elif name == ORDER_STATUS_TOOL_NAME:
                order_id = str(args.get("order_id", ""))
                result = execute_query_order_status(order_id)
            elif name == FLAG_COMPLAINT_TOOL_NAME:
                category = str(args.get("category", ""))
                result = execute_flag_complaint_category(state, category)
                if "error" not in result:
                    complaint_flagged = True
            else:
                entry_id = str(args.get("entry_id", ""))
                result = execute_lookup_faq_tool(kb, entry_id)
                if "error" not in result:
                    matched_entry_id = entry_id
                    entry = kb.get(entry_id)
                    if entry:
                        image_urls.extend(u for u in entry.image_urls if u not in image_urls)
                        links.extend(link.url for link in entry.links if link.url not in links)

            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
            messages.append(tool_msg)
            new_messages.append(tool_msg)

    # Ran out of tool rounds without a final text reply - fail safe rather than loop forever.
    logger.warning("session %s hit MAX_TOOL_ROUNDS without a final reply", resolved_session_id)
    append_turn(state, new_messages)
    return ChatResult(
        session_id=resolved_session_id,
        reply="抱歉，这个问题我暂时处理不了，请稍后再试或换个说法问我。",
        status="error",
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
    )


async def handle_message_stream(
    kb: KnowledgeBase, session_id: str | None, message: str
) -> AsyncIterator[dict]:
    """Same tool-calling turn loop as handle_message, but yields text as it
    streams in from Ark instead of waiting for the full reply.

    Yields {"type": "delta", "text": ...} chunks as content arrives, followed
    by exactly one {"type": "done", ...ChatResult fields...} at the end.

    Note: the stray-URL guardrail in handle_message can retroactively redact
    a URL because it sees the full text before returning it; a true stream
    can't un-send characters already flushed to the client, so here the same
    scan only logs a warning (still useful signal, just not a redaction) -
    the primary defense stays the system prompt telling the model never to
    type a URL itself, and image URLs are attached out-of-band regardless.
    """
    resolved_session_id, state = get_or_create(session_id)
    turn_start = time.monotonic()
    first_token_logged = False

    risk = detect_high_risk(message)
    if risk in ("self_harm", "regulatory"):
        if risk == "self_harm":
            logger.warning("session %s: self-harm signal matched, short-circuiting", resolved_session_id)
            reply = _SELF_HARM_REPLY
            reason = "self_harm"
            matched_id = None
        else:
            logger.warning("session %s: regulatory-escalation signal matched, short-circuiting", resolved_session_id)
            reply = _regulatory_reply(kb)
            reason = "regulatory"
            matched_id = CUSTOMER_SERVICE_ENTRY_ID
        status = "escalated"
        escalated = True
        yield {"type": "delta", "text": reply}
        yield {
            "type": "done",
            "session_id": resolved_session_id,
            "reply": reply,
            "image_urls": [],
            "matched_entry_id": matched_id,
            "status": status,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "escalated": escalated,
            "escalation_reason": reason,
        }
        return

    was_pending = state.pending_escalation
    redirect_injected = not was_pending and is_transfer_request(message)

    attitude_note_injected = risk == "attitude_complaint"
    if attitude_note_injected:
        state.attitude_complaint_count += 1
    quality_note_injected = risk == "quality_complaint"
    if quality_note_injected:
        state.quality_complaint_count += 1

    tools = [build_lookup_faq_tool(kb), build_query_recent_unfinished_orders_tool(), build_query_order_status_tool()]
    if risk is None:
        tools.append(build_flag_complaint_tool())
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *state.history]
    if redirect_injected:
        messages.append(_transfer_redirect_note())
    if attitude_note_injected:
        messages.append(_attitude_complaint_note(state.attitude_complaint_count == 1))
    if quality_note_injected:
        messages.append(_quality_complaint_note(state.quality_complaint_count == 1))
    messages.append({"role": "user", "content": message})

    client = build_client()
    new_messages: list[dict] = [{"role": "user", "content": message}]

    matched_entry_id: str | None = None
    complaint_flagged = False
    image_urls: list[str] = []
    links: list[str] = []
    full_text = ""
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        round_start = time.monotonic()
        stream = await stream_chat_with_tools(client, messages, tools)

        round_text = ""
        tool_call_acc: dict[int, dict] = {}

        async for chunk in stream:
            if chunk.usage is not None:
                total_prompt_tokens += chunk.usage.prompt_tokens
                total_completion_tokens += chunk.usage.completion_tokens
            if not chunk.choices:
                continue  # the usage-only trailing chunk has no delta to process

            choice = chunk.choices[0]
            delta = choice.delta

            if delta.content:
                if not first_token_logged:
                    first_token_logged = True
                    logger.info(
                        "session %s first token after %dms (round %d)",
                        resolved_session_id,
                        round(1000 * (time.monotonic() - turn_start)),
                        round_num,
                    )
                round_text += delta.content
                full_text += delta.content
                yield {"type": "delta", "text": delta.content}

            for tc in delta.tool_calls or []:
                acc = tool_call_acc.setdefault(tc.index, {"id": None, "name": None, "arguments": ""})
                if tc.id:
                    acc["id"] = tc.id
                if tc.function and tc.function.name:
                    acc["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    acc["arguments"] += tc.function.arguments

        logger.info(
            "session %s round %d: %dms (tool_call=%s)",
            resolved_session_id,
            round_num,
            round(1000 * (time.monotonic() - round_start)),
            bool(tool_call_acc),
        )

        if not tool_call_acc:
            new_messages.append({"role": "assistant", "content": round_text})
            append_turn(state, new_messages)

            attached = set(image_urls) | set(links)
            for match in _URL_RE.finditer(full_text):
                url = match.group(0)
                if url.rstrip("。，、）)") not in attached and url not in attached:
                    logger.warning("model streamed a URL not in the matched entry: %s", url)

            status = "clarifying" if _looks_like_a_question(full_text) else "no_match"
            if matched_entry_id is not None or attitude_note_injected or quality_note_injected or complaint_flagged:
                status = "answered"

            escalated_now = False
            escalation_reason: str | None = None

            if was_pending:
                if status == "answered":
                    state.pending_escalation = False
                elif status == "no_match":
                    escalated_now = True
                    escalation_reason = "unresolved_after_retry"
                    state.pending_escalation = False
                    appended = "\n\n" + _grounded_transfer_text(kb)
                    full_text = full_text.rstrip() + appended
                    yield {"type": "delta", "text": appended}
                    status = "escalated"
                # status == "clarifying": still making progress, keep pending as-is.
            elif status == "no_match" and not redirect_injected:
                state.pending_escalation = True

            if not escalated_now and reply_claims_escalation(full_text):
                logger.warning(
                    "session %s: reply claims an escalation the counter didn't grant - reconciling state",
                    resolved_session_id,
                )
                escalated_now = True
                escalation_reason = "model_claimed"
                status = "escalated"

            yield {
                "type": "done",
                "session_id": resolved_session_id,
                "reply": full_text,
                "image_urls": image_urls,
                "matched_entry_id": matched_entry_id,
                "status": status,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "escalated": escalated_now,
                "escalation_reason": escalation_reason,
            }
            return

        tool_calls_sorted = [tool_call_acc[i] for i in sorted(tool_call_acc)]
        assistant_msg = {
            "role": "assistant",
            "content": round_text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls_sorted
            ],
        }
        messages.append(assistant_msg)
        new_messages.append(assistant_msg)

        for tc in tool_calls_sorted:
            args = json.loads(tc["arguments"] or "{}")
            name = tc["name"]

            if name == RECENT_ORDERS_TOOL_NAME:
                result = execute_query_recent_unfinished_orders(resolved_session_id)
            elif name == ORDER_STATUS_TOOL_NAME:
                order_id = str(args.get("order_id", ""))
                result = execute_query_order_status(order_id)
            elif name == FLAG_COMPLAINT_TOOL_NAME:
                category = str(args.get("category", ""))
                result = execute_flag_complaint_category(state, category)
                if "error" not in result:
                    complaint_flagged = True
            else:
                entry_id = str(args.get("entry_id", ""))
                result = execute_lookup_faq_tool(kb, entry_id)
                if "error" not in result:
                    matched_entry_id = entry_id
                    entry = kb.get(entry_id)
                    if entry:
                        image_urls.extend(u for u in entry.image_urls if u not in image_urls)
                        links.extend(link.url for link in entry.links if link.url not in links)

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False),
            }
            messages.append(tool_msg)
            new_messages.append(tool_msg)

    logger.warning("session %s hit MAX_TOOL_ROUNDS without a final reply", resolved_session_id)
    append_turn(state, new_messages)
    fallback = "抱歉，这个问题我暂时处理不了，请稍后再试或换个说法问我。"
    yield {"type": "delta", "text": fallback}
    yield {
        "type": "done",
        "session_id": resolved_session_id,
        "reply": fallback,
        "image_urls": [],
        "matched_entry_id": None,
        "status": "error",
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
    }
