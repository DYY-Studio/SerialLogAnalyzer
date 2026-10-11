"""
主窗口 - 应用顶层界面
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QStatusBar,
    QMessageBox,
)

from .widgets.serial_toolbar import SerialToolbar
from .widgets.log_view import LogView
from .widgets.analysis_panel import AnalysisPanel
from .models.log_table_model import LogTableModel
from .models.log_filter_model import LogFilterModel
from .controllers.main_controller import MainController
from .controllers.device_controller import DeviceController
from .controllers.analysis_controller import AnalysisController


class MainWindow(QMainWindow):
    """
    主窗口
    
    布局：
    - 顶部：串口工具栏
    - 中间：左右分割（日志表格 | 分析面板）
    - 底部：状态栏
    """

    def __init__(
        self,
        device_controller: DeviceController,
        analysis_controller: AnalysisController,
        parent=None,
    ):
        super().__init__(parent)
        self._device_controller = device_controller
        self._analysis_controller = analysis_controller

        self.setWindowTitle("SerialLogAnalyzer - 串口日志分析工具")
        self.resize(1200, 800)

        self._setup_ui()
        self._setup_models()
        self._setup_controllers()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """构建界面"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部工具栏
        self.toolbar = SerialToolbar()
        main_layout.addWidget(self.toolbar)

        # 中间分割区域
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：日志视图
        self.log_view = LogView()
        splitter.addWidget(self.log_view)

        # 右侧：分析面板
        self.analysis_panel = AnalysisPanel()
        splitter.addWidget(self.analysis_panel)

        # 设置分割比例（左:右 = 7:3）
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([800, 400])

        main_layout.addWidget(splitter)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _setup_models(self) -> None:
        """创建数据模型"""
        self.log_table_model = LogTableModel()
        self.log_filter_model = LogFilterModel()
        self.log_view.set_models(self.log_table_model, self.log_filter_model)

    def _setup_controllers(self) -> None:
        """创建主控制器并注入依赖"""
        self.main_controller = MainController()
        self.main_controller.set_device_controller(self._device_controller)
        self.main_controller.set_analysis_controller(self._analysis_controller)
        self.main_controller.status_message.connect(self.status_bar.showMessage)

    def _connect_signals(self) -> None:
        """连接所有信号"""
        # 工具栏信号
        self.toolbar.connect_clicked.connect(self._device_controller.connect)
        self.toolbar.disconnect_clicked.connect(self._device_controller.disconnect)
        self.toolbar.refresh_clicked.connect(self._device_controller.refresh_ports)
        self.toolbar.send_command_clicked.connect(self._device_controller.send_command)

        # 设备控制器信号
        self._device_controller.ports_updated.connect(self.toolbar.update_ports)
        self._device_controller.connection_state_changed.connect(self.toolbar.set_state)
        self._device_controller.log_entries_received.connect(self._on_logs_received)
        self._device_controller.log_entry_updated.connect(self.log_table_model.update_entry)
        self._device_controller.log_entries_removed.connect(self.log_table_model.remove_entries)

        # 日志视图信号
        self.log_view.selection_changed.connect(self.main_controller.on_selection_changed)
        self.log_view.export_requested.connect(self.main_controller.on_export_clicked)
        self.log_view.clear_requested.connect(
            lambda: self.main_controller.on_clear_clicked(self.log_table_model)
        )

        # 分析面板信号
        self.analysis_panel.analyze_clicked.connect(self.main_controller.on_analyze_clicked)
        self.analysis_panel.send_message_clicked.connect(self.main_controller.on_send_message)
        self.analysis_panel.new_session_clicked.connect(
            lambda: self.main_controller.on_new_session(self.analysis_panel)
        )

        # 分析控制器信号
        self._analysis_controller.stream_chunk_received.connect(
            self.analysis_panel.append_stream_chunk
        )
        self._analysis_controller.analysis_state_changed.connect(
            self.analysis_panel.set_state
        )

        # 表格行数变化更新状态栏
        self.log_table_model.row_count_changed.connect(self._on_row_count_changed)

    # ------------------------------------------------------------------
    # 内部槽函数
    # ------------------------------------------------------------------

    def _on_logs_received(self, entries: list) -> None:
        """接收到新日志"""
        added = self.log_table_model.add_entries(entries)
        # 自动滚动到底部
        self.log_view.scroll_to_bottom()

    def _on_row_count_changed(self, count: int) -> None:
        """更新状态栏的日志计数"""
        self.status_bar.showMessage(f"共 {count} 条日志")
