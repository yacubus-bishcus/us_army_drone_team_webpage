"""Stream Signal group messages and ingest URLs into the news feed.
USAGE: python -m scripts.signal_service --number +1XXXXXXXXXX --group-name "GROUP_NAME" --log-file news_log.log --signal-cli /path/to/signal-cli --max-minutes N --target-count 10

If ``--max-minutes`` is not provided the service defaults to a two minute
runtime when ``SANDBOX_DATA_MODE=true`` and three hours otherwise.
"""

from __future__ import annotations

import argparse, logging, os, sys
from pathlib import Path
from typing import Optional, Sequence

from flask import current_app

# Ensure auxiliary scripts don't trigger the local dev browser launcher.
os.environ.setdefault("RUN_LOCAL", "0")
# Avoid recursively spawning scheduler threads when create_app() is invoked here.
os.environ.setdefault("DISABLE_SIGNAL_SCHEDULER", "1")
from . import pull_signal_news
from . import signal_group_reader
from drone_team import create_app


_SANDBOX_RUNTIME_MINUTES = 2
_PRODUCTION_RUNTIME_MINUTES = 60 * 3


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
    target_count: int,
) -> int:
    """Stream Signal messages and ingest discovered URLs."""

    if not log_file:
        raise ValueError(
            "log_file is required so URLs can be parsed from the signal_group_reader output",
        )

    log_path = Path(log_file).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if target_count <= 0:
        raise ValueError("target_count must be a positive integer")

    added_by_value = _resolve_added_by(added_by, group_name)

    app = create_app()
    with app.app_context():
        sandbox_enabled = bool(current_app.config.get("SANDBOX_DATA_MODE"))
        default_limit = (
            _SANDBOX_RUNTIME_MINUTES if sandbox_enabled else _PRODUCTION_RUNTIME_MINUTES
        )
        runtime_limit = max_minutes if max_minutes is not None else default_limit

        if max_minutes is None:
            mode_label = "SANDBOX" if sandbox_enabled else "production"
            logging.info(
                "No max runtime provided; defaulting to %.0f minutes for %s mode",
                runtime_limit,
                mode_label,
            )

        state_path = pull_signal_news._resolve_state_path(current_app, None)
        last_ts = pull_signal_news._load_state_path(state_path)
        logging.info("Last processed timestamp: %s", last_ts)

        existing_urls = pull_signal_news._load_existing_urls(current_app)
        logging.info("Loaded %d existing URL(s) from feed", len(existing_urls))

        seen_this_run: set[str] = set()
        checkpoint_ts = last_ts or 0
        discovered: list[tuple[str, int]] = []
        total_ingested = 0

        def handle_message(payload: dict) -> bool:
            nonlocal checkpoint_ts, total_ingested

            timestamp = payload.get("timestamp") or 0

            if last_ts and timestamp <= last_ts:
                logging.debug(
                    "Skipping message at %s (<= checkpoint %s)",
                    timestamp,
                    last_ts,
                )
                return False

            text = payload.get("text") or ""
            urls = list(pull_signal_news._iter_urls(text))
            if not urls:
                checkpoint_ts = max(checkpoint_ts, timestamp)
                return False

            processed_in_message: set[str] = set()
            stop_requested = False
            message_failed = False
            for url in urls:
                if url in processed_in_message:
                    continue
                processed_in_message.add(url)

                if url in seen_this_run:
                    logging.debug("Already processed URL this run: %s", url)
                    continue

                if url in existing_urls:
                    logging.info("Skipping duplicate URL already in feed: %s", url)
                    continue

                if dry_run:
                    logging.info(
                        "[dry-run] Discovered new URL %s (%d/%d)",
                        url,
                        total_ingested + 1,
                        target_count,
                    )
                    discovered.append((url, timestamp))
                    total_ingested += 1
                    seen_this_run.add(url)
                else:
                    try:
                        pull_signal_news.news_svc.add_article_by_url(
                            current_app,
                            url,
                            added_by=added_by_value,
                        )
                    except Exception:
                        logging.exception("Failed to ingest URL %s", url)
                        # Allow future attempts if ingestion fails.
                        message_failed = True
                        continue

                    existing_urls.add(url)
                    discovered.append((url, timestamp))
                    total_ingested += 1
                    seen_this_run.add(url)
                    logging.info(
                        "Ingested URL %s (%d/%d)",
                        url,
                        total_ingested,
                        target_count,
                    )

                if total_ingested >= target_count:
                    logging.info(
                        "Target of %d new URL(s) reached; requesting shutdown.",
                        target_count,
                    )
                    stop_requested = True
                    break

            if dry_run or not message_failed:
                checkpoint_ts = max(checkpoint_ts, timestamp)
            else:
                logging.info(
                    "Deferring checkpoint update at %s due to ingestion failure(s)",
                    timestamp,
                )

            return stop_requested

        logging.info("Starting signal_group_reader for group '%s'", group_name)
        try:
            signal_group_reader.run(
                number=number,
                group_name=group_name,
                signal_cli=signal_cli,
                log_file=str(log_path),
                max_minutes=runtime_limit,
                on_message=handle_message,
            )
        except RuntimeError as exc:
            logging.error("signal_group_reader failed: %s", exc)
            return 1

        if discovered:
            pull_signal_news._print_urls_summary(discovered)

        if (
            not dry_run
            and state_path
            and checkpoint_ts
            and checkpoint_ts != last_ts
        ):
            pull_signal_news._save_state_path(state_path, checkpoint_ts)
            logging.info("Persisted newest timestamp %s", checkpoint_ts)

        if total_ingested >= target_count:
            logging.info(
                "Target met with %d new URL(s); shutting down.", total_ingested
            )
        else:
            logging.info(
                "Processed %d new URL(s); target of %d not reached before exit.",
                total_ingested,
                target_count,
            )

        logging.info("Discovered %d URL(s) this run", len(discovered))
        return 0


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
        help=(
            "Optional maximum runtime (in minutes) for signal_group_reader. "
            "Defaults to 2 minutes in SANDBOX_DATA_MODE and 180 minutes otherwise."
        ),
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
    parser.add_argument(
        "--target-count",
        type=int,
        default=10,
        help="Number of new URLs to ingest before shutting down (default: 10)",
    )

    args = parser.parse_args(argv)

    logging_kwargs = {
        "level": logging.INFO,
        "format": "%(asctime)s %(levelname)s %(message)s",
        "handlers": [logging.StreamHandler(sys.stdout)],
        "force": True,
    }
    logging.basicConfig(**logging_kwargs)

    return run(
        args.number,
        args.group_name,
        args.signal_cli,
        log_file=args.log_file,
        max_minutes=args.max_minutes,
        dry_run=args.dry_run,
        added_by=args.added_by,
        target_count=args.target_count,
    )


if __name__ == "__main__":
    sys.exit(main())
