"""门控硬件联调测试：需设置 SLA_HW_PORT 且连接实机。"""

from __future__ import annotations

import os
import re

import pytest

from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.logs.preset import LogPreset, PresetLineRule
from serial_log_analyzer.core.models.device import SerialConfig
from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.core.services.device_session import (
    DeviceSession,
    DeviceSessionHandlers,
)
from serial_log_analyzer.io.serial.qt_serial_transport import QtSerialTransport

pytestmark = pytest.mark.skipif(
    not os.environ.get("SLA_HW_PORT"), reason="需设置 SLA_HW_PORT 并接实机"
)

_LINE = re.compile(r"^\[(?P<level>\w+)\]\s*\[(?P<module>[^\]]+)\]\s*(?P<message>.*)$")
_LEVEL_MAP = {
    "V": LogLevel.VERBOSE,
    "D": LogLevel.DEBUG,
    "I": LogLevel.INFO,
    "W": LogLevel.WARN,
    "E": LogLevel.ERROR,
}


def _preset() -> LogPreset:
    return LogPreset("hw", "HW", PresetLineRule(pattern=_LINE, level_map=_LEVEL_MAP))


def test_hw_receives_log_and_ping(qtbot) -> None:
    pipeline = LogPipeline(LogParser(_preset()))
    replies: list[tuple[str, bool]] = []
    session = DeviceSession(
        QtSerialTransport(),
        pipeline,
        DeviceSessionHandlers(
            on_update=lambda update: None,
            on_state=lambda state, message: None,
            on_error=lambda error: None,
            on_command_reply=lambda text, ok: replies.append((text, ok)),
        ),
    )
    session.connect(SerialConfig(port=os.environ["SLA_HW_PORT"]))
    try:
        qtbot.waitUntil(lambda: len(pipeline.entries()) > 0, timeout=5000)
        session.send_command("PING")
        qtbot.waitUntil(lambda: any(text == "PONG" for text, _ in replies), timeout=3000)
    finally:
        session.disconnect()
    assert any(entry.level is LogLevel.INFO for entry in pipeline.entries())
    assert ("PONG", True) in replies
