"""Generate Word documents for applicants based on callsigns.

This script reads a list of callsigns from a plain text file, finds the
corresponding applicant rows in an Excel spreadsheet, and writes each row's
information into an individual Word document. The resulting files are saved
using the pattern ``<username>_<name>_<callsign>.doc``.

Example usage::

    python -m scripts.generate_applicant_docs \
        --callsigns-file callsigns.txt \
        --excel-file applicants.xlsx \
        --output-dir output_docs

The Excel sheet is expected to contain at least the columns ``username``,
``name`` and ``callsign``. Their names can be customized with optional command
line arguments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd
from docx import Document


def _normalise_columns(columns: Iterable[str]) -> dict[str, str]:
    """Return a mapping of normalised column names to their originals."""

    normalised: dict[str, str] = {}
    for column in columns:
        key = str(column).strip().lower()
        if key in normalised:
            continue
        normalised[key] = column
    return normalised


def _sanitise_filename_component(component: str) -> str:
    """Return a filesystem-friendly version of ``component``."""

    safe = "".join(ch if ch.isalnum() else "_" for ch in component.strip())
    return "_".join(filter(None, safe.split("_"))) or "value"


def _load_callsigns(path: Path) -> list[str]:
    """Load and normalise callsigns from ``path``."""

    callsigns: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = line.strip()
            if not value:
                continue
            callsigns.append(value)
    return callsigns


def _create_document(row: pd.Series, doc_path: Path) -> None:
    """Write a Word document containing the values from ``row``."""

    document = Document()
    document.add_heading(str(row.get("name", "Applicant")), level=1)
    table = document.add_table(rows=0, cols=2)
    for column, value in row.items():
        cells = table.add_row().cells
        cells[0].text = str(column)
        cells[1].text = "" if pd.isna(value) else str(value)
    document.save(doc_path)


def _select_row(frame: pd.DataFrame, column: str, callsign: str) -> pd.Series | None:
    """Return the first row in ``frame`` whose ``column`` matches ``callsign``."""

    matches = frame[column].astype(str).str.casefold() == callsign.casefold()
    matched_rows = frame[matches]
    if matched_rows.empty:
        return None
    return matched_rows.iloc[0]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--callsigns-file",
        required=True,
        type=Path,
        help="Text file containing one callsign per line.",
    )
    parser.add_argument(
        "--excel-file",
        required=True,
        type=Path,
        help="Excel spreadsheet containing applicant information.",
    )
    parser.add_argument(
        "--sheet-name",
        default=0,
        help="Name or index of the sheet to read (defaults to the first sheet).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory where generated Word documents will be saved.",
    )
    parser.add_argument(
        "--callsign-column",
        default="callsign",
        help="Column name containing callsigns.",
    )
    parser.add_argument(
        "--username-column",
        default="username",
        help="Column name containing usernames.",
    )
    parser.add_argument(
        "--name-column",
        default="name",
        help="Column name containing applicant names.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if not args.callsigns_file.exists():
        raise SystemExit(f"Calls sign file not found: {args.callsigns_file}")
    if not args.excel_file.exists():
        raise SystemExit(f"Excel file not found: {args.excel_file}")

    callsigns = _load_callsigns(args.callsigns_file)
    if not callsigns:
        raise SystemExit("No callsigns provided.")

    frame = pd.read_excel(args.excel_file, sheet_name=args.sheet_name)
    normalised_columns = _normalise_columns(frame.columns)

    def resolve(column_name: str) -> str:
        key = column_name.strip().lower()
        try:
            return normalised_columns[key]
        except KeyError as exc:
            available = ", ".join(sorted(normalised_columns))
            raise SystemExit(
                f"Column '{column_name}' was not found. Available columns: {available}"
            ) from exc

    callsign_column = resolve(args.callsign_column)
    username_column = resolve(args.username_column)
    name_column = resolve(args.name_column)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for callsign in callsigns:
        row = _select_row(frame, callsign_column, callsign)
        if row is None:
            print(f"No applicant found for callsign '{callsign}'.", file=sys.stderr)
            continue

        username = str(row[username_column]) if not pd.isna(row[username_column]) else "user"
        name = str(row[name_column]) if not pd.isna(row[name_column]) else "name"

        filename = "_".join(
            [
                _sanitise_filename_component(username),
                _sanitise_filename_component(name),
                _sanitise_filename_component(callsign),
            ]
        )
        doc_path = args.output_dir / f"{filename}.doc"

        print(f"Creating {doc_path}...")
        _create_document(row, doc_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

