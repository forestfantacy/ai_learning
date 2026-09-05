from __future__ import annotations

from kb.loader import KBEntry, KnowledgeBase
from kb.tool import build_lookup_faq_tool, execute_lookup_faq_tool


def _make_kb() -> KnowledgeBase:
    entries = {
        "A": KBEntry(id="A", category="cat", question="联名周边套餐售罄", answer_text="去别的门店", preview="引导去别的门店购买", ambiguous_with=["B"], disambiguation_hint="A 是套餐，去别的门店买"),
        "B": KBEntry(id="B", category="cat", question="联名周边商品售罄", answer_text="正在补货", preview="正在加急补货", ambiguous_with=["A"], disambiguation_hint="B 是单品，原地等补货"),
        "C": KBEntry(id="C", category="cat", question="wifi密码", answer_text="12345678"),
    }
    return KnowledgeBase(entries=entries, generated_at="", source_file="")


def test_enum_matches_all_entry_ids():
    kb = _make_kb()
    tool = build_lookup_faq_tool(kb)
    enum = tool["function"]["parameters"]["properties"]["entry_id"]["enum"]
    assert sorted(enum) == sorted(kb.entries)


def test_ambiguous_entries_marked_in_description():
    kb = _make_kb()
    tool = build_lookup_faq_tool(kb)
    description = tool["function"]["description"]
    assert "⚠️" in description
    assert "A" in description and "B" in description


def test_disambiguation_hint_text_reaches_the_index_not_just_the_warning_marker():
    # Regression test: disambiguation_hint used to be computed and stored but
    # never actually read by build_index_text - only the generic "⚠️ 与 X
    # 相似" line showed up, with no explanation of how they differ.
    kb = _make_kb()
    tool = build_lookup_faq_tool(kb)
    description = tool["function"]["description"]
    assert kb.entries["A"].disambiguation_hint in description
    assert kb.entries["B"].disambiguation_hint in description


def test_preview_field_used_when_present_instead_of_raw_answer_text():
    kb = _make_kb()
    tool = build_lookup_faq_tool(kb)
    description = tool["function"]["description"]
    assert kb.entries["A"].preview in description


def test_missing_preview_falls_back_to_truncated_answer_text():
    kb = _make_kb()
    tool = build_lookup_faq_tool(kb)
    description = tool["function"]["description"]
    assert kb.entries["C"].answer_text[:40] in description


def test_execute_returns_answer_for_known_id():
    kb = _make_kb()
    result = execute_lookup_faq_tool(kb, "C")
    assert result == {"question": "wifi密码", "answer_text": "12345678"}


def test_execute_returns_error_for_unknown_id_without_raising():
    kb = _make_kb()
    result = execute_lookup_faq_tool(kb, "does-not-exist")
    assert "error" in result
