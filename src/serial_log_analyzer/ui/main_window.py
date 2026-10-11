"""主窗口：只负责布局、菜单、工具栏与状态栏。

不持有业务状态、不解析日志、不发 LLM 请求；所有动作委托给控制器，
退出清理通过构造时注入的回调执行。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QMenu,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.ui.widgets.analysis_panel import AnalysisPanel
from serial_log_analyzer.ui.widgets.log_view import LogView
from serial_log_analyzer.ui.widgets.serial_toolbar import SerialToolBar

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """应用主窗口。

    参数:
        log_view: 中部日志视图。
        analysis_panel: 右侧分析面板。
        serial_toolbar: 顶部串口工具栏。
        parent: 可选父窗口。
        on_close: 关闭前的清理回调（由组合根注入，例如断开设备、取消请求）。

    信号（由组合根连接，窗口不自己构造对话框）:
        export_requested(): 请求导出内存日志。
        import_requested(): 请求导入历史日志。
        clear_requested(): 请求清空日志。
        settings_requested(): 请求打开设置对话框。
        provider_requested(): 请求打开模型服务对话框。
        credential_requested(): 请求打开凭据对话框。
        preset_requested(): 请求切换日志 Preset。
    """

    export_requested = Signal()
    import_requested = Signal()
    clear_requested = Signal()
    settings_requested = Signal()
    provider_requested = Signal()
    credential_requested = Signal()
    preset_requested = Signal()

    def __init__(
        self,
        log_view: LogView,
        analysis_panel: AnalysisPanel,
        serial_toolbar: SerialToolBar,
        parent: QMainWindow | None = None,
        *,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_close = on_close
        self.log_view = log_view
        self.analysis_panel = analysis_panel
        self.serial_toolbar = serial_toolbar
        self.setWindowTitle("SerialLogAnalyzer - 串口日志分析工具")
        self.resize(1200, 800)
        self.addToolBar(serial_toolbar)
        self._build_menu()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(log_view)
        self.splitter.addWidget(analysis_panel)
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([840, 360])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter)
        self.setCentralWidget(central)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def show_status(self, message: str) -> None:
        """在状态栏显示一条消息。"""

        self.status_bar.showMessage(message)

    def _build_menu(self) -> None:
        """构建菜单栏：只发射意图信号，动作由组合根接。

        「文件」管日志的导入 / 导出 / 清空，「配置」管设置、Profile 与日志 Preset。
        """

        def _add(menu: QMenu, title: str, signal: Signal) -> None:
            action = QAction(title, self)
            action.triggered.connect(signal.emit)
            menu.addAction(action)

        file_menu = self.menuBar().addMenu("文件")
        _add(file_menu, "导出日志…", self.export_requested)
        _add(file_menu, "导入日志…", self.import_requested)
        file_menu.addSeparator()
        _add(file_menu, "清空日志", self.clear_requested)

        config_menu = self.menuBar().addMenu("配置")
        _add(config_menu, "设置…", self.settings_requested)
        _add(config_menu, "模型服务…", self.provider_requested)
        _add(config_menu, "凭据…", self.credential_requested)
        _add(config_menu, "切换日志 Preset…", self.preset_requested)

    def closeEvent(self, event: object) -> None:
        """窗口关闭：执行清理回调。"""

        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)
