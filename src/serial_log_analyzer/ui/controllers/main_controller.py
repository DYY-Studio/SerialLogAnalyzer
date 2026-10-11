"""
主控制器 - 协调各子控制器与 UI 组件
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from serial_log_analyzer.core.errors import AppError

from .device_controller import DeviceController
from .analysis_controller import AnalysisController


class MainController(QObject):
    """
    主控制器 - 应用顶层协调者
    负责：
    - 持有子控制器
    - 处理跨模块交互（如选中日志传给分析模块）
    - 全局错误展示
    """

    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_controller: DeviceController | None = None
        self._analysis_controller: AnalysisController | None = None
        self._selected_sequences: list[int] = []

    # ------------------------------------------------------------------
    # 依赖注入
    # ------------------------------------------------------------------

    def set_device_controller(self, controller: DeviceController) -> None:
        self._device_controller = controller
        controller.error_occurred.connect(self._on_error)

    def set_analysis_controller(self, controller: AnalysisController) -> None:
        self._analysis_controller = controller
        controller.error_occurred.connect(self._on_error)

    # ------------------------------------------------------------------
    # UI 事件处理
    # ------------------------------------------------------------------

    def on_selection_changed(self, sequences: list[int]) -> None:
        """日志表格选中变化"""
        self._selected_sequences = sequences
        self.status_message.emit(f"已选中 {len(sequences)} 条日志")

    def on_export_clicked(self) -> None:
        """导出日志"""
        # TODO: 调用 io.storage 导出
        self.status_message.emit("导出功能待实现")

    def on_clear_clicked(self, log_model) -> None:
        """清空日志"""
        log_model.clear()
        self.status_message.emit("日志已清空")

    def on_analyze_clicked(self, mode, selector, user_input) -> None:
        """开始分析"""
        if self._analysis_controller is None:
            return

        self._analysis_controller.start_analysis(
            mode=mode,
            selector=selector,
            user_input=user_input,
            selected_sequences=self._selected_sequences,
        )

    def on_send_message(self, message: str) -> None:
        """发送追问"""
        if self._analysis_controller:
            self._analysis_controller.send_followup(message)

    def on_new_session(self, analysis_panel) -> None:
        """新会话"""
        if self._analysis_controller:
            self._analysis_controller.new_session()
            analysis_panel.clear_result()
            self.status_message.emit("已开启新会话")

    # ------------------------------------------------------------------
    # 内部处理
    # ------------------------------------------------------------------

    def _on_error(self, error: AppError) -> None:
        """全局错误展示"""
        QMessageBox.critical(None, "错误", str(error))
        self.status_message.emit(f"错误: {error}")
