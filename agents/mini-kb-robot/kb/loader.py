"""Load data/knowledge_base.json into an in-memory, queryable KnowledgeBase.

The service never parses the source xlsx at request time - `ingest/build_kb.py`
is the only thing that touches it. This module just loads the compiled JSON
artifact that script produces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_KB_PATH = Path(__file__).parent.parent / "data" / "knowledge_base.json"


@dataclass
class Link:
    text: str
    url: str


@dataclass
class KBEntry:
    id: str
    category: str
    question: str
    answer_text: str
    preview: str = ""
    image_urls: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    ambiguous_with: list[str] = field(default_factory=list)
    disambiguation_hint: str | None = None


@dataclass
class KnowledgeBase:
    entries: dict[str, KBEntry]
    generated_at: str
    source_file: str

    def get(self, entry_id: str) -> KBEntry | None:
        return self.entries.get(entry_id)

    def all_sorted(self) -> list[KBEntry]:
        return sorted(self.entries.values(), key=lambda e: e.id)


def load_knowledge_base(path: Path | str = DEFAULT_KB_PATH) -> KnowledgeBase:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    entries = {}
    for e in raw["entries"]:
        entries[e["id"]] = KBEntry(
            id=e["id"],
            category=e["category"],
            question=e["question"],
            answer_text=e["answer_text"],
            preview=e.get("preview", ""),
            image_urls=e.get("image_urls", []),
            links=[Link(**link) for link in e.get("links", [])],
            ambiguous_with=e.get("ambiguous_with", []),
            disambiguation_hint=e.get("disambiguation_hint"),
        )

    if not entries:
        raise ValueError(
            f"loaded knowledge base from {path} but it has zero entries - "
            "run ingest/build_kb.py first"
        )

    return KnowledgeBase(
        entries=entries,
        generated_at=raw.get("generated_at", ""),
        source_file=raw.get("source_file", ""),
    )
