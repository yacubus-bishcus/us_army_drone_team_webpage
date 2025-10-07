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

The script keeps track of the last processed message timestamp inside the
Flask ``DATA_DIR`` (``instance/data`` by default) to ensure idempotent runs.
The script can be ran independent of flask using the --dry-run and --state-file flags 
Ex: python -m scripts.pull_signal_news --dry-run --state-file=/tmp/signal-state.json
"""
from __future__ import annotations

import argparse, json, logging, os, re, subprocess, sys
from dataclasses import dataclass
from datetime import datetime
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


def _parse_signal_cli_output(raw: str, target_group: Optional[str]) -> List[SignalMessage]:
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

        text = msg.get("message") or ""
        if not text:
            continue

        messages.append(
            SignalMessage(
                timestamp=envelope.get("timestamp") or 0,
                text=text,
                sender=envelope.get("source"),
                group_id=group_id,
            )
        )
    return messages


@lru_cache(maxsize=1)
def _signal_cli_supports_group_flag(binary: str) -> bool:
    """Return True if `signal-cli receive` advertises a `--group` flag."""

    help_cmd = [binary, "receive", "--help"]
    try:
        proc = subprocess.run(help_cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise
    except PermissionError:
        raise
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        logging.debug("Failed to detect --group support (exit code %s): %s", exc.returncode, output)
        return False

    help_text = (proc.stdout or "") + (proc.stderr or "")
    return "--group" in help_text


def _build_signal_cli_cmd(
    binary: str,
    phone_number: str,
    *,
    since_timestamp: Optional[int] = None,
    receive_limit: Optional[int]=None,
    log_file: Optional[str]=None,
) -> Sequence[str]:
    cmd = [binary, "--output=json", "--username", phone_number, "receive", "--ignore-attachments"]
    if since_timestamp:
        cmd.extend(["--since", str(since_timestamp)])
    if receive_limit:
        cmd.extend(["--max-messages", str(receive_limit)])
    if log_file:
        cmd.extend(["--log-file", str(log_file)])
    return cmd


def _fetch_signal_messages(
    *,
    binary: str,
    phone_number: str,
    group_id: Optional[str],
    since_timestamp: Optional[int],
    receive_limit: Optional[int],
    log_file: Optional[str],
) -> List[SignalMessage]:
    cmd = list(_build_signal_cli_cmd(binary, phone_number, since_timestamp=since_timestamp, receive_limit=receive_limit, log_file=log_file))
    if group_id and _signal_cli_supports_group_flag(binary):
        # `receive --group <id>` restricts output to a single group.
        cmd.extend(["--group", group_id])
    elif group_id:
        logging.info(
            "signal-cli receive on this host does not support --group; fetching all chats and filtering client-side"
        )

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

    messages = _parse_signal_cli_output(proc.stdout, group_id)
    logging.info("Fetched %d candidate messages", len(messages))
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


def ingest_signal_urls(
    *,
    dry_run: bool = False,
    state_file_override: Optional[str] = None,
    signal_cli_override: Optional[str]=None,
    log_file: Optional[str]=None,
) -> int:
    binary = signal_cli_override or os.environ.get("SIGNAL_CLI_BIN", "signal-cli")
    phone = os.environ.get("SIGNAL_PHONE_NUMBER")
    group_id = os.environ.get("SIGNAL_GROUP_ID")
    receive_limit_env = os.environ.get("SIGNAL_RECEIVE_LIMIT")
    receive_limit = int(receive_limit_env) if receive_limit_env else None
    added_by = os.environ.get("SIGNAL_ADDED_BY", DEFAULT_ADDED_BY)
    log_file = log_file 

    if not phone:
        logging.error("SIGNAL_PHONE_NUMBER environment variable is required")
        return 1

    state_path: Optional[Path] = None
    last_ts: Optional[int] = None

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

            messages = _fetch_signal_messages(
                binary=binary,
                phone_number=phone,
                group_id=group_id,
                since_timestamp=last_ts,
                receive_limit=receive_limit,
                log_file=log_file,
            )

            if not messages:
                logging.info("No new messages to process")
                return 0

            existing_urls = _load_existing_urls(current_app)
            logging.info("Found %d existing URLs in feed", len(existing_urls))

            added_count = 0
            newest_ts = last_ts or 0
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

            if newest_ts and newest_ts != last_ts:
                _save_state_path(state_path, newest_ts)
                logging.info("Persisted newest timestamp %s", newest_ts)

            logging.info("Ingested %d new article(s)", added_count)
            return 0 if added_count >= 0 else 1

    # Dry-run flow (outside app context)
    messages = _fetch_signal_messages(
        binary=binary,
        phone_number=phone,
        group_id=group_id,
        since_timestamp=last_ts,
        receive_limit=receive_limit,
        log_file=log_file,
    )

    if not messages:
        logging.info("No new messages to process")
        return 0

    discovered: List[Tuple[str, int]] = []
    newest_ts = last_ts or 0
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
        "--log_file",
        help=("Optional create log file"),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return ingest_signal_urls(
        dry_run=args.dry_run,
        state_file_override=args.state_file,
        signal_cli_override=args.signal_cli,
        log_file=args.log_file,
    )


if __name__ == "__main__":
    sys.exit(main())