"""串口发现与筛选辅助。

在 :class:`QtSerialPortInfo` 之上提供“按名称查找”“生成展示文本”等 UI 常用能力，
避免这些细节散落到 ``ui`` 层。
"""

from __future__ import annotations

from serial_log_analyzer.core.models.device import SerialPortInfo

__all__ = ["describe_port", "find_port", "friendly_priority"]


def describe_port(info: SerialPortInfo) -> str:
    """生成下拉框展示文本，例如 ``/dev/cu.usbserial-0001 — USB Serial``。"""

    raise NotImplementedError


def find_port(ports: list[SerialPortInfo], name: str) -> SerialPortInfo | None:
    """按设备名查找串口；不存在时返回 ``None``。"""

    raise NotImplementedError


def friendly_priority(info: SerialPortInfo) -> int:
    """给串口排序的优先级：真实 USB 串口优先于系统内置调试口。"""

    raise NotImplementedError
