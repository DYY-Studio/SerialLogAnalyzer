"""
日志视图组件 - 日志表格 + 过滤栏
"""

from __future__ import annotations

from typing import Set, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableView,
    QHeaderView,
    QCheckBox,
    QLabel,
)

from serial_log_analyzer.core.models.logs import LogLevel

from ..models.log_table_model import LogTableModel
from ..models.log_filter_model import LogFilterModel


class LogView(QWidget):
    """
    日志视图组件
    
    信号：
    - selection_changed(sequences: list)
    - export_requested()
    - clear_requested()
    """

    selection_changed = Signal(list)
    export_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        # 过滤栏
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)

        filter_layout.addWidget(QLabel("过滤:"))

        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("输入关键字过滤...")
        self.text_filter.setMaximumWidth(220)
        self.text_filter.setFixedHeight(30)
        filter_layout.addWidget(self.text_filter)

        # 级别复选框
        for level in [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR]:
            cb = QCheckBox(level.name)
            cb.setChecked(True)
            cb.setProperty("level", level)
            filter_layout.addWidget(cb)

        filter_layout.addStretch()

        self.export_btn = QPushButton("导出")
        self.export_btn.setFixedHeight(30)
        self.export_btn.clicked.connect(self.export_requested.emit)
        filter_layout.addWidget(self.export_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        filter_layout.addWidget(self.clear_btn)

        layout.addLayout(filter_layout)

        # 日志表格
        self.table_view = QTableView()
        self.table_view.setEditTriggers(QTableView.NoEditTriggers)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSelectionMode(QTableView.ExtendedSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.setWordWrap(False)
        self.table_view.setShowGrid(False)

        layout.addWidget(self.table_view, stretch=1)

    def _connect_signals(self) -> None:
        self.text_filter.textChanged.connect(self._on_text_filter_changed)

        # 级别复选框
        from PySide6.QtWidgets import QLayout
        for i in range(self.layout().itemAt(0).count()):
            item = self.layout().itemAt(0).itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QCheckBox):
                item.widget().toggled.connect(self._on_level_filter_changed)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def set_models(self, table_model: LogTableModel, filter_model: LogFilterModel) -> None:
        """设置数据模型"""
        self._table_model = table_model
        self._filter_model = filter_model
        self.table_view.setModel(filter_model)
        filter_model.setSourceModel(table_model)

        # model 设置后再连接 selection 信号
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # 设置列宽
        self.table_view.setColumnWidth(0, 60)   # #
        self.table_view.setColumnWidth(1, 100)  # 时间
        self.table_view.setColumnWidth(2, 70)   # 级别
        self.table_view.setColumnWidth(3, 120)  # 模块

    def selected_sequences(self) -> List[int]:
        """获取选中行的日志序列号"""
        rows = self.table_view.selectionModel().selectedRows()
        sequences = []
        for index in rows:
            source_index = self._filter_model.mapToSource(index)
            entry = self._table_model.entry_at(source_index.row())
            if entry:
                sequences.append(entry.sequence)
        return sequences

    def scroll_to_bottom(self) -> None:
        """滚动到底部"""
        self.table_view.scrollToBottom()

    # ------------------------------------------------------------------
    # 内部槽函数
    # ------------------------------------------------------------------

    def _on_text_filter_changed(self, text: str) -> None:
        self._filter_model.set_text_filter(text)

    def _on_level_filter_changed(self) -> None:
        allowed = set()
        from PySide6.QtWidgets import QLayout
        filter_layout = self.layout().itemAt(0)
        for i in range(filter_layout.count()):
            item = filter_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QCheckBox):
                cb = item.widget()
                if cb.isChecked():
                    allowed.add(cb.property("level"))

        # 如果全部选中，设置为 None（不过滤）
        if len(allowed) == len([LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR]):
            self._filter_model.set_allowed_levels(None)
        else:
            self._filter_model.set_allowed_levels(allowed)

    def _on_selection_changed(self) -> None:
        seqs = self.selected_sequences()
        self.selection_changed.emit(seqs)
