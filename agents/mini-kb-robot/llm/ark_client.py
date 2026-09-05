"""Thin wrapper around Volcengine Ark's OpenAI-compatible chat-completions API.

Confirmed (not assumed) from livekit-plugins-volcengine/llm.py: Ark is reachable
via the stock `openai.AsyncClient` pointed at Ark's base_url, using standard
OpenAI tool/function-calling schema with no Ark-specific translation needed.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import openai

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


def _exempt_from_proxy(base_url: str) -> None:
    """Ark is a domestic (cn-beijing) endpoint - a locally configured
    HTTP(S)/SOCKS proxy (common on dev machines for reaching services outside
    China) can break the TLS handshake to it instead of helping. Add the host
    to NO_PROXY/no_proxy so the underlying HTTP client talks to Ark directly,
    without touching any proxy setup the user has for other traffic.
    """
    host = urlparse(base_url).hostname
    if not host:
        return
    for var in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(var, "")
        entries = [e.strip() for e in existing.split(",") if e.strip()]
        if host not in entries:
            entries.append(host)
        os.environ[var] = ",".join(entries)


def validate_env() -> None:
    """Fail fast at startup rather than on the first chat request."""
    if not os.environ.get("ARK_API_KEY"):
        raise RuntimeError(
            "ARK_API_KEY is not set - copy .env.example to .env and fill in your "
            "Ark console API key."
        )
    if not os.environ.get("ARK_MODEL"):
        raise RuntimeError(
            "ARK_MODEL is not set - set it in .env to a model name or Endpoint ID "
            "(ep-...) provisioned in your Ark console."
        )


_cached_client: openai.AsyncClient | None = None
_cached_client_key: tuple[str, str] | None = None


def build_client() -> openai.AsyncClient:
    """Reuses one long-lived client (and its underlying HTTP connection pool)
    across calls instead of paying a fresh TCP+TLS handshake on every chat
    request - that handshake cost was pure waste given every request talks to
    the same Ark endpoint. Keyed on (api_key, base_url) so a genuine
    credential change still gets a fresh client, and callers with no
    ARK_API_KEY set still hit the same RuntimeError as before (checked before
    the cache is consulted).
    """
    global _cached_client, _cached_client_key
    api_key = os.environ.get("ARK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ARK_API_KEY is not set - copy .env.example to .env and fill in your "
            "Ark console API key."
        )
    base_url = os.environ.get("ARK_BASE_URL", DEFAULT_BASE_URL)
    key = (api_key, base_url)
    if _cached_client is None or _cached_client_key != key:
        _exempt_from_proxy(base_url)
        _cached_client = openai.AsyncClient(api_key=api_key, base_url=base_url)
        _cached_client_key = key
    return _cached_client


def get_model() -> str:
    model = os.environ.get("ARK_MODEL")
    if not model:
        raise RuntimeError(
            "ARK_MODEL is not set - set it in .env to a model name or Endpoint ID "
            "(ep-...) provisioned in your Ark console."
        )
    return model


def get_vision_model() -> str:
    """Only needed by ingest/build_kb.py, for entries with images - the chat
    runtime never calls this."""
    model = os.environ.get("ARK_VISION_MODEL")
    if not model:
        raise RuntimeError(
            "ARK_VISION_MODEL is not set - this build has entries with images, "
            "which need a vision-capable Ark model/Endpoint ID to summarize. Set "
            "ARK_VISION_MODEL in .env (see .env.example)."
        )
    return model


async def chat_with_tools(
    client: openai.AsyncClient,
    messages: list[dict],
    tools: list[dict],
) -> openai.types.chat.ChatCompletion:
    return await client.chat.completions.create(
        model=get_model(),
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )


async def stream_chat_with_tools(
    client: openai.AsyncClient,
    messages: list[dict],
    tools: list[dict],
):
    """Returns the raw async chunk stream - the tool-call-accumulation logic
    lives in chat/engine.py since it needs to interleave with the tool
    execution loop.

    stream_options={"include_usage": True} makes Ark send one extra trailing
    chunk with an empty `choices` list and a populated `usage` - confirmed in
    livekit-plugins-volcengine/llm.py (same Ark account/API), not guessed.
    """
    return await client.chat.completions.create(
        model=get_model(),
        messages=messages,
        tools=tools,
        tool_choice="auto",
        stream=True,
        stream_options={"include_usage": True},
    )
