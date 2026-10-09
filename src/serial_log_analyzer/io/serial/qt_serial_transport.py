"""基于 ``QSerialPort`` 的串口传输实现。

实现 :class:`serial_log_analyzer.core.ports.SerialTransport`：

- 数据到达：``QSerialPort.readyRead`` → ``readAll()`` → 以 ``bytes`` 上报；
- 错误处理：``QSerialPort.errorOccurred`` → 翻译为 core 异常后上报；
- 枚举串口：``QSerialPortInfo.availablePorts()`` → ``SerialPortInfo``；
- 项目自定义枚举与 Qt 枚举的相互转换集中在本模块，Qt 类型不外泄。

本类不解析日志语义，只搬运字节。
"""

from __future__ import annotations

from PySide6.QtCore import QIODevice, QObject
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from serial_log_analyzer.core.errors import SerialConnectionError, SerialWriteError
from serial_log_analyzer.core.models.device import (
    FlowControl,
    Parity,
    SerialConfig,
    SerialPortInfo,
    StopBits,
)
from serial_log_analyzer.core.ports import BytesHandler, ErrorHandler

__all__ = ["QtSerialTransport"]

_PARITY = {
    Parity.NONE: QSerialPort.Parity.NoParity,
    Parity.EVEN: QSerialPort.Parity.EvenParity,
    Parity.ODD: QSerialPort.Parity.OddParity,
    Parity.SPACE: QSerialPort.Parity.SpaceParity,
    Parity.MARK: QSerialPort.Parity.MarkParity,
}
_STOP_BITS = {
    StopBits.ONE: QSerialPort.StopBits.OneStop,
    StopBits.ONE_POINT_FIVE: QSerialPort.StopBits.OneAndHalfStop,
    StopBits.TWO: QSerialPort.StopBits.TwoStop,
}
_FLOW_CONTROL = {
    FlowControl.NONE: QSerialPort.FlowControl.NoFlowControl,
    FlowControl.HARDWARE: QSerialPort.FlowControl.HardwareControl,
    FlowControl.SOFTWARE: QSerialPort.FlowControl.SoftwareControl,
}
_DATA_BITS = {
    5: QSerialPort.DataBits.Data5,
    6: QSerialPort.DataBits.Data6,
    7: QSerialPort.DataBits.Data7,
    8: QSerialPort.DataBits.Data8,
}


class QtSerialTransport:
    """``SerialTransport`` 的 Qt 实现。

    参数:
        parent: 可选的 ``QObject`` 父对象，用于生命周期管理。
    """

    def __init__(self, parent: object | None = None) -> None:
        self._port = QSerialPort(parent if isinstance(parent, QObject) else None)
        self._on_bytes: BytesHandler | None = None
        self._on_error: ErrorHandler | None = None
        self._port.readyRead.connect(self._handle_ready_read)
        self._port.errorOccurred.connect(self._handle_error)

    def set_handlers(self, on_bytes: BytesHandler, on_error: ErrorHandler) -> None:
        """注册数据与错误回调（须在 ``open`` 之前调用）。"""

        self._on_bytes = on_bytes
        self._on_error = on_error

    def list_ports(self) -> list[SerialPortInfo]:
        """枚举系统可用串口。"""

        return [
            SerialPortInfo(
                name=info.portName(),
                description=info.description(),
                manufacturer=info.manufacturer(),
                serial_number=info.serialNumber(),
            )
            for info in QSerialPortInfo.availablePorts()
        ]

    def open(self, config: SerialConfig) -> None:
        """配置并打开串口。

        异常:
            SerialConnectionError: 端口不存在、被占用或参数不被支持。
        """

        if self._port.isOpen():
            self._port.close()
        self._port.setPortName(config.port)
        self._port.setBaudRate(config.baudrate)
        self._port.setDataBits(_DATA_BITS.get(config.data_bits, QSerialPort.DataBits.Data8))
        self._port.setParity(_PARITY.get(config.parity, QSerialPort.Parity.NoParity))
        self._port.setStopBits(_STOP_BITS.get(config.stop_bits, QSerialPort.StopBits.OneStop))
        self._port.setFlowControl(
            _FLOW_CONTROL.get(config.flow_control, QSerialPort.FlowControl.NoFlowControl)
        )
        if not self._port.open(QIODevice.OpenModeFlag.ReadWrite):
            raise SerialConnectionError(
                f"无法打开串口 {config.port}：{self._port.errorString()}"
            )

    def close(self) -> None:
        """关闭串口。"""

        if self._port.isOpen():
            self._port.close()

    def write(self, data: bytes) -> None:
        """写入原始字节。

        异常:
            SerialWriteError: 未打开或写入失败。
        """

        if not self._port.isOpen():
            raise SerialWriteError("串口未打开，无法写入")
        if self._port.write(data) < 0:
            raise SerialWriteError(f"写入串口失败：{self._port.errorString()}")

    @property
    def is_open(self) -> bool:
        """串口当前是否已打开。"""

        return self._port.isOpen()

    def _handle_ready_read(self) -> None:
        """``readyRead`` 回调：读取并上报字节。"""

        data = bytes(self._port.readAll())
        if data and self._on_bytes is not None:
            self._on_bytes(data)

    def _handle_error(self, error: QSerialPort.SerialPortError) -> None:
        """``errorOccurred`` 回调：翻译为 core 异常后上报。"""

        if error == QSerialPort.SerialPortError.NoError or self._on_error is None:
            return
        self._on_error(SerialConnectionError(f"串口错误：{self._port.errorString()}"))
