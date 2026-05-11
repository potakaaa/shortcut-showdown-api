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
        assert echoed == {"event": "message", "data": payload}


def test_ws_input_with_invalid_keys_format_returns_error() -> None:
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        connected = ws.receive_json()
        assert connected["event"] == "connect"

        ws.send_text(json.dumps({"event": "input", "keys": "ctrl+c"}))

        error = ws.receive_json()
        assert error == {"event": "error", "message": "invalid_input_format"}
