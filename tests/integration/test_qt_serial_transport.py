"""QtSerialTransport 集成测试（需 Qt）。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import SerialConnectionError
from serial_log_analyzer.core.models.device import SerialConfig, SerialPortInfo
from serial_log_analyzer.io.serial.qt_serial_transport import QtSerialTransport


def test_list_ports_returns_core_types(qtbot) -> None:
    ports = QtSerialTransport().list_ports()
    assert isinstance(ports, list)
    assert all(isinstance(port, SerialPortInfo) for port in ports)


def test_open_bogus_port_raises_serial_connection_error(qtbot) -> None:
    with pytest.raises(SerialConnectionError):
        QtSerialTransport().open(SerialConfig(port="__no_such_port__"))
