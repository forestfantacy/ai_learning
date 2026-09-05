"""Rebuild data/knowledge_base.json (+ data/dedupe_report.json) from the
source FAQ xlsx.

Usage:
    python ingest/build_kb.py /path/to/【内】C端FAQ.xlsx

Run this every time the business team edits the source spreadsheet, skim the
regenerated dedupe_report.json for any newly-introduced ambiguous pairs, add
disambiguation_hints for them in data/overrides.yaml if needed, then commit
the regenerated knowledge_base.json (and image_summary_cache.json).

Needs ARK_API_KEY + ARK_VISION_MODEL in .env whenever the sheet has any entry
with an image not already covered by data/image_summary_cache.json - those
entries get a vision-model preview instead of a plain text truncation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest.dedupe import DedupePair, build_ambiguous_clusters, find_candidate_pairs
from ingest.html_to_text import parse_answer_html
from ingest.preview import text_preview, vision_preview
from llm.ark_client import build_client, get_vision_model

logger = logging.getLogger("mini-kb-robot.ingest")

VISION_CONCURRENCY = 5

SHEET_NAME = "黄金问答"

# Category-name variants confirmed to be the same category, produced by
# inconsistent data entry (not a business distinction).
CATEGORY_CANONICAL = {
    "库迪咖啡TOC/APP账户1": "库迪咖啡TOC/APP账户",
    "库迪咖啡TOC/合作相关": "库迪咖啡TOC/合作类",
    "库迪咖啡TOC/订单类": "库迪咖啡TOC/订单相关",
}

DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class KBEntry:
    id: str
    category: str
    question: str
    answer_text: str
    preview: str = ""
    image_urls: list[str] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    ambiguous_with: list[str] = field(default_factory=list)
    disambiguation_hint: str | None = None


def load_overrides() -> dict:
    path = DATA_DIR / "overrides.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


PREVIEW_CACHE_PATH = DATA_DIR / "image_summary_cache.json"


def load_preview_cache() -> dict:
    if not PREVIEW_CACHE_PATH.exists():
        return {}
    with open(PREVIEW_CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_preview_cache(cache: dict) -> None:
    with open(PREVIEW_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"wrote {PREVIEW_CACHE_PATH} ({len(cache)} cached image previews)")


async def apply_previews(entries: list[KBEntry]) -> None:
    """Text-only entries get a free, offline sentence-extraction preview.
    Image-bearing entries get an Ark vision-model summary (cached by
    entry id + image_urls, so an unrelated Excel edit doesn't re-spend
    vision calls on unchanged images) - this is what lets the tool index
    reflect what's actually shown in a screenshot, not just the caption text.
    """
    cache = load_preview_cache()
    needs_vision = [
        e for e in entries if e.image_urls and cache.get(e.id, {}).get("image_urls") != e.image_urls
    ]

    if needs_vision:
        # Fails loudly here (missing ARK_API_KEY / ARK_VISION_MODEL) rather
        # than silently falling back - a knowledge base built without a
        # preview for some entries is a correctness bug, not a degraded mode.
        client = build_client()
        model = get_vision_model()
        semaphore = asyncio.Semaphore(VISION_CONCURRENCY)

        async def _fill_one(entry: KBEntry) -> None:
            async with semaphore:
                try:
                    summary = await vision_preview(
                        client, model, entry.question, entry.answer_text, entry.image_urls
                    )
                except Exception:
                    logger.exception(
                        "vision_preview failed for %s (%r) - falling back to text_preview",
                        entry.id,
                        entry.question,
                    )
                    summary = text_preview(entry.answer_text)
            entry.preview = summary
            cache[entry.id] = {"image_urls": entry.image_urls, "preview": summary}

        await asyncio.gather(*(_fill_one(e) for e in needs_vision))
        print(f"generated {len(needs_vision)} new vision preview(s)")

    for entry in entries:
        if not entry.image_urls:
            entry.preview = text_preview(entry.answer_text)
        elif not entry.preview:
            cached = cache.get(entry.id)
            entry.preview = cached["preview"] if cached else text_preview(entry.answer_text)

    save_preview_cache(cache)


def read_rows(xlsx_path: str) -> list[tuple[str, str, str, str]]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[SHEET_NAME]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        kid, category, question, answer_html = row[0], row[1], row[2], row[3]
        if kid is None or question is None:
            continue
        # Knowledge IDs are opaque strings (some have leading zeros) - never int().
        rows.append((str(kid).strip(), str(category or "").strip(), str(question).strip(), answer_html or ""))
    return rows


def build_entries(rows: list[tuple[str, str, str, str]], overrides: dict) -> list[KBEntry]:
    category_fixes = overrides.get("category_fixes", {})
    entries = []
    for kid, category, question, answer_html in rows:
        category = CATEGORY_CANONICAL.get(category, category)
        category = category_fixes.get(kid, category)
        parsed = parse_answer_html(answer_html)
        entries.append(
            KBEntry(
                id=kid,
                category=category,
                question=question,
                answer_text=parsed.text,
                image_urls=parsed.image_urls,
                links=[asdict(link) for link in parsed.links],
            )
        )
    return entries


def apply_ambiguity(entries: list[KBEntry], overrides: dict) -> list[DedupePair]:
    pairs = find_candidate_pairs(entries)
    clusters = build_ambiguous_clusters(pairs)

    for id_, others in (overrides.get("manual_ambiguous_edges") or {}).items():
        clusters.setdefault(id_, set()).update(others)
        for other in others:
            clusters.setdefault(other, set()).add(id_)

    for id_a, id_b in overrides.get("manual_ambiguous_removals") or []:
        clusters.get(id_a, set()).discard(id_b)
        clusters.get(id_b, set()).discard(id_a)

    hints = overrides.get("disambiguation_hints", {})
    by_id = {e.id: e for e in entries}
    for id_, others in clusters.items():
        entry = by_id.get(id_)
        if entry is None:
            continue
        entry.ambiguous_with = sorted(o for o in others if o)
        if entry.ambiguous_with:
            entry.disambiguation_hint = hints.get(id_)

    return pairs


def write_knowledge_base(entries: list[KBEntry], source_file: str) -> None:
    entries_sorted = sorted(entries, key=lambda e: e.id)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source_file,
        "entry_count": len(entries_sorted),
        "entries": [asdict(e) for e in entries_sorted],
    }
    path = DATA_DIR / "knowledge_base.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wrote {path} ({len(entries_sorted)} entries)")


def write_dedupe_report(pairs: list[DedupePair]) -> None:
    high_risk = [p for p in pairs if p.answers_differ]
    likely_duplicate = [p for p in pairs if not p.answers_differ]
    out = {
        "high_risk_ambiguous_pairs": [asdict(p) for p in high_risk],
        "likely_true_duplicates": [asdict(p) for p in likely_duplicate],
    }
    path = DATA_DIR / "dedupe_report.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(
        f"wrote {path} ({len(high_risk)} high-risk pairs, "
        f"{len(likely_duplicate)} likely-duplicate pairs) - review before committing"
    )


async def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    xlsx_path = sys.argv[1]

    load_dotenv()

    overrides = load_overrides()
    rows = read_rows(xlsx_path)
    entries = build_entries(rows, overrides)
    pairs = apply_ambiguity(entries, overrides)
    await apply_previews(entries)

    write_knowledge_base(entries, Path(xlsx_path).name)
    write_dedupe_report(pairs)


if __name__ == "__main__":
    asyncio.run(main())
