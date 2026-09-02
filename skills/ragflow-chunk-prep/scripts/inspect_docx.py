#!/usr/bin/env python3
"""Dump a .docx body, in document order, as JSON.

Usage:
    python3 inspect_docx.py <input.docx>

Prints {"total_elements": N, "elements": [...]} to stdout. Each element is
either a paragraph ({"index", "type": "paragraph", "style", "text"}, full
text, not truncated) or a table ({"index", "type": "table", "n_rows",
"n_cols", "grid": [[cell text, ...], ...]}, full grid, not a preview).

This is the "what does the source document actually contain" ground truth
used both for planning chunk boundaries and for the completeness check in
verify_plan_completeness.py.
"""

import json
import sys


def main():
    if len(sys.argv) != 2:
        print("usage: inspect_docx.py <input.docx>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]

    try:
        from docx import Document
        from docx.table import Table
    except ImportError:
        print(
            "error: python-docx is not installed (pip install python-docx)",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        doc = Document(input_path)
    except Exception as e:
        print(f"error: could not open '{input_path}': {e}", file=sys.stderr)
        sys.exit(1)

    elements = []
    for index, item in enumerate(doc.iter_inner_content()):
        if isinstance(item, Table):
            grid = [[cell.text for cell in row.cells] for row in item.rows]
            n_rows = len(item.rows)
            n_cols = len(item.columns)

            has_nested = any(
                cell.tables for row in item.rows for cell in row.cells
            )
            if has_nested:
                print(
                    f"warning: table at index {index} contains a nested "
                    "table; nested content is not represented in 'grid'",
                    file=sys.stderr,
                )

            elements.append(
                {
                    "index": index,
                    "type": "table",
                    "n_rows": n_rows,
                    "n_cols": n_cols,
                    "grid": grid,
                }
            )
        else:
            style_name = None
            try:
                style_name = item.style.name if item.style else None
            except Exception:
                style_name = None
            elements.append(
                {
                    "index": index,
                    "type": "paragraph",
                    "style": style_name,
                    "text": item.text,
                }
            )

    result = {"total_elements": len(elements), "elements": elements}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
