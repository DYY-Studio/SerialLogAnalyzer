"""设备控制器：把 ``DeviceSession`` 的普通回调转译为 Qt Signal。

串口刷新/连接/断开/命令与清空全部委托给 core 服务；控制器只做回调转换与错误上报。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.models.device import DeviceConnectionState, SerialConfig
from serial_log_analyzer.core.services.device_session import DeviceSession, DeviceSessionHandlers

__all__ = ["DeviceController"]


class DeviceController(QObject):
    """串口设备控制器。

    信号:
        ports_refreshed(list): 串口列表刷新完成。
        connection_changed(object, str): 连接状态与说明文本。
        log_update(object): 日志增量载荷（:class:`PipelineUpdate`）。
        error_occurred(str): 错误文本，供状态栏展示。
        command_reply(object): 命令响应（:class:`CommandReply`）。
    """

    ports_refreshed = Signal(list)
    connection_changed = Signal(object, str)
    log_update = Signal(object)
    error_occurred = Signal(str)
    command_reply = Signal(object)

    def __init__(self, session: DeviceSession) -> None:
        super().__init__()
        self._session = session
        session.set_handlers(
            DeviceSessionHandlers(
                on_update=self.log_update.emit,
                on_state=self.connection_changed.emit,
                on_error=self._on_error,
                on_command_reply=self.command_reply.emit,
            )
        )

    def refresh_ports(self) -> None:
        """刷新串口列表并通过 ``ports_refreshed`` 通知界面。"""

        try:
            ports = self._session.list_ports()
        except AppError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.ports_refreshed.emit(ports)

    def connect(self, config: SerialConfig) -> None:
        """按配置连接设备；失败时状态与错误由会话回调上报。"""

        try:
            self._session.connect(config)
        except AppError as exc:
            self.error_occurred.emit(str(exc))

    def disconnect(self) -> None:
        """断开设备。"""

        try:
            self._session.disconnect()
        except AppError as exc:
            self.error_occurred.emit(str(exc))

    def send_command(self, command: str) -> None:
        """发送一行文本命令。"""

        try:
            self._session.send_command(command)
        except AppError as exc:
            self.error_occurred.emit(str(exc))

    def clear_logs(self) -> None:
        """清空日志流水线。"""

        self._session.pipeline.clear()

    @property
    def state(self) -> DeviceConnectionState:
        """当前连接状态（供界面初始化）。"""

        return self._session.state

    def _on_error(self, error: AppError) -> None:
        self.error_occurred.emit(str(error))
