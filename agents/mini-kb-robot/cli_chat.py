"""Local REPL for manual testing - talks to chat.engine directly, no HTTP hop."""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()

from chat.engine import handle_message  # noqa: E402
from kb.loader import load_knowledge_base  # noqa: E402
from llm.ark_client import validate_env  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

SESSION_ID = "local"


async def main() -> None:
    validate_env()
    kb = load_knowledge_base()
    print(f"loaded {len(kb.entries)} knowledge-base entries. Ctrl+C to quit.\n")
    while True:
        try:
            message = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue

        result = await handle_message(kb, SESSION_ID, message)
        print(f"机器人 [{result.status}]: {result.reply}")
        for url in result.image_urls:
            print(f"  [图片] {url}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
