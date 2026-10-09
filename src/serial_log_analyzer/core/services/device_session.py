"""设备会话：串口连接、命令通道与日志解析的编排。

职责：
- 管理连接状态机（``DISCONNECTED → CONNECTING → CONNECTED → DISCONNECTED``）；
- 把 ``SerialTransport`` 上报的字节交给行分帧器（``core.logs.line_framer``）与
  :class:`LogPipeline`；
- 区分日志行与命令响应行（``@OK`` / ``@ERR``），后者的判定来自 ``core.device``
  的命令响应协议，本模块只负责分发；
- 通过回调向 UI 推送状态变化与日志增量。

本类不 import PySide6，所有通知均为普通 callable。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from serial_log_analyzer.core.device import command as device_command
from serial_log_analyzer.core.errors import AppError, SerialConnectionError
from serial_log_analyzer.core.logs.line_framer import LineFramer
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
        self.on_update = on_update
        self.on_state = on_state
        self.on_error = on_error
        self.on_command_reply = on_command_reply


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
        self._transport = transport
        self._pipeline = pipeline
        self._handlers = handlers
        self._framer = LineFramer()
        self._state = DeviceConnectionState.DISCONNECTED

    @property
    def state(self) -> DeviceConnectionState:
        """当前连接状态。"""

        return self._state

    @property
    def pipeline(self) -> LogPipeline:
        """关联的日志流水线。"""

        return self._pipeline

    def list_ports(self) -> list[SerialPortInfo]:
        """枚举可用串口。"""

        return self._transport.list_ports()

    def connect(self, config: SerialConfig) -> None:
        """打开串口并开始接收日志。

        异常:
            SerialConnectionError: 打开失败。
        """

        self._set_state(DeviceConnectionState.CONNECTING, f"正在连接 {config.port}")
        try:
            self._transport.set_handlers(self._on_bytes, self._on_transport_error)
            self._transport.open(config)
        except SerialConnectionError as exc:
            self._set_state(DeviceConnectionState.ERROR, str(exc))
            raise
        self._framer.reset()
        self._set_state(DeviceConnectionState.CONNECTED, f"已连接 {config.port}")

    def disconnect(self) -> None:
        """关闭串口并 flush 分帧器残余内容。"""

        self._transport.close()
        residual = self._framer.finalize()
        if residual is not None:
            self._handle_line(residual)
        self._set_state(DeviceConnectionState.DISCONNECTED, "已断开")

    def send_command(self, command: str) -> None:
        """向设备发送一行文本命令（自动追加换行）。

        异常:
            SerialWriteError: 写入失败。
            SerialConnectionError: 未连接。
        """

        if self._state is not DeviceConnectionState.CONNECTED:
            raise SerialConnectionError("未连接设备，无法发送命令")
        self._transport.write((command + "\r\n").encode())

    def _on_bytes(self, data: bytes) -> None:
        """串口字节到达回调：分帧 → 解析 → 分发。"""

        for line in self._framer.feed(data):
            self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        """把一整行分派到命令回复或日志流水线。"""

        if device_command.is_response_line(line):
            reply = device_command.parse_response(line)
            if self._handlers.on_command_reply is not None:
                self._handlers.on_command_reply(reply.text, reply.ok)
            return
        self._handlers.on_update(self._pipeline.feed(line, time.time()))

    def _on_transport_error(self, error: AppError) -> None:
        """串口错误回调：更新状态并上报。"""

        self._set_state(DeviceConnectionState.ERROR, str(error))
        self._handlers.on_error(error)

    def _set_state(self, state: DeviceConnectionState, message: str) -> None:
        """更新状态并通知。"""

        self._state = state
        self._handlers.on_state(state, message)
