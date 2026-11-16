"""``DeviceController`` 行为测试（pytest-qt）：40ms 批处理节流、清空丢弃、断开同步 flush 与命令超时。"""

from __future__ import annotations

from pathlib import Path

from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline, PipelineUpdate
from serial_log_analyzer.core.logs.preset_loader import load_preset
from serial_log_analyzer.core.models.device import SerialConfig
from serial_log_analyzer.core.services.device_session import DeviceSession
from serial_log_analyzer.io.resources import CompositeResourceLoader
from serial_log_analyzer.ui.controllers.device_controller import DeviceController

_REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeSerialTransport:
    """内存串口传输替身，用于驱动真实 ``DeviceSession`` 字节分发。"""

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

    def feed_bytes(self, data: bytes) -> None:
        assert self._on_bytes is not None
        self._on_bytes(data)


def _make_controller(
    *,
    capacity: int = 100,
    batch_interval_ms: int = 30,
    command_timeout_ms: int = 80,
) -> tuple[_FakeSerialTransport, DeviceController]:
    loader = CompositeResourceLoader([_REPO_ROOT])
    preset = load_preset(loader, "hi3861-default")
    pipeline = LogPipeline(LogParser(preset), capacity=capacity)
    transport = _FakeSerialTransport()
    session = DeviceSession(transport, pipeline)
    controller = DeviceController(
        session,
        batch_interval_ms=batch_interval_ms,
        command_timeout_ms=command_timeout_ms,
    )
    return transport, controller


def test_batch_coalesces_updates_over_interval(qtbot) -> None:
    transport, controller = _make_controller(capacity=3, batch_interval_ms=30)
    updates: list[PipelineUpdate] = []
    controller.log_update.connect(updates.append)
    controller.connect(SerialConfig(port="COM1"))

    # 同一批内写入 4 条（容量 3 淘汰首条）+ 一条多行续接，应合成为单次更新
    transport.feed_bytes(
        b"[I] [wifi] line 0\r\n"
        b"[I] [wifi] line 1\r\n"
        b"[I] [wifi] line 2\r\n"
        b"[I] [wifi] line 3\r\n"
        b"    detail\r\n"
    )
    assert updates == []

    qtbot.waitUntil(lambda: len(updates) == 1, timeout=1000)
    merged = updates[0]
    assert [entry.sequence for entry in merged.added] == [1, 2, 3]
    assert merged.added[-1].message == "line 3\n    detail"
    assert merged.updated == ()
    assert merged.dropped_sequences == ()

    # 跨批次：续接上一批已发出的条目并触发淘汰旧条目
    transport.feed_bytes(b"    extra\r\n[I] [wifi] line 4\r\n")
    qtbot.waitUntil(lambda: len(updates) == 2, timeout=1000)
    second = updates[1]
    assert [entry.sequence for entry in second.updated] == [3]
    assert second.updated[0].message.endswith("\n    extra")
    assert [entry.sequence for entry in second.added] == [4]
    assert second.dropped_sequences == (1,)


def test_clear_logs_discards_pending_updates(qtbot) -> None:
    transport, controller = _make_controller(batch_interval_ms=30)
    updates: list[PipelineUpdate] = []
    controller.log_update.connect(updates.append)
    controller.connect(SerialConfig(port="COM1"))

    transport.feed_bytes(b"[I] [wifi] stale line\r\n")
    assert updates == []

    controller.clear_logs()
    qtbot.wait(60)
    assert updates == []


def test_disconnect_flushes_pending_and_residual_synchronously(qtbot) -> None:
    transport, controller = _make_controller(batch_interval_ms=500)
    updates: list[PipelineUpdate] = []
    controller.log_update.connect(updates.append)
    controller.connect(SerialConfig(port="COM1"))

    transport.feed_bytes(b"[I] [wifi] buffered\r\n[W] [uart] tail without newline")
    assert updates == []

    controller.disconnect()
    assert len(updates) == 1
    assert [entry.message for entry in updates[0].added] == ["buffered", "tail without newline"]


def test_command_timeout_and_reply_recovery(qtbot) -> None:
    transport, controller = _make_controller(command_timeout_ms=60)
    timed_out: list[str] = []
    replies: list[str] = []
    controller.command_timed_out.connect(timed_out.append)
    controller.command_reply.connect(lambda reply: replies.append(reply.text))
    controller.connect(SerialConfig(port="COM1"))

    # 第一个命令及时回复 -> 不触发超时
    controller.send_command("PING")
    transport.feed_bytes(b"@OK PONG\r\n")
    qtbot.wait(90)
    assert replies == ["PONG"]
    assert timed_out == []

    # 连续两个命令未回复 -> 按顺序分别触发超时，且不影响后续命令正常回复
    controller.send_command("VERSION")
    controller.send_command("HELP")
    qtbot.waitUntil(lambda: timed_out == ["VERSION", "HELP"], timeout=1000)

    controller.send_command("PING")
    transport.feed_bytes(b"@OK PONG\r\n")
    assert replies == ["PONG", "PONG"]
