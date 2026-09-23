"""设备控制器：串口刷新 / 连接 / 断开与日志批量刷新。

把 :class:`DeviceSessionHandlers` 的普通回调转译为 Qt Signal，供界面订阅；
连接动作与串口配置来自工具栏，业务实现全部委托给 core。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

__all__ = ["DeviceController"]


class DeviceController(QObject):
    """串口设备控制器。

    信号:
        ports_refreshed: 串口列表刷新完成，携带 ``list[SerialPortInfo]``。
        connection_changed: 连接状态变化，携带状态与说明文本。
        log_update: 日志增量载荷，携带 :class:`PipelineUpdate`。
        error_occurred: 错误文本，供状态栏展示。
        command_reply: 命令响应文本与是否成功。
    """

    ports_refreshed = Signal(list)
    connection_changed = Signal(object, str)
    log_update = Signal(object)
    error_occurred = Signal(str)
    command_reply = Signal(str, bool)

    def __init__(self, session: object) -> None:
        """参数: session — :class:`core.services.device_session.DeviceSession`。"""

        super().__init__()
        raise NotImplementedError

    def refresh_ports(self) -> None:
        """刷新串口列表并通过 ``ports_refreshed`` 通知界面。"""

        raise NotImplementedError

    def connect(self, config: object) -> None:
        """按配置连接设备。"""

        raise NotImplementedError

    def disconnect(self) -> None:
        """断开设备。"""

        raise NotImplementedError

    def send_command(self, command: str) -> None:
        """发送一行文本命令。"""

        raise NotImplementedError

    def clear_logs(self) -> None:
        """清空日志流水线。"""

        raise NotImplementedError
