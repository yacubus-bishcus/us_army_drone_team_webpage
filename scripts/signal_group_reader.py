"""
USAGE (foreground or under systemd):
  python signal_group_reader.py \
    --number +1XXXXXXXXXX \
    --group-name "Testing" \
    [--signal-cli /path/to/signal-cli] \
    [--log-file ~/.logs/testing_group.log] \
    [--max-minutes 15]

Notes:
- Keep --log-file if you also want a rotating file; journal already captures stdout/stderr.
- For systemd auto-stop, prefer RuntimeMaxSec= instead of --max-minutes.
"""

import argparse, json, logging, signal, subprocess, sys, time
from shutil import which
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_NAME = REPO_ROOT.name

stop = False

def on_signal(sig, frame):
    global stop
    logging.info("Received signal %s, shutting down...", sig)
    stop = True

def human(ts_ms: Optional[int]) -> str:
    if not ts_ms:
        return datetime.now().isoformat(sep=" ", timespec="seconds")
    return datetime.fromtimestamp(ts_ms/1000).isoformat(sep=" ", timespec="seconds")

def setup_logging(log_file: Optional[str]):
    root = logging.getLogger()
    root.handlers[:] = []
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    # journal captures stdout/stderr → always log to stdout
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # optional file mirror
    if log_file:
        p = Path(log_file).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(p, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

def get_group_id(number: str, name: str, signal_cli: str) -> str:
    """Resolve group ID by display name (case-insensitive)."""
    res = subprocess.run(
        [signal_cli, "-u", number, "--output=json", "listGroups"],
        check=True, capture_output=True, text=True
    )
    groups = json.loads(res.stdout or "[]")
    ncf = name.casefold()
    exact = [g for g in groups if (g.get("name") or "").casefold() == ncf]
    cand = exact or [g for g in groups if ncf in (g.get("name") or "").casefold()]
    if not cand:
        raise SystemExit(f"Group named '{name}' not found. Available: {[g.get('name') for g in groups]}")
    gid = cand[0].get("id") or cand[0].get("groupId")
    if not gid:
        raise SystemExit("Matched group has no ID field in listGroups output.")
    return gid

def normalize(envelope: dict) -> dict:
    dm = envelope.get("dataMessage") or {}
    sm = (envelope.get("syncMessage") or {}).get("sentMessage") or {}
    text = dm.get("message") or sm.get("message") or ""
    group = (dm.get("groupInfo") or {}).get("groupId") or (sm.get("groupInfo") or {}).get("groupId")
    return {
        "timestamp": envelope.get("timestamp"),
        "sender": envelope.get("sourceName") or envelope.get("source") or "me",
        "text": text,
        "group_id": group,
        "is_outgoing": bool(sm),
    }

def resolve_signal_cli(signal_cli: str) -> str:
    """Return an absolute path to the signal-cli binary or exit."""
    candidate = Path(signal_cli).expanduser()
    if candidate.is_file():
        return str(candidate)

    if candidate.is_absolute() and REPO_NAME in candidate.parts:
        # Users often configure a host path (e.g. /home/me/<repo>/bin/signal-cli)
        # while the container sees the project under /app. Try to translate the
        # tail of that path so the same repo asset can be located inside Docker.
        tail = Path(*candidate.parts[candidate.parts.index(REPO_NAME) + 1 :])
        translated = REPO_ROOT / tail
        if translated.is_file():
            logging.info(
                "Resolved signal-cli binary inside container as %s (from %s)",
                translated,
                candidate,
            )
            return str(translated)

    discovered = which(signal_cli)
    if discovered:
        return discovered

    raise SystemExit(
        "signal-cli binary not found. "
        "Set SIGNAL_CLI_BIN to a path that exists inside the container (e.g. /app/bin/signal-cli) "
        "or install signal-cli in PATH."
    )


def run(number: str, group_name: str, signal_cli: str,
        log_file: Optional[str], max_minutes: Optional[float]):

    setup_logging(log_file)
    if max_minutes:
        logging.info("Time limit set: %.2f minutes", max_minutes)

    # Handle SIGTERM/SIGINT (systemd will send SIGTERM on stop)
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, on_signal)

    signal_cli_path = resolve_signal_cli(signal_cli)

    gid = get_group_id(number, group_name, signal_cli_path)
    logging.info("Filtering for group '%s' (ID %s)", group_name, gid)

    # Start jsonRpc
    p = subprocess.Popen(
        [signal_cli_path, "-u", number, "jsonRpc"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )

    deadline = (time.monotonic() + max_minutes * 60.0) if max_minutes else None
    try:
        assert p.stdout is not None
        for raw in p.stdout:
            if stop:
                break
            if deadline and time.monotonic() >= deadline:
                logging.info("Time limit (%.2f minutes) reached; shutting down.", max_minutes)
                break

            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # ignore non-JSON noise

            if msg.get("method") != "receive":
                continue

            env = (msg.get("params") or {}).get("envelope") or {}
            info = normalize(env)
            if info["group_id"] != gid:
                continue

            logging.info("[%s] %s: %s",
                         human(info["timestamp"] or 0),
                         "(me)" if info["is_outgoing"] else info["sender"],
                         info["text"])
    finally:
        if p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                p.kill()

def main():
    ap = argparse.ArgumentParser(description="Stream Signal messages from a specific group via signal-cli jsonRpc (systemd-friendly).")
    ap.add_argument("--number", "-u", required=True, help="Your Signal account number (e.g. +14125551234)")
    ap.add_argument("--group-name", "-g", required=True, help="Group display name to filter (case-insensitive).")
    ap.add_argument("--signal-cli", default="signal-cli", help="Path to signal-cli binary (default: find in PATH).")
    ap.add_argument("--log-file", help="Optional: also append logs here (journal always captures stdout).")
    ap.add_argument("--max-minutes", type=float, help="Optional: stop after N minutes (for testing).")
    
    args = ap.parse_args()

    if args.max_minutes is not None and args.max_minutes <= 0:
        ap.error("--max-minutes must be a positive number")

    run(args.number, args.group_name, args.signal_cli, args.log_file, args.max_minutes)

if __name__ == "__main__":
    main()
