"""主窗口：只负责布局、菜单、工具栏与状态栏。

不持有业务状态、不解析日志、不发 LLM 请求；所有动作委托给控制器，
退出清理通过构造时注入的回调执行。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QStatusBar,
    QToolButton,
    QWidget,
)

from serial_log_analyzer.ui.icons import render_icon
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens
from serial_log_analyzer.ui.widgets.analysis_panel import AnalysisPanel
from serial_log_analyzer.ui.widgets.app_log_panel import AppLogPanel
from serial_log_analyzer.ui.widgets.command_panel import CommandPanel
from serial_log_analyzer.ui.widgets.log_view import LogView
from serial_log_analyzer.ui.widgets.serial_toolbar import SerialToolBar

__all__ = ["MainWindow"]


class _DockTitleBar(QWidget):
    """紧凑扁平的 Dock 标题栏：左对齐标题 + 图标化浮动与隐藏按钮。"""

    def __init__(self, title: str, dock: QDockWidget) -> None:
        super().__init__(dock)
        self.setObjectName("dock-title-bar")
        self.setFixedHeight(26)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 6, 2)
        layout.setSpacing(4)

        label = QLabel(title)
        label.setObjectName("dock-title-label")
        layout.addWidget(label)
        layout.addStretch()

        self.float_btn = QToolButton()
        self.float_btn.setToolTip("浮动 / 停靠")
        self.float_btn.setIconSize(QSize(12, 12))
        self.float_btn.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        layout.addWidget(self.float_btn)

        self.close_btn = QToolButton()
        self.close_btn.setToolTip("隐藏面板")
        self.close_btn.setIconSize(QSize(12, 12))
        self.close_btn.clicked.connect(dock.close)
        layout.addWidget(self.close_btn)

    def refresh_icons(self, tokens: ThemeTokens) -> None:
        """按主题色刷新浮动与关闭按钮图标。"""

        self.float_btn.setIcon(render_icon("dock-float", tokens.text_secondary, size=12))
        self.close_btn.setIcon(render_icon("disconnect", tokens.text_secondary, size=12))


class MainWindow(QMainWindow):
    """应用主窗口。

    参数:
        log_view: 中部日志视图。
        analysis_panel: 右侧分析面板。
        serial_toolbar: 顶部串口工具栏。
        command_panel: 底部命令面板（输入 + 回复历史）。
        app_log_panel: 底部应用日志面板（与命令面板同区，切换标签页）。
        parent: 可选父窗口。
        on_close: 关闭前的清理回调（由组合根注入，例如断开设备、取消请求）。

    布局：中央是日志表格，「LLM 分析」停靠在右侧、「命令」与「应用日志」停靠在底部
    （同一区域的两个标签页），都可拖动 / 浮动 / 关闭，「视图」菜单控制显隐。
    布局通过 ``saveState`` / :meth:`restore_layout` 记忆，但只在面板集合没变时恢复
    （见 ``bootstrap._restore_layout``）。

    信号（由组合根连接，窗口不自己构造对话框）:
        export_requested(): 请求导出内存日志。
        import_requested(): 请求导入历史日志。
        clear_requested(): 请求清空日志。
        settings_requested(): 请求打开设置对话框。
        provider_requested(): 请求打开模型服务对话框。
        preset_requested(): 请求切换日志 Preset。
    """

    export_requested = Signal()
    import_requested = Signal()
    clear_requested = Signal()
    settings_requested = Signal()
    provider_requested = Signal()
    preset_requested = Signal()

    def __init__(
        self,
        log_view: LogView,
        analysis_panel: AnalysisPanel,
        serial_toolbar: SerialToolBar,
        command_panel: CommandPanel,
        app_log_panel: AppLogPanel,
        parent: QMainWindow | None = None,
        *,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_close = on_close
        self._tokens = default_tokens()
        self._dock_titles: list[_DockTitleBar] = []
        self.log_view = log_view
        self.analysis_panel = analysis_panel
        self.serial_toolbar = serial_toolbar
        self.command_panel = command_panel
        self.app_log_panel = app_log_panel
        self.setWindowTitle("SerialLogAnalyzer - 串口日志分析工具")
        self.resize(1200, 800)
        self.addToolBar(serial_toolbar)
        self.analysis_dock = self._make_dock(
            "analysis-dock", "LLM 分析", analysis_panel, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.command_dock = self._make_dock(
            "command-dock", "命令", command_panel, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.app_log_dock = self._make_dock(
            "app-log-dock", "应用日志", app_log_panel, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        # 与应用日志共用底部区域，用标签页切换，避免再占一块高度。
        self.tabifyDockWidget(self.command_dock, self.app_log_dock)
        self.command_dock.raise_()
        self._apply_dock_corners()
        self._build_menu()
        self.setCentralWidget(log_view)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.connection_status_label = self._make_status_pill("status-connection", "○ 未连接")
        self.preset_status_label = self._make_status_pill("status-preset", "Preset: -")
        self.usage_status_label = self._make_status_pill("status-usage", "")
        self.usage_status_label.setVisible(False)
        self.log_count_label = self._make_status_pill("status-log-count", "日志 0 条")
        self.status_bar.addPermanentWidget(self.connection_status_label)
        self.status_bar.addPermanentWidget(self.preset_status_label)
        self.status_bar.addPermanentWidget(self.usage_status_label)
        self.status_bar.addPermanentWidget(self.log_count_label)
        self.set_theme_tokens(self._tokens)

    @staticmethod
    def _make_status_pill(object_name: str, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setProperty("role", "status-pill")
        return label

    def set_theme_tokens(self, tokens: ThemeTokens) -> None:
        """将新主题 Token 同步到停靠栏标题图标、工具栏、日志视图与各功能面板。"""

        self._tokens = tokens
        for bar in self._dock_titles:
            bar.refresh_icons(tokens)
        self.serial_toolbar.set_theme_tokens(tokens)
        self.log_view.set_theme_tokens(tokens)
        self.analysis_panel.set_theme_tokens(tokens)
        self.command_panel.set_theme_tokens(tokens)
        self.app_log_panel.set_theme_tokens(tokens)

    def set_connection_status(self, connected: bool, detail: str = "") -> None:
        """更新状态栏右侧的串口连接状态胶囊。"""

        if not connected:
            self.connection_status_label.setText("○ 未连接")
            return
        self.connection_status_label.setText(f"● {detail}" if detail else "● 已连接")

    def set_preset_name(self, preset_id: str) -> None:
        """更新状态栏右侧的当前日志 Preset 标识。"""

        self.preset_status_label.setText(f"Preset: {preset_id or '-'}")

    def show_status(self, message: str) -> None:
        """在状态栏显示一条消息。"""

        self.status_bar.showMessage(message)

    def set_log_count(self, count: int) -> None:
        """更新状态栏右侧的日志条数指示。"""

        self.log_count_label.setText(f"日志 {count} 条")

    def set_usage_summary(self, input_tokens: int, output_tokens: int, total_tokens: int) -> None:
        """更新状态栏右侧的 LLM Token 用量摘要。"""

        self.usage_status_label.setText(
            f"Token: {input_tokens} / {output_tokens} / {total_tokens}"
        )
        self.usage_status_label.setVisible(True)

    def clear_usage_summary(self) -> None:
        """清空状态栏右侧的 LLM Token 用量摘要。"""

        self.usage_status_label.clear()
        self.usage_status_label.setVisible(False)

    def restore_layout(self, state: object) -> None:
        """恢复工具栏 / 停靠布局。

        右下角归属是固定策略而不是用户状态，而 ``restoreState`` 会把它一起带回来，
        因此恢复之后必须重新声明，否则分析面板不再贯通上下。
        """

        self.restoreState(state)
        self._apply_dock_corners()

    def dock_names(self) -> list[str]:
        """当前停靠面板的标识集合（供布局存档判断面板是否增减过）。"""

        return sorted(dock.objectName() for dock in self.findChildren(QDockWidget))

    def _apply_dock_corners(self) -> None:
        """右下角交给右侧停靠区：分析面板贯通上下，命令面板只占左下。"""

        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)

    def _make_dock(
        self, name: str, title: str, widget: QWidget, area: Qt.DockWidgetArea
    ) -> QDockWidget:
        """把组件包成可拖动 / 可浮动 / 可关闭的停靠面板。"""

        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        title_bar = _DockTitleBar(title, dock)
        dock.setTitleBarWidget(title_bar)
        self._dock_titles.append(title_bar)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(area, dock)
        return dock

    def _build_menu(self) -> None:
        """构建菜单栏：只发射意图信号，动作由组合根接。

        「文件」管日志的导入 / 导出 / 清空，「配置」管设置、Profile 与日志 Preset，
        「视图」管停靠面板的显隐（面板被关掉后必须能从这里找回来）。
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
        _add(config_menu, "切换日志 Preset…", self.preset_requested)

        view_menu = self.menuBar().addMenu("视图")
        view_menu.addAction(self.analysis_dock.toggleViewAction())
        view_menu.addAction(self.command_dock.toggleViewAction())
        view_menu.addAction(self.app_log_dock.toggleViewAction())

    def closeEvent(self, event: object) -> None:
        """窗口关闭：执行清理回调。"""

        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)
