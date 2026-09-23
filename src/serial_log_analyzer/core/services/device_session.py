"""设备会话：串口连接、命令通道与日志解析的编排。

职责：
- 管理连接状态机（``DISCONNECTED → CONNECTING → CONNECTED → DISCONNECTED``）；
- 把 ``SerialTransport`` 上报的字节交给行分帧器（``core.logs.line_framer``）与
  :class:`LogPipeline`；
- 区分日志行与命令响应行（``@OK`` / ``@ERR``），后者的“行”本身来自 ``core.device``
  的命令响应判定，本模块只负责分发；
- 通过回调向 UI 推送状态变化与日志增量。

本类不 import PySide6，所有通知均为普通 callable。
"""

from __future__ import annotations

from collections.abc import Callable

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.logs.pipeline import LogPipeline, PipelineUpdate
from serial_log_analyzer.core.models.device import (
    DeviceConnectionState,
    SerialConfig,
    SerialPortInfo,
)
from serial_log_analyzer.core.ports import SerialTransport

__all__ = ["DeviceSession", "DeviceSessionHandlers"]

UpdateHandler = Callable[[PipelineUpdate], None]
StateHandler = Callable[[DeviceConnectionState, str], None]
CommandReplyHandler = Callable[[str, bool], None]


class DeviceSessionHandlers:
    """设备会话对外回调集合。

    参数:
        on_update: 日志增量（批量刷新载荷）。
        on_state: 连接状态变化与人类可读说明。
        on_error: 错误通知。
        on_command_reply: 命令响应；``(文本, 是否成功)``。
    """

    def __init__(
        self,
        on_update: UpdateHandler,
        on_state: StateHandler,
        on_error: Callable[[AppError], None],
        on_command_reply: CommandReplyHandler | None = None,
    ) -> None:
        raise NotImplementedError


class DeviceSession:
    """一次设备连接的生命周期管理。

    参数:
        transport: 串口传输实现（由 ``io`` 提供）。
        pipeline: 日志流水线。
        handlers: 对外回调。
    """

    def __init__(
        self,
        transport: SerialTransport,
        pipeline: LogPipeline,
        handlers: DeviceSessionHandlers,
    ) -> None:
        raise NotImplementedError

    @property
    def state(self) -> DeviceConnectionState:
        """当前连接状态。"""

        raise NotImplementedError

    @property
    def pipeline(self) -> LogPipeline:
        """关联的日志流水线。"""

        raise NotImplementedError

    def list_ports(self) -> list[SerialPortInfo]:
        """枚举可用串口。"""

        raise NotImplementedError

    def connect(self, config: SerialConfig) -> None:
        """打开串口并开始接收日志。

        异常:
            SerialConnectionError: 打开失败。
        """

        raise NotImplementedError

    def disconnect(self) -> None:
        """关闭串口并 flush 分帧器残余内容。"""

        raise NotImplementedError

    def send_command(self, command: str) -> None:
        """向设备发送一行文本命令（自动追加换行）。

        异常:
            SerialWriteError: 写入失败。
            SerialConnectionError: 未连接。
        """

        raise NotImplementedError

    def _on_bytes(self, data: bytes) -> None:
        """串口字节到达回调：分帧 → 解析 → 分发。"""

        raise NotImplementedError

    def _on_transport_error(self, error: AppError) -> None:
        """串口错误回调：更新状态并上报。"""

        raise NotImplementedError
