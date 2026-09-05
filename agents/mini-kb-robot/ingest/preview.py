"""Generate the short one-line preview shown for each entry in the tool
index (kb/tool.py's build_index_text). Text-only entries get a cheap,
dependency-free sentence extraction; entries with images get an Ark
vision-model summary that folds in what the image actually shows, since for
several real entries (e.g. UI-path screenshots) the distinguishing content
lives in the image, not the surrounding text.
"""

from __future__ import annotations

import re

_SENTENCE_END_RE = re.compile(r"[。！？\n]")

VISION_SYSTEM_PROMPT = (
    "You write a one-line Chinese summary (under 40 characters) of one customer-service "
    "FAQ entry, for use as a preview in an index a model scans to pick the right entry. "
    "You're given the question, the answer text (with [图片] marking where an image sits), "
    "and the actual image(s). Fold in anything the image shows that the text doesn't already "
    "say - a UI path, a code, a price, which channel it's for - since that's often the only "
    "thing that distinguishes this entry from a similarly-worded one. Output only the summary "
    "sentence, no preamble, no quotes."
)


def text_preview(answer_text: str, limit: int = 40, min_sentence_len: int = 6) -> str:
    """First sentence (split on 。！？ or newline), truncated further only if
    that first sentence itself still exceeds limit - avoids the previous
    behavior of blindly cutting mid-sentence.

    Skips past a sentence-ender if the fragment before it is shorter than
    min_sentence_len: these answers routinely open with a greeting like
    "您好！" or "亲爱的库米~" before the actual content, and splitting on the
    very first 。！？ would make the preview just that greeting.
    """
    text = answer_text.strip()
    if not text:
        return ""

    first_sentence = text
    pos = 0
    for match in _SENTENCE_END_RE.finditer(text):
        end = match.start()
        if end - pos >= min_sentence_len or end >= limit:
            first_sentence = text[:end]
            break

    if len(first_sentence) > limit:
        return first_sentence[:limit].rstrip() + "…"
    return first_sentence


def build_vision_messages(question: str, answer_text: str, image_urls: list[str]) -> list[dict]:
    content: list[dict] = [
        {
            "type": "text",
            "text": f"问题：{question}\n答案文字：{answer_text}",
        }
    ]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [
        {"role": "system", "content": VISION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


async def vision_preview(client, model: str, question: str, answer_text: str, image_urls: list[str]) -> str:
    """Raises on any failure (network, bad response) - the caller decides
    whether that's a hard build failure or a logged fallback to text_preview.
    """
    messages = build_vision_messages(question, answer_text, image_urls)
    completion = await client.chat.completions.create(model=model, messages=messages)
    summary = (completion.choices[0].message.content or "").strip()
    if not summary:
        raise RuntimeError(f"vision_preview returned empty summary for question {question!r}")
    return summary
