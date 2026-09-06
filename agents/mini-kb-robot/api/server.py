"""FastAPI HTTP layer: POST /chat, GET /health, and the manual test page at /.

No auth, no persistence beyond chat.sessions' in-memory store - this is a
lightweight service for a small knowledge base, not a platform.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

import openai
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from chat.engine import handle_message, handle_message_stream  # noqa: E402
from kb.loader import load_knowledge_base  # noqa: E402
from llm.ark_client import validate_env  # noqa: E402

# Without this, chat/engine.py's per-round timing logs (logger.info) are
# silently dropped - the default root logger level is WARNING, and uvicorn
# doesn't touch it. Only need INFO for our own logger; leave uvicorn's own
# loggers (which already print access logs) alone.
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("mini-kb-robot").setLevel(logging.INFO)

logger = logging.getLogger("mini-kb-robot")

MAX_MESSAGE_LENGTH = 2000

validate_env()
app = FastAPI(title="mini-kb-robot")
# Dev-only convenience: lets an external tool/script on a different origin
# call the API directly (web/index.html itself is same-origin and doesn't need this).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
_kb = load_knowledge_base()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    image_urls: list[str] = []
    matched_entry_id: str | None = None
    status: Literal["answered", "clarifying", "no_match", "error", "escalated"]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    escalated: bool = False
    escalation_reason: str | None = None


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "kb_entries": len(_kb.entries)}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if not req.message.strip():
        return ChatResponse(
            session_id=req.session_id or "",
            reply="请输入您的问题。",
            status="error",
        )

    try:
        result = await handle_message(_kb, req.session_id, req.message)
    except (openai.APIError, openai.APIConnectionError, openai.APITimeoutError):
        logger.exception("Ark call failed")
        return ChatResponse(
            session_id=req.session_id or "",
            reply="抱歉，服务暂时不可用，请稍后再试。",
            status="error",
        )

    return ChatResponse(
        session_id=result.session_id,
        reply=result.reply,
        image_urls=result.image_urls,
        matched_entry_id=result.matched_entry_id,
        status=result.status,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        escalated=result.escalated,
        escalation_reason=result.escalation_reason,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Server-Sent Events version of /chat: 'delta' events carry text chunks
    as they arrive from Ark, followed by one 'done' event with the same
    fields as ChatResponse (session_id/image_urls/matched_entry_id/status -
    those never stream incrementally, they're only known once the model's
    tool call, if any, has resolved).
    """
    if not req.message.strip():
        async def _empty() -> AsyncIterator[str]:
            yield _sse("error", {"message": "请输入您的问题。"})

        return StreamingResponse(_empty(), media_type="text/event-stream")

    async def _gen() -> AsyncIterator[str]:
        try:
            async for event in handle_message_stream(_kb, req.session_id, req.message):
                if event["type"] == "delta":
                    yield _sse("delta", {"text": event["text"]})
                else:
                    yield _sse("done", {k: v for k, v in event.items() if k != "type"})
        except (openai.APIError, openai.APIConnectionError, openai.APITimeoutError):
            logger.exception("Ark call failed mid-stream")
            yield _sse("error", {"message": "抱歉，服务暂时不可用，请稍后再试。"})

    return StreamingResponse(_gen(), media_type="text/event-stream")


# Registered last so /health and /chat above always match first - this mount
# only serves web/index.html (and any other static file) at every other path.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "web", html=True), name="web")
