"""Simple background scheduler for ingesting Signal URLs inside the web app."""
from __future__ import annotations

import json, os, threading, time
from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class ManualIngestionStatus:
    """Represents the lifecycle and outcome of a manual ingestion run."""

    state: str = "idle"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    results: Optional[list[tuple[GroupConfig, int]]] = None
    error: Optional[str] = None
    dry_run: bool = False

    def is_running(self) -> bool:
        return self.state == "running"


@dataclass(frozen=True)
class ManualTriggerResult:
    """Return value from :func:`trigger_manual_ingestion`."""

    started: bool
    message: str
    category: str
    status: Optional[ManualIngestionStatus]


_manual_run_lock = threading.Lock()
_manual_run_thread: Optional[threading.Thread] = None
_manual_run_status = ManualIngestionStatus()


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


def _clone_status(status: Optional[ManualIngestionStatus]) -> Optional[ManualIngestionStatus]:
    if status is None:
        return None
    return ManualIngestionStatus(
        state=status.state,
        started_at=status.started_at,
        finished_at=status.finished_at,
        results=list(status.results) if status.results is not None else None,
        error=status.error,
        dry_run=status.dry_run,
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
) -> int:
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
        return exit_code
    except Exception:  # pragma: no cover - defensive logging
        app.logger.exception(
            "Signal scheduler: unexpected failure while processing group '%s'",
            group.name,
        )
        return 1


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


def _prepare_run(app: Flask) -> Optional[tuple[list[GroupConfig], str, str, bool, Optional[float]]]:
    groups = _load_group_configs(app)
    if not groups:
        return None

    phone = os.getenv("SIGNAL_PHONE_NUMBER")
    if not phone:
        raise RuntimeError(
            "SIGNAL_PHONE_NUMBER is not configured; unable to run Signal update.",
        )

    signal_cli = os.getenv("SIGNAL_CLI_BIN", "signal-cli")
    dry_run = _strtobool(os.getenv("SIGNAL_DRY_RUN"))

    max_minutes_env = os.getenv("SIGNAL_MAX_MINUTES")
    max_minutes: Optional[float] = None
    if max_minutes_env:
        try:
            parsed = float(max_minutes_env)
            if parsed <= 0:
                raise ValueError
            max_minutes = parsed
        except (TypeError, ValueError):
            app.logger.warning(
                "Invalid SIGNAL_MAX_MINUTES value '%s'; ignoring",
                max_minutes_env,
            )
            max_minutes = None

    return groups, phone, signal_cli, dry_run, max_minutes


def _execute_run(
    app: Flask,
    groups: list[GroupConfig],
    *,
    phone: str,
    signal_cli: str,
    dry_run: bool,
    max_minutes: Optional[float],
) -> list[tuple[GroupConfig, int]]:
    results: list[tuple[GroupConfig, int]] = []
    for group in groups:
        exit_code = _run_group(
            app,
            group,
            phone=phone,
            signal_cli=signal_cli,
            dry_run=dry_run,
            max_minutes=max_minutes,
        )
        results.append((group, exit_code))
    return results


def run_ingestion_once(app: Flask) -> list[tuple[GroupConfig, int]]:
    """Run Signal ingestion immediately for the configured group(s).

    Returns a list of ``(GroupConfig, exit_code)`` tuples. When no groups are
    configured an empty list is returned. A ``RuntimeError`` is raised if the
    environment lacks required settings.
    """

    prepared = _prepare_run(app)
    if not prepared:
        return []

    groups, phone, signal_cli, dry_run, max_minutes = prepared
    return _execute_run(
        app,
        groups,
        phone=phone,
        signal_cli=signal_cli,
        dry_run=dry_run,
        max_minutes=max_minutes,
    )


def trigger_manual_ingestion(app: Flask) -> ManualTriggerResult:
    """Start an ingestion run in a background thread."""

    try:
        prepared = _prepare_run(app)
    except RuntimeError as exc:
        return ManualTriggerResult(False, str(exc), "error", get_manual_ingestion_status())

    if not prepared:
        return ManualTriggerResult(
            False,
            "No Signal groups are configured for ingestion.",
            "warning",
            get_manual_ingestion_status(),
        )

    groups, phone, signal_cli, dry_run, max_minutes = prepared

    with _manual_run_lock:
        global _manual_run_thread, _manual_run_status

        if _manual_run_thread and _manual_run_thread.is_alive():
            status = _clone_status(_manual_run_status)
            started_at = (
                status.started_at.strftime("%Y-%m-%d %H:%M UTC")
                if status and status.started_at
                else "unknown"
            )
            message = f"Signal update is already running (started {started_at})."
            return ManualTriggerResult(False, message, "warning", status)

        status = ManualIngestionStatus(
            state="running",
            started_at=datetime.utcnow(),
            finished_at=None,
            results=[],
            error=None,
            dry_run=dry_run,
        )
        _manual_run_status = status

        def _target() -> None:
            nonlocal groups, phone, signal_cli, dry_run, max_minutes, status
            try:
                with app.app_context():
                    results = _execute_run(
                        app,
                        groups,
                        phone=phone,
                        signal_cli=signal_cli,
                        dry_run=dry_run,
                        max_minutes=max_minutes,
                    )
                    failures = [group.name for group, code in results if code != 0]
                    status.results = results
                    status.finished_at = datetime.utcnow()
                    if failures:
                        status.state = "completed_with_errors"
                        status.error = ", ".join(failures)
                        app.logger.warning(
                            "Signal manual ingestion completed with failures for: %s",
                            ", ".join(failures),
                        )
                    else:
                        status.state = "succeeded"
                        status.error = None
                        app.logger.info("Signal manual ingestion completed successfully")
            except Exception as exc:  # pragma: no cover - defensive logging
                app.logger.exception("Signal manual ingestion failed: %s", exc)
                status.finished_at = datetime.utcnow()
                status.state = "failed"
                status.error = str(exc)
                status.results = None
            finally:
                with _manual_run_lock:
                    _manual_run_thread = None

        thread = threading.Thread(
            target=_target,
            name="signal-manual-run",
            daemon=True,
        )
        _manual_run_thread = thread
        thread.start()

        return ManualTriggerResult(
            True,
            "Signal update started in the background. Monitor the logs for progress.",
            "success",
            _clone_status(status),
        )


def get_manual_ingestion_status() -> Optional[ManualIngestionStatus]:
    with _manual_run_lock:
        return _clone_status(_manual_run_status)


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
        max_minutes: Optional[float]
        if max_minutes_env:
            try:
                max_minutes = float(max_minutes_env)
                if max_minutes <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                app.logger.warning(
                    "Invalid SIGNAL_MAX_MINUTES value '%s'; ignoring", max_minutes_env
                )
                max_minutes = None
        else:
            max_minutes = max(interval / 60.0, 1.0)
            app.logger.info(
                "Signal scheduler: defaulting run window to %.1f minutes to cover the %d-second interval",
                max_minutes,
                interval,
            )

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


__all__ = [
    "init_signal_scheduler",
    "run_ingestion_once",
    "trigger_manual_ingestion",
    "get_manual_ingestion_status",
    "ManualIngestionStatus",
    "ManualTriggerResult",
]
