from __future__ import annotations

from orders.tool import (
    ORDER_STATUS_TOOL_NAME,
    RECENT_ORDERS_TOOL_NAME,
    build_query_order_status_tool,
    build_query_recent_unfinished_orders_tool,
    execute_query_order_status,
    execute_query_recent_unfinished_orders,
)


def test_recent_orders_tool_schema_takes_no_arguments():
    tool = build_query_recent_unfinished_orders_tool()
    assert tool["function"]["name"] == RECENT_ORDERS_TOOL_NAME
    assert tool["function"]["parameters"]["properties"] == {}
    assert tool["function"]["parameters"]["required"] == []


def test_order_status_tool_schema_requires_order_id():
    tool = build_query_order_status_tool()
    assert tool["function"]["name"] == ORDER_STATUS_TOOL_NAME
    assert tool["function"]["parameters"]["required"] == ["order_id"]
    assert "order_id" in tool["function"]["parameters"]["properties"]


def test_recent_orders_bucket_zero_returns_no_orders():
    assert execute_query_recent_unfinished_orders("scenario-zero-orders-0") == {"orders": []}


def test_recent_orders_bucket_one_returns_one_order():
    result = execute_query_recent_unfinished_orders("scenario-one-order-1")
    assert len(result["orders"]) == 1


def test_recent_orders_bucket_two_returns_two_orders():
    result = execute_query_recent_unfinished_orders("scenario-two-orders-2")
    assert len(result["orders"]) == 2


def test_recent_orders_empty_session_id_falls_back_to_bucket_zero():
    assert execute_query_recent_unfinished_orders("") == {"orders": []}


def test_order_status_even_last_digit_is_not_started():
    result = execute_query_order_status("20260904100234512")
    assert result == {"order_id": "20260904100234512", "status": "not_started"}


def test_order_status_odd_last_digit_is_in_production():
    result = execute_query_order_status("20260905100234511")
    assert result == {"order_id": "20260905100234511", "status": "in_production"}


def test_order_status_no_digits_falls_back_to_not_started():
    result = execute_query_order_status("no-digits-here")
    assert result["status"] == "not_started"
