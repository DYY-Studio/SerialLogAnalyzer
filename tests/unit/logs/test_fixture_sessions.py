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
        ("PING VERSION HELP TEST", True),
    ]
    entries = pipeline.entries()
    assert entries and all(entry.message for entry in entries)  # \r\r\n 不产生空条目
    sensors = [entry for entry in entries if entry.module == "sensor"]
    assert len(sensors) == 2
    assert sensors[0].extra["temperature"] == "26.4"
    assert sensors[0].extra["infrared"] == "3"


def test_anomalies_fixture_parses_all_scenarios_and_boundaries(parser) -> None:
    raw = (_FIXTURES / "hi3861-anomalies.txt").read_bytes()
    framer = LineFramer()
    pipeline = LogPipeline(parser)
    replies = []
    # 按 257 字节任意切块喂入，同时覆盖半行/多行/超长行跨块分帧。
    for offset in range(0, len(raw), 257):
        for line in framer.feed(raw[offset : offset + 257]):
            if device_command.is_response_line(line):
                replies.append(device_command.parse_response(line))
            else:
                pipeline.feed(line, 0.0)
    assert framer.finalize() is None

    assert [(reply.text, reply.ok, reply.code) for reply in replies] == [
        ("PONG", True, None),
        ("TEST memory started", True, None),
        ("TEST watchdog started", True, None),
        ("TEST sensor started", True, None),
        ("TEST wifi started", True, None),
        ("TEST uart started", True, None),
        ("invalid test name", False, 2),
    ]

    entries = pipeline.entries()
    assert entries and all(entry.message for entry in entries)
    assert not any(entry.raw.startswith("@") for entry in entries)

    # N-01 / X-01 传感器结构化字段
    sensors = [entry for entry in entries if entry.module == "sensor"]
    assert sensors[0].extra["temperature"] == "26.4"
    assert sensors[2].extra["temperature"] == "27.1"

    # M-01 / T-01 多行栈堆合并
    malloc_entry = next(
        entry for entry in entries if entry.module == "memory" and "size=4096" in entry.message
    )
    assert malloc_entry.level is LogLevel.ERROR and malloc_entry.continuation is True
    assert "pvPortMalloc" in malloc_entry.message and "sensor_buf_alloc" in malloc_entry.message

    wdt_entry = next(entry for entry in entries if entry.module == "watchdog")
    assert wdt_entry.level is LogLevel.ERROR and wdt_entry.continuation is True
    assert "watchdog timeout" in wdt_entry.message and "wdt_feed_check" in wdt_entry.message

    # D-01 / C-01 / R-01 / X-01 故障覆盖
    assert any(entry.module == "i2c" and "i2c read failed" in entry.message for entry in entries)
    assert any(entry.module == "wifi" and "reconnect failed" in entry.message for entry in entries)
    uart_overflows = [
        entry for entry in entries if entry.module == "uart" and "uart rx overflow" in entry.message
    ]
    assert len(uart_overflows) == 4

    # B-01 回退、未知级别、超长行拆分与尾行恢复
    assert any(
        entry.level is LogLevel.UNKNOWN
        and entry.module is None
        and entry.message == "RAW_BSP_MSG unformatted diagnostic text"
        for entry in entries
    )
    assert any(
        entry.level is LogLevel.UNKNOWN
        and entry.module == "custom"
        and entry.message == "unmapped level token"
        for entry in entries
    )
    overlong_head = next(
        entry for entry in entries if entry.module == "boundary" and entry.level is LogLevel.WARN
    )
    assert len(overlong_head.raw) == 65536
    assert overlong_head.message.startswith("overlong_payload=")
    tail_idx = entries.index(overlong_head)
    assert entries[tail_idx + 1].level is LogLevel.UNKNOWN
    assert set(entries[tail_idx + 1].message) == {"A"}
    assert entries[-1].module == "app" and entries[-1].message == "heartbeat tick=2"
