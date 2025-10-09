from __future__ import annotations

import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

from dotenv import load_dotenv


def _open_browser_once():
    webbrowser.open_new("http://127.0.0.1:5000")


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from drone_team import create_app  # import after .env is loaded


_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _run_signal_worker(argv: list[str]) -> int:
    """Run the Signal ingestion worker using repository environment defaults."""

    parser = argparse.ArgumentParser(
        prog="python run.py",
        description=(
            "Launch the Signal ingestion worker using environment variables for "
            "the Signal credentials. Provide the log file path as the first "
            "positional argument."
        ),
    )
    parser.add_argument(
        "log_file",
        help="Path where Signal group activity should be mirrored (also streamed to stdout).",
    )
    parser.add_argument(
        "--number",
        "-u",
        default=os.getenv("SIGNAL_PHONE_NUMBER"),
        help=(
            "Signal account phone number (defaults to SIGNAL_PHONE_NUMBER from the environment)."
        ),
    )
    parser.add_argument(
        "--group-name",
        "-g",
        default=os.getenv("SIGNAL_GROUP_NAME"),
        help="Signal group display name (defaults to SIGNAL_GROUP_NAME).",
    )
    parser.add_argument(
        "--signal-cli",
        default=os.getenv("SIGNAL_CLI_BIN", "signal-cli"),
        help=(
            "Path to the signal-cli binary (defaults to SIGNAL_CLI_BIN or 'signal-cli' in PATH)."
        ),
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=_env_float("SIGNAL_MAX_MINUTES"),
        help=(
            "Optional runtime limit in minutes. Defaults to SIGNAL_MAX_MINUTES when set."
        ),
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=_env_int("SIGNAL_TARGET_COUNT", 10),
        help="Number of URLs to ingest before stopping (defaults to SIGNAL_TARGET_COUNT or 10).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=_env_bool("SIGNAL_DRY_RUN"),
        help="Print discovered URLs without modifying the CSV store (or set SIGNAL_DRY_RUN=1).",
    )
    parser.add_argument(
        "--added-by",
        default=os.getenv("SIGNAL_ADDED_BY"),
        help="Override the added_by metadata for ingested URLs (defaults to SIGNAL_ADDED_BY).",
    )

    args = parser.parse_args(argv)

    if not args.number:
        parser.error(
            "Signal phone number is required. Set SIGNAL_PHONE_NUMBER or pass --number explicitly."
        )

    if not args.group_name:
        parser.error(
            "Signal group name is required. Set SIGNAL_GROUP_NAME or pass --group-name explicitly."
        )

    logging.basicConfig(
        level=logging.INFO,
        format=_LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    from scripts import signal_service

    return signal_service.run(
        args.number,
        args.group_name,
        args.signal_cli,
        log_file=args.log_file,
        max_minutes=args.max_minutes,
        dry_run=args.dry_run,
        added_by=args.added_by,
        target_count=args.target_count,
    )


def _maybe_open_browser():
    if os.getenv("RUN_LOCAL", "1") == "1" and not os.getenv("GUNICORN_CMD_ARGS"):
        Timer(1, _open_browser_once).start()


def build_app():
    """Return a Flask application instance (for ``flask --app run:build_app``)."""

    return create_app()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        return _run_signal_worker(args)

    flask_app = create_app()
    _maybe_open_browser()
    flask_app.run(debug=True, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
