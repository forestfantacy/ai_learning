"""Run tests/test_scenarios.yaml against chat.engine using the real Ark API.

Usage: python scripts/run_scenarios.py

Needs ARK_API_KEY (and ARK_MODEL) set - see .env.example. Skips with a clear
message if they're missing rather than failing confusingly mid-run.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from chat.engine import handle_message  # noqa: E402
from kb.loader import load_knowledge_base  # noqa: E402

SCENARIOS_PATH = Path(__file__).parent.parent / "tests" / "test_scenarios.yaml"


def check_turn(turn: dict, result) -> list[str]:
    failures = []

    if "expect_status" in turn and result.status != turn["expect_status"]:
        failures.append(f"status: expected {turn['expect_status']!r}, got {result.status!r}")

    if "expect_entry_id" in turn and result.matched_entry_id != turn["expect_entry_id"]:
        failures.append(
            f"matched_entry_id: expected {turn['expect_entry_id']!r}, got {result.matched_entry_id!r}"
        )

    if "expect_entry_id_not_in" in turn and result.matched_entry_id in turn["expect_entry_id_not_in"]:
        failures.append(f"matched_entry_id {result.matched_entry_id!r} was in the forbidden set")

    for needle in turn.get("expect_reply_contains", []):
        if needle not in result.reply:
            failures.append(f"reply missing expected text {needle!r}: {result.reply!r}")

    for needle in turn.get("expect_reply_not_contains", []):
        if needle in result.reply:
            failures.append(f"reply contains forbidden text {needle!r}: {result.reply!r}")

    if turn.get("expect_image_urls_nonempty") and not result.image_urls:
        failures.append("expected non-empty image_urls, got none")

    if "expect_escalated" in turn and result.escalated != turn["expect_escalated"]:
        failures.append(f"escalated: expected {turn['expect_escalated']!r}, got {result.escalated!r}")

    if "expect_escalation_reason" in turn and result.escalation_reason != turn["expect_escalation_reason"]:
        failures.append(
            f"escalation_reason: expected {turn['expect_escalation_reason']!r}, got {result.escalation_reason!r}"
        )

    return failures


async def run_scenario(kb, scenario: dict) -> tuple[bool, list[str]]:
    session_id = scenario.get("session_id") or f"scenario-{uuid.uuid4()}"
    failures: list[str] = []
    for i, turn in enumerate(scenario["turns"]):
        result = await handle_message(kb, session_id, turn["message"])
        turn_failures = check_turn(turn, result)
        if turn_failures:
            failures.append(f"  turn {i + 1} ({turn['message']!r}): " + "; ".join(turn_failures))
    return (not failures), failures


async def main() -> None:
    if not os.environ.get("ARK_API_KEY") or not os.environ.get("ARK_MODEL"):
        print("ARK_API_KEY / ARK_MODEL not set - skipping scenario suite (see .env.example).")
        return

    kb = load_knowledge_base()
    scenarios = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))

    passed = 0
    for scenario in scenarios:
        ok, failures = await run_scenario(kb, scenario)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {scenario['name']}")
        for f in failures:
            print(f)
        if ok:
            passed += 1

    total = len(scenarios)
    print(f"\n{passed}/{total} scenarios passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
