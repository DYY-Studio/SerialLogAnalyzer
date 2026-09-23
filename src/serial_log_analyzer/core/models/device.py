"""设备与串口相关的领域模型。

本模块只使用项目自定义的枚举与普通 Python 类型，不包含任何 Qt 类型；
Qt 的枚举（如 ``QSerialPort.Parity``）由 ``io.serial`` 在适配时转换。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "DeviceConnectionState",
    "FlowControl",
    "Parity",
    "SerialConfig",
    "SerialPortInfo",
    "StopBits",
]


class Parity(Enum):
    """串口校验位。"""

    NONE = "none"
    EVEN = "even"
    ODD = "odd"
    SPACE = "space"
    MARK = "mark"


class StopBits(Enum):
    """串口停止位。"""

    ONE = "one"
    ONE_POINT_FIVE = "one_point_five"
    TWO = "two"


class FlowControl(Enum):
    """串口流控方式。"""

    NONE = "none"
    HARDWARE = "hardware"
    SOFTWARE = "software"


class DeviceConnectionState(Enum):
    """设备连接状态机取值。"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True)
class SerialConfig:
    """一次串口连接所需的完整参数。

    参数:
        port: 串口设备名，例如 ``/dev/cu.usbserial-0001`` 或 ``COM3``。
        baudrate: 波特率，Hi3861 常用 ``115200``。
        data_bits: 数据位，通常为 8。
        parity: 校验位。
        stop_bits: 停止位。
        flow_control: 流控方式。
    """

    port: str
    baudrate: int = 115200
    data_bits: int = 8
    parity: Parity = Parity.NONE
    stop_bits: StopBits = StopBits.ONE
    flow_control: FlowControl = FlowControl.NONE


@dataclass(frozen=True)
class SerialPortInfo:
    """系统枚举到的串口设备描述信息。"""

    name: str
    description: str = ""
    manufacturer: str = ""
    serial_number: str = ""
