"""主控制器：应用级协调与生命周期。

只负责少量跨控制器协调：
- 应用退出时的清理（断开设备、保存设置、取消进行中的请求）；
- 设备断开后的界面状态恢复。

不设计万能 ``ApplicationManager``，具体业务逻辑仍在各控制器与 core 服务中。
"""

from __future__ import annotations

from PySide6.QtCore import QObject

__all__ = ["MainController"]


class MainController(QObject):
    """应用级控制器。

    参数:
        device_controller: 设备控制器。
        analysis_controller: 分析控制器。
        settings: 设置存储。
    """

    def __init__(
        self,
        device_controller: object,
        analysis_controller: object,
        settings: object,
    ) -> None:
        super().__init__()
        raise NotImplementedError

    def shutdown(self) -> None:
        """退出前清理：断开串口、取消请求、同步设置。"""

        raise NotImplementedError

    def restore_session(self) -> None:
        """按上次设置恢复界面状态（串口选择、波特率、当前 Profile）。"""

        raise NotImplementedError
