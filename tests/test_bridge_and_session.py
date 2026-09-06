"""Bridge, session, and response unit tests (no Pi subprocess needed)."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from op0.bridge import ReadOnlyToolBridge
from op0.response import response_text_from_payload, sanitize_terminal_text
from op0.session import Session


def _request(bridge: ReadOnlyToolBridge, payload: dict) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(5.0)
    client.connect(bridge.socket_path)
    client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
    buffer = bytearray()
    while b"\n" not in buffer:
        chunk = client.recv(4096)
        if not chunk:
            break
        buffer.extend(chunk)
    client.close()
    return json.loads(bytes(buffer.split(b"\n", 1)[0]).decode("utf-8"))


def test_bridge_serves_scoped_read(tmp_path: Path) -> None:
    (tmp_path / "answer.txt").write_text("VALUE = 555\n", encoding="utf-8")
    bridge = ReadOnlyToolBridge((str(tmp_path),))
    bridge.start()
    try:
        response = _request(
            bridge,
            {"type": "tool_call", "toolName": "openpilot_read", "toolCallId": "c1", "args": {"path": "answer.txt"}},
        )
        assert response["success"] is True
        assert "555" in response["content"]
    finally:
        bridge.stop()


def test_bridge_rejects_out_of_scope(tmp_path: Path) -> None:
    (tmp_path / "inside.txt").write_text("ok", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    bridge = ReadOnlyToolBridge((str(tmp_path),))
    bridge.start()
    try:
        response = _request(
            bridge,
            {"type": "tool_call", "toolName": "openpilot_read", "toolCallId": "c2", "args": {"path": str(outside)}},
        )
        assert response["success"] is False
        assert "secret" not in response["content"]
    finally:
        bridge.stop()


def test_bridge_rejects_unknown_tool(tmp_path: Path) -> None:
    bridge = ReadOnlyToolBridge((str(tmp_path),))
    bridge.start()
    try:
        response = _request(
            bridge,
            {"type": "tool_call", "toolName": "openpilot_patch", "toolCallId": "c3", "args": {}},
        )
        assert response["success"] is False
    finally:
        bridge.stop()


def test_session_trajectory_roundtrip(tmp_path: Path) -> None:
    session = Session(tmp_path)
    session.record("tool_call", {"path": "answer.txt"}, producer="bridge", call_id="c1")
    session.record(
        "model_response",
        {"message": {"role": "assistant", "content": [{"type": "text", "text": "555"}], "stopReason": "stop"}},
    )
    # a user message_end must never be mistaken for a model response
    session.record(
        "model_response",
        {"message": {"role": "user", "content": [{"type": "text", "text": "user prompt"}], "stopReason": "stop"}},
    )
    events = session.load_events()
    assert [e.event_type for e in events] == ["tool_call", "model_response", "model_response"]
    assert events[0].payload["path"] == "answer.txt"
    assert session.last_model_response() == "555"
    assert session.path.exists() and session.path.suffix == ".jsonl"


def test_response_extraction_and_sanitization() -> None:
    assert response_text_from_payload({"text": "  VALUE = 555 "}) == "VALUE = 555"
    assert response_text_from_payload({"nested": [{"content": "x"}]}) == "x"
    dirty = "\x1b[31mred\u200btext\x1b[0m"
    assert sanitize_terminal_text(dirty) == "redtext"
    assert len(sanitize_terminal_text("a" * 9000)) == 6000
