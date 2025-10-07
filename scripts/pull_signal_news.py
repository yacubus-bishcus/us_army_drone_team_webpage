"""Scheduled ingestion of Signal URLs into the UAS news feed.

This script is designed to be executed by Render Cron (or any scheduler).
It pulls recent Signal group chat messages using the `signal-cli` binary and
stores any URLs it finds into the existing CSV-backed news feed via the
`news_svc.add_article_by_url` helper.

Environment variables:
    SIGNAL_CLI_BIN        Path to the signal-cli binary (default: ``signal-cli``)
    SIGNAL_PHONE_NUMBER   Signal phone number (required)
    SIGNAL_GROUP_ID       Group identifier; if omitted all chats for the account
                          are scanned. Strongly recommended for multi-chat bots.
    SIGNAL_RECEIVE_LIMIT  Optional maximum number of messages to fetch per run
                          (defaults to 200).
    SIGNAL_ADDED_BY       The ``added_by`` value stored in the CSV (default:
                          ``signal_bot``)
    SIGNAL_SENDER         Optional filter for a specific message sender (for
                          example a "note to self" conversation). The value
                          should match the Signal E.164 phone number, e.g.
                          ``+15555555555``.

The script keeps track of the last processed message timestamp inside the
Flask ``DATA_DIR`` (``instance/data`` by default) to ensure idempotent runs.
The script can be ran independent of flask using the --dry-run and --state-file flags
Ex: python -m scripts.pull_signal_news --dry-run --state-file=/tmp/signal-state.json

Pass ``--log-file=/path/to/log`` to duplicate console output to a persistent log.
Pass ``--message-log=/path/to/messages.jsonl`` to dump fetched Signal messages as JSON lines.
Pass ``--since=<iso-or-millis>`` to override the checkpoint and reprocess older
history, and ``--sender=<phone>`` to restrict ingestion to a specific
conversation (for example "Note to Self").
"""
from __future__ import annotations

import argparse, json, logging, os, re, subprocess, sys
from dataclasses import dataclass, asdict 
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from flask import current_app

from drone_team import create_app
from drone_team.services import news as news_svc

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
STATE_FILENAME = "signal_ingest_state.json"
DEFAULT_ADDED_BY = "signal_bot"


@dataclass
class SignalMessage:
    """Subset of Signal message fields we care about."""

    timestamp: int  # milliseconds since epoch (Signal convention)
    text: str
    sender: Optional[str]
    group_id: Optional[str]


def _data_dir(app) -> Path:
    base = Path(app.config.get("DATA_DIR", app.instance_path)) / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve_state_path(app, override: Optional[str]) -> Path:
    if override:
        path = Path(override).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    if app is None:
        raise ValueError("App instance required when no state file override is provided")
    return _data_dir(app) / STATE_FILENAME


def _load_state_path(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.warning("State file %s is corrupt; ignoring", path)
        return None
    return data.get("last_timestamp")


def _save_state_path(path: Path, timestamp: int) -> None:
    payload = {"last_timestamp": timestamp, "saved_at": datetime.utcnow().isoformat()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_since_argument(value: str) -> int:
    value = (value or "").strip()
    if not value:
        raise argparse.ArgumentTypeError("--since requires a non-empty value")

    if value.isdigit():
        return int(value)

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--since must be milliseconds since epoch or an ISO 8601 datetime"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)

    return int(parsed.timestamp() * 1000)


def _parse_signal_cli_output(
    raw: str,
    target_group: Optional[str],
    target_sender: Optional[str],
) -> List[SignalMessage]:
    messages: List[SignalMessage] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logging.debug("Skipping non-JSON line from signal-cli: %s", line)
            continue

        envelope = payload.get("envelope") or {}
        msg = envelope.get("dataMessage") or {}
        if not msg:
            continue

        group_info = msg.get("groupInfo") or {}
        group_id = group_info.get("groupId")
        if target_group and group_id != target_group:
            continue

        sender = envelope.get("source")
        if target_sender and sender != target_sender:
            continue

        text = msg.get("message") or ""
        if not text:
            continue

        messages.append(
            SignalMessage(
                timestamp=envelope.get("timestamp") or 0,
                text=text,
                sender=sender,
                group_id=group_id,
            )
        )
    return messages


@lru_cache(maxsize=1)
def _signal_cli_supports_group_flag(binary: str) -> bool:
    """Return True if `signal-cli receive` advertises a `--group` or `-g` flag."""
    help_cmd = [binary, "receive", "--help"]
    try:
        proc = subprocess.run(help_cmd, check=True, capture_output=True, text=True)
        help_text = (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        raise
    except PermissionError:
        raise
    except subprocess.CalledProcessError as exc:
        # Some tools print usage to stdout/stderr with non-zero exit; still inspect it.
        help_text = (exc.stdout or "") + (exc.stderr or "")
        logging.debug(
            "Failed to detect group flag (exit code %s): %s",
            exc.returncode, help_text
        )

    # Match either '--group' or '-g' as standalone options (e.g., "-g, --group")
    # Start-of-line or whitespace before, and a word boundary after.
    pattern = r'(?m)(^|\s)(?:--group\b|-g\b)'
    return re.search(pattern, help_text) is not None


def _build_signal_cli_cmd(
    binary: str,
    phone_number: str,
    *,
    since_timestamp: Optional[int] = None,
    receive_limit: Optional[int] = None,
) -> Sequence[str]:
    cmd = [binary, "--output=json", "--username", phone_number, "receive"]
    if receive_limit:
        cmd.extend(["--max-messages", str(receive_limit)])
    return cmd


def _fetch_signal_messages(
    *,
    binary: str,
    phone_number: str,
    group_id: Optional[str],
    sender: Optional[str],
    since_timestamp: Optional[int],
    receive_limit: Optional[int],
    ignore_cli_support_flag: Optional[bool],
) -> List[SignalMessage]:
    cmd = list(
        _build_signal_cli_cmd(
            binary,
            phone_number,
            since_timestamp=since_timestamp,
            receive_limit=receive_limit,
        )
    )

    if group_id:
        # `receive --group <id>` restricts output to a single group.
        if ignore_cli_support_flag or _signal_cli_supports_group_flag(binary):
            cmd.extend(["-g", group_id])
            logging.info("running receive -g <id> restricting output to a single group.")
        
        else:
            # signal-cli does not support --group or -g and cli_support_flag not ignored 
            logging.info(
                "signal-cli receive on this host does not support --group or -g; fetching all chats and filtering client-side"
            )
    else:
        # no group id fetching all chats and filtering client-side 
        logging.info("No group ID. Fetching all chats and filtering client-side")

    logging.info("Running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        logging.error("signal-cli binary not found at %s", binary)
        raise
    except PermissionError as exc:
        logging.error(
            "signal-cli binary at %s is not executable (%s). Adjust permissions (e.g. 'sudo chmod +x' or 'sudo chown' on the"
            " installation directory) or point SIGNAL_CLI_BIN/--signal-cli to a user-owned install.",
            binary,
            exc,
        )
        raise
    except subprocess.CalledProcessError as exc:
        logging.error("signal-cli failed: %s", exc.stderr or exc.stdout)
        raise

    messages = _parse_signal_cli_output(proc.stdout, group_id, sender)
    logging.info("Fetched %d candidate messages", len(messages))
    logging.info(f"Messages: {messages}")
    return messages

def _iter_urls(text: str) -> Iterable[str]:
    for match in URL_RE.finditer(text):
        # Strip trailing punctuation that commonly appears in chat messages.
        url = match.group(0).rstrip(".,);!?")
        yield url


def _load_existing_urls(app) -> Set[str]:
    existing = {row.get("url") for row in news_svc.list_articles(app)}
    return {url for url in existing if url}


def _print_urls_summary(urls_added: Sequence[Tuple[str, int]]) -> None:
    if not urls_added:
        logging.info("No URLs discovered in recent Signal messages")
        return

    logging.info("Discovered %d URL(s)", len(urls_added))
    for url, timestamp in urls_added:
        ts = datetime.fromtimestamp(timestamp / 1000.0)
        logging.info("%s — %s", ts.isoformat(), url)

def _write_message_log(messages: Sequence[SignalMessage], path: Path) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as fh:
        for msg in messages:
            fh.write(json.dumps(asdict(msg), ensure_ascii=False) + "\n")

    logging.info("Wrote %d fetched message(s) to %s", len(messages), path)

def ingest_signal_urls(
    *,
    dry_run: bool = False,
    state_file_override: Optional[str] = None,
    signal_cli_override: Optional[str]=None,
    ignore_cli_support_flag: bool=False,
    message_log: Optional[str] = None,
    since_override: Optional[int] = None,
    sender_filter: Optional[str] = None,
) -> int:
    binary = signal_cli_override or os.environ.get("SIGNAL_CLI_BIN", "signal-cli")
    phone = os.environ.get("SIGNAL_PHONE_NUMBER")
    group_id = os.environ.get("SIGNAL_GROUP_ID")
    sender = sender_filter or os.environ.get("SIGNAL_SENDER")
    receive_limit_env = os.environ.get("SIGNAL_RECEIVE_LIMIT")
    receive_limit = int(receive_limit_env) if receive_limit_env else None
    added_by = os.environ.get("SIGNAL_ADDED_BY", DEFAULT_ADDED_BY)

    if not phone:
        logging.error("SIGNAL_PHONE_NUMBER environment variable is required")
        return 1

    state_path: Optional[Path] = None
    last_ts: Optional[int] = None

    message_log_path: Optional[Path] = None
    if message_log:
        message_log_path = Path(message_log)

    if dry_run:
        if state_file_override:
            state_path = _resolve_state_path(None, state_file_override)
            last_ts = _load_state_path(state_path)
            logging.info("Dry-run mode using state file %s (last timestamp: %s)", state_path, last_ts)
        else:
            logging.info("Dry-run mode without state tracking; all fetched messages will be considered new")
    else:
        app = create_app()
        with app.app_context():
            state_path = _resolve_state_path(current_app, state_file_override)
            last_ts = _load_state_path(state_path)
            logging.info("Last processed timestamp: %s", last_ts)

            since_ts = since_override if since_override is not None else last_ts
            if since_override is not None:
                logging.info("Using user-supplied --since override: %s", since_override)

            messages = _fetch_signal_messages(
                binary=binary,
                phone_number=phone,
                group_id=group_id,
                sender=sender,
                since_timestamp=since_ts,
                receive_limit=receive_limit,
                ignore_cli_support_flag=ignore_cli_support_flag,
            )

            if message_log_path:
                _write_message_log(messages, message_log_path)

            if not messages:
                logging.info("No new messages to process")
                return 0

            existing_urls = _load_existing_urls(current_app)
            logging.info("Found %d existing URLs in feed", len(existing_urls))

            added_count = 0
            newest_ts = (since_ts or last_ts) or 0
            discovered: List[Tuple[str, int]] = []

            for msg in sorted(messages, key=lambda m: m.timestamp):
                newest_ts = max(newest_ts, msg.timestamp)
                urls = list(_iter_urls(msg.text))
                if not urls:
                    continue

                logging.info(
                    "Processing message %s from %s containing %d URL(s)",
                    msg.timestamp,
                    msg.sender,
                    len(urls),
                )

                for url in urls:
                    if url in existing_urls:
                        logging.info("Skipping duplicate URL: %s", url)
                        continue
                    try:
                        news_svc.add_article_by_url(current_app, url, added_by=added_by)
                    except Exception:
                        logging.exception("Failed to ingest URL %s", url)
                        continue
                    existing_urls.add(url)
                    added_count += 1
                    discovered.append((url, msg.timestamp))

            if discovered:
                _print_urls_summary(discovered)

            if state_path and newest_ts and newest_ts != last_ts:
                _save_state_path(state_path, newest_ts)
                logging.info("Persisted newest timestamp %s", newest_ts)

            logging.info("Ingested %d new article(s)", added_count)
            return 0 if added_count >= 0 else 1

    # Dry-run flow (outside app context)
    since_ts = since_override if since_override is not None else last_ts
    if since_override is not None:
        logging.info("Using user-supplied --since override: %s", since_override)

    messages = _fetch_signal_messages(
        binary=binary,
        phone_number=phone,
        group_id=group_id,
        sender=sender,
        since_timestamp=since_ts,
        receive_limit=receive_limit,
        ignore_cli_support_flag=ignore_cli_support_flag,
    )

    if message_log_path:
        _write_message_log(messages, message_log_path)

    if not messages:
        logging.info("No new messages to process")
        return 0

    discovered: List[Tuple[str, int]] = []
    newest_ts = (since_ts or last_ts) or 0
    for msg in sorted(messages, key=lambda m: m.timestamp):
        newest_ts = max(newest_ts, msg.timestamp)
        for url in _iter_urls(msg.text):
            discovered.append((url, msg.timestamp))

    _print_urls_summary(discovered)

    if state_path and newest_ts and newest_ts != last_ts:
        _save_state_path(state_path, newest_ts)
        logging.info("Persisted newest timestamp %s (dry-run mode)", newest_ts)

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Signal URLs into the UAS news feed")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print URLs without touching the CSV store")
    parser.add_argument(
        "--state-file",
        help=(
            "Optional override for the ingestion checkpoint file. "
            "Useful when running in dry-run mode or storing state outside the Flask instance directory."
        ),
    )
    parser.add_argument(
        "--signal-cli",
        help=(
            "Optional override for the signal-cli binary path. Mirrors the SIGNAL_CLI_BIN environment variable"
            " but can be passed per-run."
        ),
    )
    parser.add_argument(
        "--log-file",
        dest="log_file",
        help="Optional path to write script logs",
    )
    parser.add_argument(
        "--message-log",
        dest="message_log",
        help="Optional path to write fetched Signal messages as JSON lines",
    )
    parser.add_argument(
        "--since",
        type=_parse_since_argument,
        help=(
            "Optional timestamp override (milliseconds since epoch or ISO 8601)"
            " to re-process older messages."
        ),
    )
    parser.add_argument(
        "--sender",
        dest="sender",
        help=(
            "Optional sender phone number filter (E.164). Useful for one-on-one or"
            " 'Note to Self' conversations."
        ),
    )
    parser.add_argument(
        "--ignore_cli_support_flag",
        action="store_true",
        help=("Optional override for the cli supporting --group or -g flags"),
    )
    args = parser.parse_args(argv)

    logging_kwargs = {"level": logging.INFO, "format": "%(asctime)s %(levelname)s %(message)s"}
    if args.log_file:
        log_path = Path(args.log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging_kwargs["handlers"] = [
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ]

    logging.basicConfig(**logging_kwargs)
    return ingest_signal_urls(
        dry_run=args.dry_run,
        state_file_override=args.state_file,
        signal_cli_override=args.signal_cli,
        ignore_cli_support_flag=args.ignore_cli_support_flag,
        message_log=args.message_log,
        since_override=args.since,
        sender_filter=args.sender,
    )


if __name__ == "__main__":
    sys.exit(main())