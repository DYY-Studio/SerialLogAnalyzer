"""串口发现辅助测试。"""

from __future__ import annotations

from serial_log_analyzer.core.models.device import SerialPortInfo
from serial_log_analyzer.io.serial.port_discovery import (
    describe_port,
    find_port,
    friendly_priority,
)


def test_describe_port_with_description() -> None:
    info = SerialPortInfo(name="COM3", description="USB-SERIAL CH340")
    assert describe_port(info) == "COM3 — USB-SERIAL CH340"


def test_describe_port_without_description() -> None:
    assert describe_port(SerialPortInfo(name="COM3")) == "COM3"


def test_find_port() -> None:
    ports = [SerialPortInfo(name="COM1"), SerialPortInfo(name="COM3")]
    assert find_port(ports, "COM3").name == "COM3"
    assert find_port(ports, "COM9") is None


def test_friendly_priority_prefers_usb() -> None:
    usb = SerialPortInfo(name="COM3", description="USB-SERIAL CH340")
    builtin = SerialPortInfo(name="COM1", description="Communications Port")
    assert friendly_priority(usb) < friendly_priority(builtin)
