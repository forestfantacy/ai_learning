#!/usr/bin/env python3
"""Check a chunk plan against the source document for dropped/lost content.

Usage:
    python3 verify_plan_completeness.py <elements.json> <plan.json>

This is a mechanical, non-judgment check: it never evaluates whether chunk
boundaries are "good" — only whether content that existed in the source
(especially exact table-cell values, which are the highest-risk thing to
lose or scramble) is still present somewhere in the plan's output.

elements.json is the ground truth (inspect_docx.py's output for a DOCX
source, or a hand-written transcript in the same schema for a PDF source).

plan.json can be either shape:
  - path A (DOCX, incremental edit): {"insert_marker_after": [...],
    "flatten_tables": {"<table index>": ["paragraph text", ...], ...},
    "label_prefix": {"<paragraph index>": "prefix text"}}
    Only flattened tables are checked for content coverage (untouched
    paragraphs/tables cannot have been altered by construction);
    label_prefix entries are checked separately (see check_label_prefix)
    for structural validity — right element type, right position, and
    quoting text that actually exists earlier in the document.
  - path B (PDF, full rebuild): {"chunk_groups": [{"elements": [...]}]}
    Every table cell and every paragraph from elements.json is checked
    against the full rebuilt output, since anything could have been
    dropped when the plan was authored from scratch.

Exit code is 0 iff there are zero FAIL entries (WARN entries do not affect
the exit code, but every WARN must still be manually reviewed by the
caller before proceeding).
"""

import json
import re
import sys

COVERAGE_FAIL_THRESHOLD = 0.35  # below this, treat as an outright drop (hard FAIL)
COVERAGE_WARN_THRESHOLD = 0.6  # below this (but above FAIL), possible reword (WARN)
MIN_TEXT_LEN_FOR_COVERAGE_CHECK = 4  # chars; shorter text is skipped


def normalize(text):
    if text is None:
        return ""
    return re.sub(r"\s+", "", text)


def char_bigrams(text):
    if len(text) < 2:
        return [text] if text else []
    return [text[i : i + 2] for i in range(len(text) - 1)]


def build_bigram_document_frequency(paragraph_texts):
    """Count, for each bigram, in how many distinct source paragraphs it
    appears. Used to down-weight boilerplate shared across sibling
    paragraphs (e.g. templated "label: value" sentences produced when a
    table is flattened) so it can't mask one sibling being dropped
    entirely — a bigram that recurs across many paragraphs is weak
    evidence that any *specific* one of them survived."""
    df = {}
    for text in paragraph_texts:
        for bg in set(char_bigrams(text)):
            df[bg] = df.get(bg, 0) + 1
    return df


def weighted_coverage_ratio(source_text, output_pool_text, bigram_df):
    bigrams = char_bigrams(source_text)
    if not bigrams:
        return 1.0
    total_weight = 0.0
    hit_weight = 0.0
    for bg in bigrams:
        weight = 1.0 / bigram_df.get(bg, 1)
        total_weight += weight
        if bg in output_pool_text:
            hit_weight += weight
    if total_weight == 0:
        return 1.0
    return hit_weight / total_weight


def load_json(path, label):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"error: could not read {label} '{path}': {e}", file=sys.stderr)
        sys.exit(1)


def collect_plan_output_pool_a(plan, elements_by_index):
    """Path A: everything except flattened tables passes through unchanged."""
    flatten_tables = plan.get("flatten_tables", {})
    pieces = []
    for el in elements_by_index.values():
        idx_str = str(el["index"])
        if el["type"] == "table":
            if idx_str in flatten_tables:
                pieces.extend(flatten_tables[idx_str])
            else:
                for row in el["grid"]:
                    pieces.extend(row)
        else:
            pieces.append(el.get("text", "") or "")
    return normalize("".join(pieces))


def collect_plan_output_pool_b(plan):
    pieces = []
    for group in plan.get("chunk_groups", []):
        for el in group.get("elements", []):
            if el.get("type") == "table":
                for row in el.get("rows", []):
                    pieces.extend(row)
            else:
                pieces.append(el.get("text", "") or "")
    return normalize("".join(pieces))


def check_table_cells_exact(elements, output_pool, findings, only_indices=None):
    for el in elements:
        if el["type"] != "table":
            continue
        if only_indices is not None and el["index"] not in only_indices:
            continue
        for r, row in enumerate(el["grid"]):
            for c, cell in enumerate(row):
                cell_norm = normalize(cell)
                if not cell_norm:
                    continue
                if cell_norm not in output_pool:
                    findings.append(
                        {
                            "level": "FAIL",
                            "element_index": el["index"],
                            "detail": f"table cell (row {r}, col {c}) not found in plan output: {cell!r}",
                        }
                    )


def check_label_prefix(elements_by_index, plan, findings):
    """Path A only: mechanically validate label_prefix entries. This never
    judges whether a chunk *needs* a label (that's Claude's call) — only
    that a declared label targets a real paragraph at a real chunk start,
    with non-trivial content, and quotes text that actually exists earlier
    in the source document rather than inventing a heading from scratch."""
    label_prefix_raw = plan.get("label_prefix", {})
    marker_indices = set(plan.get("insert_marker_after", []))

    for idx_str, prefix in label_prefix_raw.items():
        try:
            idx = int(idx_str)
        except ValueError:
            findings.append({
                "level": "FAIL", "element_index": idx_str,
                "detail": f"label_prefix key {idx_str!r} is not an integer",
            })
            continue

        el = elements_by_index.get(idx)
        if el is None:
            findings.append({
                "level": "FAIL", "element_index": idx,
                "detail": f"label_prefix index {idx} not found in source elements",
            })
            continue
        if el["type"] != "paragraph":
            findings.append({
                "level": "FAIL", "element_index": idx,
                "detail": f"label_prefix index {idx} does not refer to a paragraph element",
            })
            continue

        original_text = el.get("text", "") or ""
        if not original_text.strip():
            findings.append({
                "level": "FAIL", "element_index": idx,
                "detail": f"label_prefix index {idx} targets an empty paragraph",
            })
            continue
        if not isinstance(prefix, str) or not prefix.strip():
            findings.append({
                "level": "FAIL", "element_index": idx,
                "detail": f"label_prefix[{idx}] prefix is empty",
            })
            continue

        is_chunk_start = idx == 0 or (idx - 1) in marker_indices
        if not is_chunk_start:
            findings.append({
                "level": "FAIL", "element_index": idx,
                "detail": (
                    f"label_prefix index {idx} is not the first paragraph of a chunk "
                    "(expected index 0 or right after an insert_marker_after index)"
                ),
            })
            continue

        if normalize(original_text).startswith(normalize(prefix)):
            findings.append({
                "level": "WARN", "element_index": idx,
                "detail": (
                    f"label_prefix[{idx}] prefix {prefix!r} may duplicate text the paragraph "
                    f"already starts with: {original_text[:40]!r}"
                ),
            })

        # the prefix (minus its trailing separator, if any) must quote text
        # that actually appears earlier in the document — labels restate an
        # existing heading, they don't invent one.
        quoted = prefix.strip().rstrip("·").strip()
        quoted_norm = normalize(quoted)
        if quoted_norm:
            found_earlier = any(
                other_idx < idx
                and other_el["type"] == "paragraph"
                and quoted_norm in normalize(other_el.get("text", "") or "")
                for other_idx, other_el in elements_by_index.items()
            )
            if not found_earlier:
                findings.append({
                    "level": "FAIL", "element_index": idx,
                    "detail": (
                        f"label_prefix[{idx}] text {quoted!r} is not found verbatim in any "
                        "earlier paragraph — labels must quote an existing heading, not invent one"
                    ),
                })


def check_paragraphs_coverage(elements, output_pool, findings):
    paragraph_texts_norm = [
        normalize(el.get("text", ""))
        for el in elements
        if el["type"] == "paragraph" and len(normalize(el.get("text", ""))) >= MIN_TEXT_LEN_FOR_COVERAGE_CHECK
    ]
    bigram_df = build_bigram_document_frequency(paragraph_texts_norm)

    for el in elements:
        if el["type"] != "paragraph":
            continue
        text_norm = normalize(el.get("text", ""))
        if len(text_norm) < MIN_TEXT_LEN_FOR_COVERAGE_CHECK:
            continue
        ratio = weighted_coverage_ratio(text_norm, output_pool, bigram_df)
        if ratio < COVERAGE_FAIL_THRESHOLD:
            findings.append(
                {
                    "level": "FAIL",
                    "element_index": el["index"],
                    "detail": (
                        f"paragraph text only {ratio:.0%} covered in plan output "
                        f"(below hard floor {COVERAGE_FAIL_THRESHOLD:.0%}) — almost certainly dropped: "
                        f"{el.get('text', '')[:80]!r}"
                    ),
                }
            )
        elif ratio < COVERAGE_WARN_THRESHOLD:
            findings.append(
                {
                    "level": "WARN",
                    "element_index": el["index"],
                    "detail": (
                        f"paragraph text only {ratio:.0%} covered in plan output "
                        f"(threshold {COVERAGE_WARN_THRESHOLD:.0%}), possibly reworded — verify: "
                        f"{el.get('text', '')[:80]!r}"
                    ),
                }
            )


def main():
    if len(sys.argv) != 3:
        print("usage: verify_plan_completeness.py <elements.json> <plan.json>", file=sys.stderr)
        sys.exit(1)

    elements_data = load_json(sys.argv[1], "elements.json")
    plan = load_json(sys.argv[2], "plan.json")

    elements = elements_data.get("elements", [])
    elements_by_index = {el["index"]: el for el in elements}

    findings = []

    is_path_a = "flatten_tables" in plan or "insert_marker_after" in plan
    is_path_b = "chunk_groups" in plan

    if is_path_a and is_path_b:
        print("error: plan.json matches both path A and path B shapes; ambiguous", file=sys.stderr)
        sys.exit(1)
    if not is_path_a and not is_path_b:
        print(
            "error: plan.json has neither 'flatten_tables'/'insert_marker_after' (path A) "
            "nor 'chunk_groups' (path B)",
            file=sys.stderr,
        )
        sys.exit(1)

    if is_path_a:
        output_pool = collect_plan_output_pool_a(plan, elements_by_index)
        flattened_indices = {int(k) for k in plan.get("flatten_tables", {}).keys()}
        check_table_cells_exact(elements, output_pool, findings, only_indices=flattened_indices)
        check_label_prefix(elements_by_index, plan, findings)
        # Path A never rewrites untouched paragraphs, so no coverage check needed.
    else:
        output_pool = collect_plan_output_pool_b(plan)
        check_table_cells_exact(elements, output_pool, findings, only_indices=None)
        check_paragraphs_coverage(elements, output_pool, findings)

    fails = [f for f in findings if f["level"] == "FAIL"]
    warns = [f for f in findings if f["level"] == "WARN"]

    report = {
        "path": "A" if is_path_a else "B",
        "total_findings": len(findings),
        "fail_count": len(fails),
        "warn_count": len(warns),
        "findings": findings,
        "result": "FAIL" if fails else ("WARN" if warns else "PASS"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
