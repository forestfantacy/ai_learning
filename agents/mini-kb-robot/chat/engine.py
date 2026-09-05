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

from chat.sessions import append_turn, get_or_create
from kb.loader import KnowledgeBase
from kb.tool import TOOL_NAME, build_lookup_faq_tool, execute_lookup_faq_tool
from llm.ark_client import build_client, chat_with_tools, stream_chat_with_tools
from llm.instructions import SYSTEM_PROMPT

logger = logging.getLogger("mini-kb-robot")

_URL_RE = re.compile(r"https?://\S+")

MAX_TOOL_ROUNDS = 3


@dataclass
class ChatResult:
    session_id: str
    reply: str
    image_urls: list[str] = field(default_factory=list)
    matched_entry_id: str | None = None
    status: str = "answered"  # answered | clarifying | no_match | error
    prompt_tokens: int = 0
    completion_tokens: int = 0


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


async def handle_message(kb: KnowledgeBase, session_id: str | None, message: str) -> ChatResult:
    resolved_session_id, state = get_or_create(session_id)
    turn_start = time.monotonic()

    tool_schema = build_lookup_faq_tool(kb)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *state.history, {"role": "user", "content": message}]

    client = build_client()
    new_messages: list[dict] = [{"role": "user", "content": message}]

    matched_entry_id: str | None = None
    image_urls: list[str] = []
    links: list[str] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        round_start = time.monotonic()
        completion = await chat_with_tools(client, messages, [tool_schema])
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
            if matched_entry_id is not None:
                status = "answered"
            return ChatResult(
                session_id=resolved_session_id,
                reply=reply_text,
                image_urls=image_urls,
                matched_entry_id=matched_entry_id,
                status=status,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
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

    tool_schema = build_lookup_faq_tool(kb)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *state.history, {"role": "user", "content": message}]

    client = build_client()
    new_messages: list[dict] = [{"role": "user", "content": message}]

    matched_entry_id: str | None = None
    image_urls: list[str] = []
    links: list[str] = []
    full_text = ""
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        round_start = time.monotonic()
        stream = await stream_chat_with_tools(client, messages, [tool_schema])

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
            if matched_entry_id is not None:
                status = "answered"
            yield {
                "type": "done",
                "session_id": resolved_session_id,
                "reply": full_text,
                "image_urls": image_urls,
                "matched_entry_id": matched_entry_id,
                "status": status,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
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
