"""实机日志片段夹具：启动序列与抓取会话的解析行为。

夹具存放于 ``tests/fixtures/serial/``，保留设备真实的 ``\\r\\r\\n`` 行尾：

- ``hi3861-boot.txt``：固件启动输出（bsp 初始化行 + 多行栈堆），按固件代码构造；
- ``hi3861-session.txt``：COM3 实机抓取的稳态会话（心跳 / 传感器 / 命令回复）。
"""

from __future__ import annotations

from pathlib import Path

from serial_log_analyzer.core.device import command as device_command
from serial_log_analyzer.core.logs.line_framer import LineFramer
from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.logs import LogLevel

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "serial"


def _feed(raw: bytes, parser: LogParser) -> tuple[LogPipeline, list]:
    """按 DeviceSession 的分发规则（``@`` 回复 vs 日志）吃下整段原始字节。"""

    framer = LineFramer()
    pipeline = LogPipeline(parser)
    replies = []
    for line in framer.feed(raw):
        if device_command.is_response_line(line):
            replies.append(device_command.parse_response(line))
        else:
            pipeline.feed(line, 0.0)
    return pipeline, replies


def test_boot_fixture_parses(parser) -> None:
    pipeline, replies = _feed((_FIXTURES / "hi3861-boot.txt").read_bytes(), parser)
    assert replies == []
    entries = pipeline.entries()
    # 固件未格式化的 bsp 初始化行 → UNKNOWN 降级保留
    assert any(
        entry.level is LogLevel.UNKNOWN and entry.message.startswith("I2C PCF8574")
        for entry in entries
    )
    # 多行栈堆并入上一条
    assert any(entry.continuation and "osTimerStart" in entry.message for entry in entries)
    assert any(
        entry.level is LogLevel.INFO and entry.module == "main" and entry.message == "system ready"
        for entry in entries
    )


def test_session_fixture_parses(parser) -> None:
    pipeline, replies = _feed((_FIXTURES / "hi3861-session.txt").read_bytes(), parser)
    assert [(reply.text, reply.ok) for reply in replies] == [
        ("PONG", True),
        ("fw=1.0.0 chip=hi3861", True),
        ("PING VERSION HELP TEST LOGLEVEL", True),
    ]
    entries = pipeline.entries()
    assert entries and all(entry.message for entry in entries)  # \r\r\n 不产生空条目
    sensors = [entry for entry in entries if entry.module == "sensor"]
    assert len(sensors) == 2
    assert sensors[0].extra["temperature"] == "26.4"
    assert sensors[0].extra["infrared"] == "3"
