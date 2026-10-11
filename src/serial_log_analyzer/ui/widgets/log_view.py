"""日志视图：过滤栏 + 表格，接收流水线增量并处理自动滚动。

只持有 Qt 模型引用，不解析日志；上下文选择所需的条目查询由 :meth:`selected_log_entries`
提供给控制器。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.ui.models.log_filter_model import LogFilterModel
from serial_log_analyzer.ui.models.log_table_model import LEVEL_LABELS, LogTableModel

__all__ = ["LogView"]

_FILTERED_LEVELS = (LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR)


class LogView(QWidget):
    """日志表格视图。

    参数:
        model: :class:`LogTableModel` 实例（数据来源，容量由 core 控制）。
        parent: 可选父对象。

    信号:
        selection_changed(list): 选中变化，携带条目序号。
        export_requested(): 用户请求导出日志。
        import_requested(): 用户请求导入历史日志。
        clear_requested(): 用户请求清空日志。
    """

    selection_changed = Signal(list)
    export_requested = Signal()
    import_requested = Signal()
    clear_requested = Signal()

    def __init__(self, model: LogTableModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._filter = LogFilterModel(self)
        self._filter.setSourceModel(model)
        self._autoscroll = True
        self._level_boxes: dict[LogLevel, QCheckBox] = {}
        self._build()
        model.rowsInserted.connect(self._on_rows_inserted)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def append_update(self, update: object) -> None:
        """接收流水线增量（新增 / continuation 更新 / 容量截断）。"""

        added = list(getattr(update, "added", ()))
        if added:
            self._model.add_entries(added)
        self._model.update_entries(list(getattr(update, "updated", ())))
        self._model.remove_sequences(list(getattr(update, "dropped_sequences", ())))

    def selected_log_entries(self) -> list[LogEntry]:
        """返回当前选中的条目，供构造分析上下文。"""

        entries: list[LogEntry] = []
        for index in self.table_view.selectionModel().selectedRows():
            entry = self._model.entry_at(self._filter.mapToSource(index).row())
            if entry is not None:
                entries.append(entry)
        return entries

    def set_autoscroll(self, enabled: bool) -> None:
        """设置新日志到达时是否自动滚动到底部。"""

        self._autoscroll = bool(enabled)

    def clear(self) -> None:
        """清空表格。"""

        self._model.clear()

    # ------------------------------------------------------------------
    # 构建与槽函数
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel("级别:"))
        for level in _FILTERED_LEVELS:
            box = QCheckBox(LEVEL_LABELS[level])
            box.setChecked(True)
            box.toggled.connect(self._apply_filters)
            self._level_boxes[level] = box
            bar.addWidget(box)
        bar.addWidget(QLabel("模块:"))
        self.module_filter = QLineEdit()
        self.module_filter.setPlaceholderText("模块名")
        self.module_filter.setMaximumWidth(120)
        self.module_filter.textChanged.connect(self._apply_filters)
        bar.addWidget(self.module_filter)
        bar.addWidget(QLabel("关键字:"))
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("消息关键字")
        self.text_filter.setMaximumWidth(200)
        self.text_filter.textChanged.connect(self._apply_filters)
        bar.addWidget(self.text_filter)
        bar.addStretch()

        export = QPushButton("导出")
        export.clicked.connect(self.export_requested.emit)
        bar.addWidget(export)
        load = QPushButton("导入")
        load.clicked.connect(self.import_requested.emit)
        bar.addWidget(load)
        clear = QPushButton("清空")
        clear.clicked.connect(self.clear_requested.emit)
        bar.addWidget(clear)
        layout.addLayout(bar)

        self.table_view = QTableView()
        self.table_view.setModel(self._filter)
        self.table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setWordWrap(False)
        self.table_view.setShowGrid(False)
        self.table_view.verticalHeader().setVisible(False)
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.table_view.setColumnWidth(0, 60)
        self.table_view.setColumnWidth(1, 110)
        self.table_view.setColumnWidth(2, 60)
        self.table_view.setColumnWidth(3, 120)
        layout.addWidget(self.table_view, stretch=1)

    def _apply_filters(self) -> None:
        allowed = {level for level, box in self._level_boxes.items() if box.isChecked()}
        self._filter.set_allowed_levels(
            None if allowed == set(_FILTERED_LEVELS) else allowed
        )
        self._filter.set_module_filter(self.module_filter.text())
        self._filter.set_text_filter(self.text_filter.text())

    def _on_rows_inserted(self, parent: object, first: int, last: int) -> None:
        if self._autoscroll:
            self.table_view.scrollToBottom()

    def _on_selection_changed(self) -> None:
        self.selection_changed.emit(
            [entry.sequence for entry in self.selected_log_entries()]
        )
