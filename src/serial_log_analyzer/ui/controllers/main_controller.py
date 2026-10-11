"""主控制器：应用级协调与生命周期。

只负责少量跨控制器协调：退出前取消进行中的分析、断开串口；界面状态恢复由窗口在
组装时按设置完成（控制器不持有 widget）。
"""

from __future__ import annotations

from PySide6.QtCore import QObject

from serial_log_analyzer.core.models.device import DeviceConnectionState
from serial_log_analyzer.ui.controllers.analysis_controller import AnalysisController
from serial_log_analyzer.ui.controllers.device_controller import DeviceController

__all__ = ["MainController"]


class MainController(QObject):
    """应用级控制器。

    参数:
        device_controller: 设备控制器。
        analysis_controller: 分析控制器。
        settings: 设置存储（供关闭时同步界面偏好）。
    """

    def __init__(
        self,
        device_controller: DeviceController,
        analysis_controller: AnalysisController,
        settings: object,
    ) -> None:
        super().__init__()
        self._device = device_controller
        self._analysis = analysis_controller
        self._settings = settings

    def shutdown(self) -> None:
        """退出前清理：取消进行中的请求并断开串口。"""

        self._analysis.cancel()
        if self._device.state is DeviceConnectionState.CONNECTED:
            self._device.disconnect()
