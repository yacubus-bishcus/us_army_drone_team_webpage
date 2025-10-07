"""Stream Signal group messages and ingest URLs into the news feed."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence
from . import pull_signal_news
from . import signal_group_reader


def _resolve_added_by(value: Optional[str], fallback: Optional[str]) -> str:
    for candidate in (value, fallback, pull_signal_news.DEFAULT_ADDED_BY):
        if candidate:
            cleaned = candidate.strip()
            if cleaned:
                return cleaned
    return pull_signal_news.DEFAULT_ADDED_BY


def run(
    number: str,
    group_name: str,
    signal_cli: str,
    *,
    log_file: Optional[str],
    max_minutes: Optional[float],
    dry_run: bool,
    added_by: Optional[str],
) -> int:
    """Stream Signal messages and ingest discovered URLs."""

    if not log_file:
        raise ValueError(
            "log_file is required so URLs can be parsed from the signal_group_reader output",
        )

    log_path = Path(log_file).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.info("Starting signal_group_reader for group '%s'", group_name)
    signal_group_reader.run(
        number=number,
        group_name=group_name,
        signal_cli=signal_cli,
        log_file=str(log_path),
        max_minutes=max_minutes,
    )

    added_by_value = _resolve_added_by(added_by, group_name)
    logging.info("Ingesting URLs discovered in %s", log_path)
    return pull_signal_news.ingest_urls_from_log_file(
        str(log_path),
        group_name=group_name,
        added_by=added_by_value,
        dry_run=dry_run,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stream Signal messages from a group and ingest discovered URLs into the news feed",
    )
    parser.add_argument("--number", "-u", required=True, help="Signal phone number (E.164 format)")
    parser.add_argument("--group-name", "-g", required=True, help="Signal group display name")
    parser.add_argument(
        "--signal-cli",
        default="signal-cli",
        help="Path to the signal-cli binary (defaults to 'signal-cli' in PATH)",
    )
    parser.add_argument(
        "--log-file",
        required=True,
        help="Path where signal_group_reader should write logs for URL ingestion",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        help="Optional maximum runtime (in minutes) for signal_group_reader",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print discovered URLs without modifying the CSV store",
    )
    parser.add_argument(
        "--added-by",
        dest="added_by",
        help="Override the added_by metadata stored with new URLs",
    )

    args = parser.parse_args(argv)

    logging_kwargs = {"level": logging.INFO, "format": "%(asctime)s %(levelname)s %(message)s"}
    logging.basicConfig(**logging_kwargs)

    return run(
        args.number,
        args.group_name,
        args.signal_cli,
        log_file=args.log_file,
        max_minutes=args.max_minutes,
        dry_run=args.dry_run,
        added_by=args.added_by,
    )


if __name__ == "__main__":
    sys.exit(main())
