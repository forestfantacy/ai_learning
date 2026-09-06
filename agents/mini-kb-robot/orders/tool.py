"""Mock order-lookup tools: stand in for a future real order-system
integration, so the wrong-order-handling flow (find order -> confirm ->
cancel-or-contact-store) can be built and tested end-to-end before that
integration exists. Swap the execute_* bodies for real backend calls later -
the tool names/schemas should not need to change.
"""

from __future__ import annotations

RECENT_ORDERS_TOOL_NAME = "query_recent_unfinished_orders"
ORDER_STATUS_TOOL_NAME = "query_order_status"

# MOCK data. Deliberately one even-last-digit id (-> not_started) and one
# odd-last-digit id (-> in_production) so both branches of
# execute_query_order_status are reachable through this list in tests.
_MOCK_ORDERS = [
    {"order_id": "20260904100234512", "store_name": "库迪咖啡人民广场店", "item_summary": "生椰拿铁 x1"},
    {"order_id": "20260905100234511", "store_name": "库迪咖啡静安寺店", "item_summary": "美式咖啡 x2"},
]


def build_query_recent_unfinished_orders_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": RECENT_ORDERS_TOOL_NAME,
            "description": (
                "Look up the user's own unfinished orders from the last 3 "
                "days. Call this first whenever a user says they ordered the "
                "wrong item or picked the wrong store and wants it fixed - "
                "never ask them for an order number up front, this tool finds "
                "the candidates for them. Takes no arguments."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def execute_query_recent_unfinished_orders(session_id: str) -> dict:
    """MOCK - stands in for a real order-system call scoped to the current
    user. Deterministic on the session id's last character so test scenarios
    can pin a session_id and reliably hit all three cases: 0, 1, or 2 orders.
    """
    last_char = session_id[-1] if session_id else "0"
    bucket = ord(last_char) % 3
    orders = [] if bucket == 0 else _MOCK_ORDERS[:bucket]
    return {"orders": orders}


def build_query_order_status_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": ORDER_STATUS_TOOL_NAME,
            "description": (
                "Check whether one specific order has already started being "
                "made. Call this after the user has confirmed or picked which "
                "order they mean - never guess the production status "
                "yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order_id from query_recent_unfinished_orders.",
                    }
                },
                "required": ["order_id"],
            },
        },
    }


def execute_query_order_status(order_id: str) -> dict:
    """MOCK - stands in for a real order-system call. Deterministic on the
    order id's last digit: even -> not started yet, odd -> already in
    production.
    """
    digits = [c for c in order_id if c.isdigit()]
    last_digit = int(digits[-1]) if digits else 0
    status = "not_started" if last_digit % 2 == 0 else "in_production"
    return {"order_id": order_id, "status": status}
