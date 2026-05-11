"""Unit tests for WebSocket envelope helpers."""

from __future__ import annotations

from app.core.websocket_protocol import build_error, build_message, parse_inbound_message


def test_build_message_sets_version_and_aliases() -> None:
    msg = build_message("connect", {"player_id": "p1"})

    assert msg["v"] == 1
    assert msg["type"] == "connect"
    assert msg["event"] == "connect"
    assert msg["payload"] == {"player_id": "p1"}
    assert msg["player_id"] == "p1"


def test_build_message_preserves_reserved_keys_in_payload() -> None:
    msg = build_message("state", {"type": "inner", "v": 99, "x": 1})

    assert msg["type"] == "state"
    assert msg["v"] == 1
    assert msg["payload"]["type"] == "inner"
    assert msg["payload"]["v"] == 99
    assert msg["x"] == 1


def test_build_error_uses_code_as_default_message() -> None:
    msg = build_error("invalid_input_format")

    assert msg["type"] == "error"
    assert msg["payload"]["code"] == "invalid_input_format"
    assert msg["payload"]["message"] == "invalid_input_format"


def test_build_error_allows_message_and_details() -> None:
    msg = build_error("conflict", "roster changed", room_id="r1")

    assert msg["payload"]["code"] == "conflict"
    assert msg["payload"]["message"] == "roster changed"
    assert msg["payload"]["room_id"] == "r1"
    assert msg["room_id"] == "r1"


def test_parse_inbound_message_prefers_payload_dict() -> None:
    message_type, payload, version = parse_inbound_message(
        {
            "v": 1,
            "type": "input",
            "payload": {"keys": ["ctrl", "c"]},
            "keys": ["wrong"],
        }
    )

    assert message_type == "input"
    assert version == 1
    assert payload["keys"] == ["ctrl", "c"]
    assert payload["type"] == "input"
    assert payload["event"] == "input"
    assert payload["v"] == 1


def test_parse_inbound_message_uses_legacy_fields_when_no_payload() -> None:
    message_type, payload, version = parse_inbound_message(
        {
            "event": "join_room",
            "room_id": "room-a",
        }
    )

    assert message_type == "join_room"
    assert version is None
    assert payload["room_id"] == "room-a"
    assert payload["event"] == "join_room"
    assert payload["type"] == "join_room"


def test_parse_inbound_message_handles_non_dict_input() -> None:
    message_type, payload, version = parse_inbound_message("not-a-dict")

    assert message_type is None
    assert payload == {}
    assert version is None
