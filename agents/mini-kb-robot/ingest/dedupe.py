"""Flag pairs of FAQ questions that look similar enough to risk being confused.

A pair is HIGH-RISK (ambiguous) when the questions are textually similar but
the answers actually differ - that's the failure mode a closed-enum lookup
tool needs an explicit warning for, since the model could otherwise guess the
wrong one. A pair with similar questions AND similar answers is a likely true
duplicate, logged separately for a human to consider merging - it's not a
disambiguation risk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PUNCT_RE = re.compile(r"[【】()（）\-·:：,，。！？!?、\s]")

SIMILARITY_THRESHOLD = 0.35


def _normalize(question: str) -> str:
    return _PUNCT_RE.sub("", question)


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def jaccard(a: str, b: str) -> float:
    set_a, set_b = _bigrams(_normalize(a)), _bigrams(_normalize(b))
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _answers_differ(a: str, b: str) -> bool:
    norm_a = re.sub(r"\s+", "", a)
    norm_b = re.sub(r"\s+", "", b)
    if norm_a == norm_b:
        return False
    return jaccard(norm_a, norm_b) < 0.6


@dataclass
class DedupePair:
    id_a: str
    id_b: str
    question_a: str
    question_b: str
    question_similarity: float
    answers_differ: bool


def find_candidate_pairs(entries: list) -> list[DedupePair]:
    """entries: list of objects with .id, .question, .answer_text."""
    pairs: list[DedupePair] = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            e_a, e_b = entries[i], entries[j]
            sim = jaccard(e_a.question, e_b.question)
            if sim >= SIMILARITY_THRESHOLD:
                pairs.append(
                    DedupePair(
                        id_a=e_a.id,
                        id_b=e_b.id,
                        question_a=e_a.question,
                        question_b=e_b.question,
                        question_similarity=round(sim, 3),
                        answers_differ=_answers_differ(e_a.answer_text, e_b.answer_text),
                    )
                )
    return pairs


def build_ambiguous_clusters(pairs: list[DedupePair]) -> dict[str, set[str]]:
    """id -> set of other ids it's ambiguous with (answers_differ pairs only)."""
    clusters: dict[str, set[str]] = {}
    for pair in pairs:
        if not pair.answers_differ:
            continue
        clusters.setdefault(pair.id_a, set()).add(pair.id_b)
        clusters.setdefault(pair.id_b, set()).add(pair.id_a)
    return clusters
