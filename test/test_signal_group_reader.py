from __future__ import annotations

import sys
from pathlib import Path
import io

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import signal_group_reader as sgr


def test_extract_group_id_from_group_info():
    envelope = {"dataMessage": {"groupInfo": {"groupId": "legacy"}}}

    assert sgr._extract_group_id(envelope) == "legacy"


def test_extract_group_id_from_group_v2():
    envelope = {"dataMessage": {"groupV2": {"groupId": "v2-id"}}}

    assert sgr._extract_group_id(envelope) == "v2-id"


def test_extract_group_id_from_sync_destination():
    envelope = {"syncMessage": {"sentMessage": {"destinationGroupId": "sync-id"}}}

    assert sgr._extract_group_id(envelope) == "sync-id"


def test_normalize_uses_extracted_group_id():
    envelope = {
        "timestamp": 123,
        "sourceName": "Alice",
        "dataMessage": {
            "message": "Hello",
            "groupV2": {"groupId": "group-id"},
        },
    }

    info = sgr.normalize(envelope)

    assert info["group_id"] == "group-id"
    assert info["text"] == "Hello"
    assert info["sender"] == "Alice"
    assert info["is_outgoing"] is False


def test_run_raises_when_signal_cli_exits_early(monkeypatch):
    class FakeProcess:
        def __init__(self, returncode: int = 0):
            self._returncode = returncode
            self.stdout = io.StringIO("")

        def poll(self):
            return self._returncode

        def terminate(self):
            self._returncode = self._returncode or -15

        def wait(self, timeout=None):
            return self._returncode

        def kill(self):
            self._returncode = self._returncode or -9

    fake_process = FakeProcess()

    monkeypatch.setattr(sgr, "resolve_signal_cli", lambda value: value)
    monkeypatch.setattr(sgr, "get_group_id", lambda *args, **kwargs: "group")
    monkeypatch.setattr(
        sgr.subprocess,
        "Popen",
        lambda *args, **kwargs: fake_process,
    )

    with pytest.raises(RuntimeError) as excinfo:
        sgr.run(
            number="+15555550100",
            group_name="Test",
            signal_cli="signal-cli",
            log_file=None,
            max_minutes=2,
            on_message=None,
        )

    assert "exited unexpectedly" in str(excinfo.value)
