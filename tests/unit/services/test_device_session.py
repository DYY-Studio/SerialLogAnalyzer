"""DeviceSession 编排测试。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import SerialConnectionError
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.device import DeviceConnectionState, SerialConfig
from serial_log_analyzer.core.services.device_session import (
    DeviceSession,
    DeviceSessionHandlers,
)


class FakeTransport:
    """内存串口传输，供单测手动触发回调。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.opened = False
        self._on_bytes = None
        self._on_error = None

    def set_handlers(self, on_bytes, on_error) -> None:
        self._on_bytes = on_bytes
        self._on_error = on_error

    def list_ports(self):
        return []

    def open(self, config) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    @property
    def is_open(self) -> bool:
        return self.opened

    def emit(self, data: bytes) -> None:
        self._on_bytes(data)

    def fail(self, error: Exception) -> None:
        self._on_error(error)


def _handlers(**kwargs) -> DeviceSessionHandlers:
    return DeviceSessionHandlers(
        on_update=kwargs.get("on_update", lambda u: None),
        on_state=kwargs.get("on_state", lambda s, m: None),
        on_error=kwargs.get("on_error", lambda e: None),
        on_command_reply=kwargs.get("on_command_reply"),
    )


@pytest.fixture
def pipe(parser) -> LogPipeline:
    return LogPipeline(parser)


def test_connect_sets_state_and_forwards_log_lines(pipe) -> None:
    transport = FakeTransport()
    seen = []
    session = DeviceSession(transport, pipe, _handlers(on_update=seen.append))
    session.connect(SerialConfig(port="COM3"))
    assert session.state is DeviceConnectionState.CONNECTED
    transport.emit(b"[I] [main] ok\r\n")
    assert seen and seen[-1].added[0].message == "ok"


def test_command_reply_routed_not_into_pipeline(pipe) -> None:
    transport = FakeTransport()
    replies = []
    session = DeviceSession(transport, pipe, _handlers(on_command_reply=replies.append))
    session.connect(SerialConfig(port="COM3"))
    transport.emit(b"@OK PONG\r\n")
    assert [(r.text, r.ok) for r in replies] == [("PONG", True)]
    assert len(pipe.entries()) == 0

    transport.emit(b"@ERR 2 bad arg\r\n")
    assert (replies[-1].text, replies[-1].ok, replies[-1].code) == ("bad arg", False, 2)


def test_send_command_appends_crlf(pipe) -> None:
    transport = FakeTransport()
    session = DeviceSession(transport, pipe, _handlers())
    session.connect(SerialConfig(port="COM3"))
    session.send_command("PING")
    assert transport.written[-1] == b"PING\r\n"


def test_send_when_closed_raises(pipe) -> None:
    session = DeviceSession(FakeTransport(), pipe, _handlers())
    with pytest.raises(SerialConnectionError):
        session.send_command("PING")


def test_recoverable_transport_error_keeps_connected(pipe) -> None:
    transport = FakeTransport()
    errors = []
    session = DeviceSession(transport, pipe, _handlers(on_error=errors.append))
    session.connect(SerialConfig(port="COM3"))
    transport.fail(SerialConnectionError("framing error"))
    assert session.state is DeviceConnectionState.CONNECTED
    assert errors


def test_fatal_transport_error_after_close_sets_error(pipe) -> None:
    transport = FakeTransport()
    session = DeviceSession(transport, pipe, _handlers())
    session.connect(SerialConfig(port="COM3"))
    transport.close()
    transport.fail(SerialConnectionError("device gone"))
    assert session.state is DeviceConnectionState.ERROR


def test_disconnect_flushes_residual_line(pipe) -> None:
    transport = FakeTransport()
    session = DeviceSession(transport, pipe, _handlers())
    session.connect(SerialConfig(port="COM3"))
    transport.emit(b"[I] [main] half")
    assert len(pipe.entries()) == 0
    session.disconnect()
    assert [entry.message for entry in pipe.entries()] == ["half"]
    assert session.state is DeviceConnectionState.DISCONNECTED
