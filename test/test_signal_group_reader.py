from __future__ import annotations

import sys
from pathlib import Path

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
