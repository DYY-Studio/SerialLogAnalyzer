"""串口工具栏：端口选择、波特率、刷新、连接与清空。

只发射用户意图信号，不直接操作串口对象；实际动作由 :class:`DeviceController` 执行。
"""

from __future__ import annotations

from PySide6.QtWidgets import QToolBar

__all__ = ["SerialToolBar"]


class SerialToolBar(QToolBar):
    """顶部串口操作工具栏。

    信号（由控制器连接）:
        connect_requested(SerialConfig): 请求连接。
        disconnect_requested(): 请求断开。
        refresh_requested(): 请求刷新串口列表。
        clear_requested(): 请求清空日志。
        filter_changed(): 过滤条件变化。
    """

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def set_ports(self, ports: list[object]) -> None:
        """填充串口下拉列表，尽量保留当前选择。"""

        raise NotImplementedError

    def set_connected(self, connected: bool) -> None:
        """根据连接状态切换“连接 / 断开”按钮与控件可用性。"""

        raise NotImplementedError

    def current_config(self) -> object:
        """按当前界面选择构造 :class:`SerialConfig`。"""

        raise NotImplementedError
