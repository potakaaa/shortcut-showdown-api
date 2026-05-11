"""Integration tests for websocket message routing and validation."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app


def test_ws_json_non_input_event_is_echoed_as_message_payload() -> None:
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        connected = ws.receive_json()
        assert connected["event"] == "connect"

        payload = {"event": "ping", "value": 42}
        ws.send_text(json.dumps(payload))

        echoed = ws.receive_json()
        assert echoed.get("event") == "message"
        assert echoed.get("type", "message") == "message"
        echoed_data = echoed.get("data")
        if echoed_data is None and isinstance(echoed.get("payload"), dict):
            echoed_data = echoed["payload"].get("data")
        assert echoed_data == payload


def test_ws_input_with_invalid_keys_format_returns_error() -> None:
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        connected = ws.receive_json()
        assert connected["event"] == "connect"

        ws.send_text(json.dumps({"event": "input", "keys": "ctrl+c"}))

        error = ws.receive_json()
        assert error.get("event") == "error"
        assert error.get("type", "error") == "error"
        message = error.get("message")
        if message is None and isinstance(error.get("payload"), dict):
            message = error["payload"].get("message")
        assert message == "invalid_input_format"
