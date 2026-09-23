"""基于 ``QSerialPort`` 的串口传输实现。

实现 :class:`serial_log_analyzer.core.ports.SerialTransport`：

- 数据到达：``QSerialPort.readyRead`` → ``readAll()`` → 以 ``bytes`` 上报；
- 错误处理：``QSerialPort.errorOccurred`` → 翻译为 core 异常后上报；
- 枚举串口：``QSerialPortInfo.availablePorts()`` → ``SerialPortInfo``；
- 项目自定义枚举与 Qt 枚举的相互转换集中在本模块，Qt 类型不外泄。

本类不解析日志语义，只搬运字节。
"""

from __future__ import annotations

from serial_log_analyzer.core.models.device import SerialConfig, SerialPortInfo
from serial_log_analyzer.core.ports import BytesHandler, ErrorHandler

__all__ = ["QtSerialTransport"]


class QtSerialTransport:
    """``SerialTransport`` 的 Qt 实现。

    参数:
        parent: 可选的 ``QObject`` 父对象，用于生命周期管理。
    """

    def __init__(self, parent: object | None = None) -> None:
        raise NotImplementedError

    def set_handlers(self, on_bytes: BytesHandler, on_error: ErrorHandler) -> None:
        """注册数据与错误回调（须在 ``open`` 之前调用）。"""

        raise NotImplementedError

    def list_ports(self) -> list[SerialPortInfo]:
        """枚举系统可用串口。"""

        raise NotImplementedError

    def open(self, config: SerialConfig) -> None:
        """配置并打开串口。

        异常:
            SerialConnectionError: 端口不存在、被占用或参数不被支持。
        """

        raise NotImplementedError

    def close(self) -> None:
        """关闭串口。"""

        raise NotImplementedError

    def write(self, data: bytes) -> None:
        """写入原始字节。

        异常:
            SerialWriteError: 未打开或写入失败。
        """

        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        """串口当前是否已打开。"""

        raise NotImplementedError
