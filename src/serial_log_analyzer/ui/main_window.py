"""主窗口：布局、菜单、工具栏与状态栏。

保持轻量：不持有业务状态、不解析日志、不发 LLM 请求；所有动作委托给控制器。
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """应用主窗口。

    参数:
        log_view: 中部日志视图。
        analysis_panel: 右侧分析面板。
        serial_toolbar: 顶部串口工具栏。
        parent: 可选父窗口。
    """

    def __init__(
        self,
        log_view: object,
        analysis_panel: object,
        serial_toolbar: object,
        parent: QMainWindow | None = None,
    ) -> None:
        super().__init__(parent)
        self._log_view = log_view
        self._analysis_panel = analysis_panel
        self._serial_toolbar = serial_toolbar

    def closeEvent(self, event: object) -> None:
        """窗口关闭：交由主控制器执行保存设置与断开设备等清理。"""

        raise NotImplementedError
