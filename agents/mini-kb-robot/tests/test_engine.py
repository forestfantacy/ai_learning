from __future__ import annotations

from chat.engine import build_flag_complaint_tool, execute_flag_complaint_category
from chat.sessions import SessionState


def test_flag_complaint_tool_enum_has_both_categories():
    tool = build_flag_complaint_tool()
    enum = tool["function"]["parameters"]["properties"]["category"]["enum"]
    assert sorted(enum) == sorted(["attitude_complaint", "quality_complaint"])


def test_first_quality_complaint_returns_first_text_and_increments_count():
    state = SessionState()
    result = execute_flag_complaint_category(state, "quality_complaint")
    assert state.quality_complaint_count == 1
    assert "留言" in result["must_ground_reply_in"]
    assert "留言卡片" not in result["must_ground_reply_in"]


def test_second_quality_complaint_returns_repeat_text():
    state = SessionState()
    execute_flag_complaint_category(state, "quality_complaint")
    result = execute_flag_complaint_category(state, "quality_complaint")
    assert state.quality_complaint_count == 2
    assert "留言卡片" in result["must_ground_reply_in"]


def test_first_attitude_complaint_returns_first_text_and_increments_count():
    state = SessionState()
    result = execute_flag_complaint_category(state, "attitude_complaint")
    assert state.attitude_complaint_count == 1
    assert "留言" not in result["must_ground_reply_in"]


def test_second_attitude_complaint_returns_repeat_text():
    state = SessionState()
    execute_flag_complaint_category(state, "attitude_complaint")
    result = execute_flag_complaint_category(state, "attitude_complaint")
    assert state.attitude_complaint_count == 2
    assert "留言" in result["must_ground_reply_in"]


def test_quality_and_attitude_counters_are_independent():
    state = SessionState()
    execute_flag_complaint_category(state, "quality_complaint")
    execute_flag_complaint_category(state, "attitude_complaint")
    assert state.quality_complaint_count == 1
    assert state.attitude_complaint_count == 1


def test_unknown_category_returns_error_without_touching_counters():
    state = SessionState()
    result = execute_flag_complaint_category(state, "something_else")
    assert "error" in result
    assert state.quality_complaint_count == 0
    assert state.attitude_complaint_count == 0
