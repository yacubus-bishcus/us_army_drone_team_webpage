"""Simple background scheduler for ingesting Signal URLs inside the web app."""
from __future__ import annotations

import json, os, threading, time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from flask import Flask
_DEFAULT_INTERVAL_SECONDS = 60 * 60 * 4  # 4 hours
_DEFAULT_TARGET_COUNT = 10

_scheduler_lock = threading.Lock()
_scheduler_started = False


@dataclass(frozen=True)
class GroupConfig:
    name: str
    log_file: str
    added_by: str
    target_count: int


def _strtobool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    slug = "_".join(filter(None, cleaned.split("_")))
    return slug or "signal_group"


def _resolve_log_path(app: Flask, raw_path: Optional[str], group_name: str) -> str:
    base_dir = Path(app.root_path).parent
    default_path = base_dir / "static" / "logs" / f"news_log_{_slugify(group_name)}.log"

    if not raw_path:
        return str(default_path)

    path = Path(raw_path)
    if not path.is_absolute():
        path = (base_dir / raw_path).resolve()
    return str(path)


def _normalize_group(app: Flask, payload: dict | str, default_target: int) -> Optional[GroupConfig]:
    if isinstance(payload, str):
        name = payload.strip()
        if not name:
            return None
        log_file = None
        added_by = None
        target_count = None
    elif isinstance(payload, dict):
        name = str(payload.get("name", "")).strip()
        if not name:
            return None
        log_file = payload.get("log_file")
        added_by = payload.get("added_by")
        target_count = payload.get("target_count")
    else:
        return None

    try:
        resolved_target = int(target_count) if target_count is not None else default_target
    except (TypeError, ValueError):
        resolved_target = default_target

    resolved_added_by = (added_by or name).strip() or name
    resolved_log = _resolve_log_path(app, log_file, name)

    return GroupConfig(
        name=name,
        log_file=resolved_log,
        added_by=resolved_added_by,
        target_count=resolved_target,
    )


def _load_group_configs(app: Flask) -> list[GroupConfig]:
    groups_env = os.getenv("SIGNAL_SCHEDULER_GROUPS")
    default_target = int(os.getenv("SIGNAL_TARGET_COUNT", str(_DEFAULT_TARGET_COUNT)))

    configs: list[GroupConfig] = []

    if groups_env:
        try:
            payload = json.loads(groups_env)
        except json.JSONDecodeError:
            app.logger.error("SIGNAL_SCHEDULER_GROUPS is not valid JSON; scheduler disabled")
            return []

        if isinstance(payload, (list, tuple)):
            for entry in payload:
                cfg = _normalize_group(app, entry, default_target)
                if cfg:
                    configs.append(cfg)
        else:
            cfg = _normalize_group(app, payload, default_target)
            if cfg:
                configs.append(cfg)
    else:
        single_name = os.getenv("SIGNAL_GROUP_NAME")
        if single_name:
            cfg = _normalize_group(
                app,
                {
                    "name": single_name,
                    "log_file": os.getenv("SIGNAL_LOG_FILE"),
                    "added_by": os.getenv("SIGNAL_ADDED_BY"),
                    "target_count": os.getenv("SIGNAL_TARGET_COUNT"),
                },
                default_target,
            )
            if cfg:
                configs.append(cfg)

    return configs


def _run_group(
    app: Flask,
    group: GroupConfig,
    *,
    phone: str,
    signal_cli: str,
    dry_run: bool,
    max_minutes: Optional[float],
) -> None:
    """Run a single Signal ingestion session for ``group``."""
    # Import lazily to avoid circular imports during Flask app creation.
    from scripts import signal_service

    app.logger.info("Signal scheduler: starting ingestion for group '%s'", group.name)
    try:
        exit_code = signal_service.run(
            phone,
            group.name,
            signal_cli,
            log_file=group.log_file,
            max_minutes=max_minutes,
            dry_run=dry_run,
            added_by=group.added_by,
            target_count=group.target_count,
        )
        if exit_code != 0:
            app.logger.warning(
                "Signal scheduler: ingestion for '%s' exited with status %s",
                group.name,
                exit_code,
            )
    except Exception:  # pragma: no cover - defensive logging
        app.logger.exception(
            "Signal scheduler: unexpected failure while processing group '%s'",
            group.name,
        )


def _run_iteration(
    app: Flask,
    groups: Iterable[GroupConfig],
    *,
    dry_run: bool,
    max_minutes: Optional[float],
) -> None:
    phone = os.getenv("SIGNAL_PHONE_NUMBER")
    if not phone:
        app.logger.error("Signal scheduler enabled but SIGNAL_PHONE_NUMBER is not configured")
        return

    signal_cli = os.getenv("SIGNAL_CLI_BIN", "signal-cli")

    threads: list[threading.Thread] = []

    for group in groups:
        thread = threading.Thread(
            target=_run_group,
            name=f"signal-group-{_slugify(group.name)}",
            args=(app, group),
            kwargs={
                "phone": phone,
                "signal_cli": signal_cli,
                "dry_run": dry_run,
                "max_minutes": max_minutes,
            },
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()


def _worker(
    app: Flask,
    groups: list[GroupConfig],
    interval: int,
    *,
    dry_run: bool,
    max_minutes: Optional[float],
) -> None:
    thread_name = threading.current_thread().name
    app.logger.info(
        "%s started; running %d Signal group(s) every %d seconds",
        thread_name,
        len(groups),
        interval,
    )

    while True:
        start = time.monotonic()
        try:
            _run_iteration(app, groups, dry_run=dry_run, max_minutes=max_minutes)
        except Exception:  # pragma: no cover - defensive logging
            app.logger.exception("Signal scheduler: iteration crashed")

        elapsed = time.monotonic() - start
        sleep_for = max(interval - int(elapsed), 0)
        if sleep_for:
            time.sleep(sleep_for)


def init_signal_scheduler(app: Flask) -> None:
    if _strtobool(os.getenv("DISABLE_SIGNAL_SCHEDULER")):
        app.logger.info("Signal scheduler disabled via DISABLE_SIGNAL_SCHEDULER")
        return

    if not _strtobool(os.getenv("ENABLE_SIGNAL_SCHEDULER")):
        app.logger.info("Signal scheduler disabled; set ENABLE_SIGNAL_SCHEDULER=1 to enable")
        return

    with _scheduler_lock:
        global _scheduler_started
        if _scheduler_started:
            app.logger.info("Signal scheduler already running; skipping initialization")
            return

        groups = _load_group_configs(app)
        if not groups:
            app.logger.warning("Signal scheduler enabled but no groups configured")
            return

        try:
            interval = int(os.getenv("SIGNAL_SCHEDULER_INTERVAL_SECONDS", str(_DEFAULT_INTERVAL_SECONDS)))
            if interval <= 0:
                raise ValueError
        except ValueError:
            app.logger.warning(
                "Invalid SIGNAL_SCHEDULER_INTERVAL_SECONDS value; using default %d seconds",
                _DEFAULT_INTERVAL_SECONDS,
            )
            interval = _DEFAULT_INTERVAL_SECONDS

        max_minutes_env = os.getenv("SIGNAL_MAX_MINUTES")
        try:
            max_minutes = float(max_minutes_env) if max_minutes_env else None
        except (TypeError, ValueError):
            app.logger.warning("Invalid SIGNAL_MAX_MINUTES value '%s'; ignoring", max_minutes_env)
            max_minutes = None

        dry_run = _strtobool(os.getenv("SIGNAL_DRY_RUN"))

        thread = threading.Thread(
            target=_worker,
            args=(app, groups, interval),
            kwargs={"dry_run": dry_run, "max_minutes": max_minutes},
            name="signal-scheduler",
            daemon=True,
        )
        thread.start()

        _scheduler_started = True


__all__ = ["init_signal_scheduler"]
