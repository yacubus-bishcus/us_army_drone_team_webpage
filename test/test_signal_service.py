from __future__ import annotations

import sys
from pathlib import Path
import types

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.signal_service as signal_service


def _mock_pull_signal_news(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"

    monkeypatch.setattr(
        signal_service.pull_signal_news,
        "_resolve_state_path",
        lambda app, _: state_path,
    )
    monkeypatch.setattr(
        signal_service.pull_signal_news,
        "_load_state_path",
        lambda path: None,
    )
    monkeypatch.setattr(
        signal_service.pull_signal_news,
        "_load_existing_urls",
        lambda app: set(),
    )
    monkeypatch.setattr(
        signal_service.pull_signal_news,
        "_iter_urls",
        lambda text: iter(()),
    )
    monkeypatch.setattr(
        signal_service.pull_signal_news,
        "_print_urls_summary",
        lambda discovered: None,
    )
    monkeypatch.setattr(
        signal_service.pull_signal_news,
        "_save_state_path",
        lambda path, ts: None,
    )
    monkeypatch.setattr(
        signal_service.pull_signal_news,
        "news_svc",
        types.SimpleNamespace(add_article_by_url=lambda *args, **kwargs: None),
    )


def _mock_reader(monkeypatch):
    captured = {}

    def fake_reader(*, number, group_name, signal_cli, log_file, max_minutes, on_message):
        captured.update(
            number=number,
            group_name=group_name,
            signal_cli=signal_cli,
            log_file=log_file,
            max_minutes=max_minutes,
            on_message=on_message,
        )

    monkeypatch.setattr(signal_service.signal_group_reader, "run", fake_reader)
    return captured


def _invoke(monkeypatch, tmp_path, *, sandbox_env: str | None):
    if sandbox_env is not None:
        monkeypatch.setenv("SANDBOX_DATA_MODE", sandbox_env)
    else:
        monkeypatch.delenv("SANDBOX_DATA_MODE", raising=False)

    _mock_pull_signal_news(monkeypatch, tmp_path)
    captured = _mock_reader(monkeypatch)

    def fake_create_app():
        app = Flask(__name__)
        app.config["DATA_DIR"] = str(tmp_path / "data")
        app.config["SANDBOX_DATA_MODE"] = (
            (sandbox_env or "0").lower() in {"1", "true", "t", "yes", "y", "on"}
        )
        return app

    monkeypatch.setattr(signal_service, "create_app", fake_create_app)

    log_path = tmp_path / "log.txt"
    result = signal_service.run(
        number="+15555550100",
        group_name="Test",
        signal_cli="signal-cli",
        log_file=str(log_path),
        max_minutes=None,
        dry_run=True,
        added_by=None,
        target_count=1,
    )

    return result, captured


def test_default_runtime_sandbox(monkeypatch, tmp_path):
    result, captured = _invoke(monkeypatch, tmp_path, sandbox_env="true")

    assert result == 0
    assert captured["max_minutes"] == signal_service._SANDBOX_RUNTIME_MINUTES


def test_default_runtime_production(monkeypatch, tmp_path):
    result, captured = _invoke(monkeypatch, tmp_path, sandbox_env="false")

    assert result == 0
    assert captured["max_minutes"] == signal_service._PRODUCTION_RUNTIME_MINUTES
