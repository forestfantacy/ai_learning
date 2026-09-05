"""Deterministic knowledge-lookup tool: the model selects one entry id from a
closed enum built from the loaded KnowledgeBase, mirroring the philosophy of
hotel_receptionist's policies/__init__.py (index/enum rebuilt from the corpus
at startup, so it can never drift) - adapted from per-topic-file granularity
to per-question-entry granularity, and expressed as a plain OpenAI-format
tool dict since this project talks to Ark directly via the openai SDK rather
than through livekit-agents' function_tool machinery.
"""

from __future__ import annotations

from kb.loader import KnowledgeBase

TOOL_NAME = "lookup_faq_entry"

_UNKNOWN_ID_ERROR = "unknown entry_id {entry_id!r} - it is not in the knowledge base."


def build_index_text(kb: KnowledgeBase) -> str:
    lines = []
    for e in kb.all_sorted():
        preview = e.preview or e.answer_text[:40]
        line = f"- {e.id}: 「{e.question}」→ {preview}"
        if e.ambiguous_with:
            hint = e.disambiguation_hint or "务必仔细区分"
            line += f"  ⚠️ 与 {', '.join(e.ambiguous_with)} 相似：{hint}"
        lines.append(line)
    return "\n".join(lines)


def build_lookup_faq_tool(kb: KnowledgeBase) -> dict:
    entries = kb.all_sorted()
    index_text = build_index_text(kb)

    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Fetch the exact stored answer for one FAQ knowledge-base entry. "
                "Pick the entry whose question best matches what the user actually "
                "asked. If an entry is marked with ⚠️ (similar to other entries) and "
                "the user's own wording does not make it clear which one they mean, "
                "do not guess - ask a short clarifying question instead and wait for "
                "their answer before calling this tool. If the user's wording clearly "
                "names one specific entry, call this tool for that one even if it "
                "carries a ⚠️ marker - the marker is a caution against guessing between "
                "look-alikes, not a ban on ever selecting a marked entry.\n\nEntries:\n"
                + index_text
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "enum": [e.id for e in entries],
                        "description": "The exact id from the index above.",
                    }
                },
                "required": ["entry_id"],
            },
        },
    }


def execute_lookup_faq_tool(kb: KnowledgeBase, entry_id: str) -> dict:
    entry = kb.get(entry_id)
    if entry is None:
        return {"error": _UNKNOWN_ID_ERROR.format(entry_id=entry_id)}
    return {"question": entry.question, "answer_text": entry.answer_text}
