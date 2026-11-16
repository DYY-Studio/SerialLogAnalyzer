"""日志视图：过滤栏 + 表格，接收流水线增量并处理自动滚动。

只持有 Qt 模型引用，不解析日志；上下文选择所需的条目查询由 :meth:`selected_log_entries`
提供给控制器。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.ui.delegates import LogLevelDelegate
from serial_log_analyzer.ui.icons import render_icon, render_pixmap
from serial_log_analyzer.ui.models.log_filter_model import LogFilterModel
from serial_log_analyzer.ui.models.log_table_model import LEVEL_LABELS, LogTableModel
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens, level_styles, monospace_font

__all__ = ["LogView"]


def _dot_icon(color_hex: str) -> QIcon:
    """绘制用于日志级别过滤芯片的圆点图标（兼容 1x / 2x）。"""

    icon = QIcon()
    for dpr in (1.0, 2.0):
        px = round(10 * dpr)
        pixmap = QPixmap(px, px)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(dpr)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color_hex))
        painter.drawEllipse(1, 1, 8, 8)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class LogView(QWidget):
    """日志表格视图。

    参数:
        model: :class:`LogTableModel` 实例（数据来源，容量由 core 控制）。
        parent: 可选父对象。
        tokens: 可选主题 Token；缺省按当前应用探测。

    信号:
        selection_changed(list): 选中变化，携带条目序号。
        autoscroll_toggled(bool): 用户切换了自动滚动开关。
    """

    selection_changed = Signal(list)
    autoscroll_toggled = Signal(bool)

    def __init__(
        self,
        model: LogTableModel,
        parent: QWidget | None = None,
        *,
        tokens: ThemeTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._tokens = tokens if tokens is not None else default_tokens()
        self._filter = LogFilterModel(self)
        self._filter.setSourceModel(model)
        self._autoscroll = True
        self._level_boxes: dict[LogLevel, QToolButton] = {}
        self._build()
        self.set_theme_tokens(self._tokens)
        model.rowsInserted.connect(self._on_rows_inserted)
        for sig in (
            self._filter.modelReset,
            self._filter.rowsInserted,
            self._filter.rowsRemoved,
            self._filter.layoutChanged,
        ):
            sig.connect(self._sync_empty_state)
        self.table_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table_view.viewport().installEventFilter(self)
        self._sync_empty_state()

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def set_theme_tokens(self, tokens: ThemeTokens) -> None:
        """按主题 Token 刷新过滤芯片色点、图标、空状态与级别列胶囊委托。"""

        self._tokens = tokens
        self._level_delegate.set_tokens(tokens)
        styles = level_styles(tokens)
        for level, chip in self._level_boxes.items():
            chip.setIcon(_dot_icon(styles[level].foreground))
        search_icon = render_icon("search", tokens.text_muted, size=13)
        self._module_search_action.setIcon(search_icon)
        self._text_search_action.setIcon(search_icon)
        self.reset_filter_btn.setIcon(render_icon("disconnect", tokens.text_secondary, size=14))
        self._empty_icon.setPixmap(render_pixmap("terminal", tokens.text_muted, size=28, dpr=2.0))
        self.table_view.viewport().update()

    def clear_filters(self) -> None:
        """清空全部过滤条件并恢复全级别选中。"""

        for chip in self._level_boxes.values():
            chip.blockSignals(True)
            chip.setChecked(True)
            chip.blockSignals(False)
        self.module_filter.blockSignals(True)
        self.module_filter.clear()
        self.module_filter.blockSignals(False)
        self.text_filter.blockSignals(True)
        self.text_filter.clear()
        self.text_filter.blockSignals(False)
        self._apply_filters()

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
        """设置新日志到达时是否自动滚动到底部（同步勾选状态）。"""

        self._autoscroll = bool(enabled)
        if self.autoscroll_box.isChecked() != self._autoscroll:
            self.autoscroll_box.blockSignals(True)
            self.autoscroll_box.setChecked(self._autoscroll)
            self.autoscroll_box.blockSignals(False)

    def clear(self) -> None:
        """清空表格。"""

        self._model.clear()

    def scroll_to_sequence(self, sequence: int) -> bool:
        """定位并选中指定流水线序号对应的日志行。

        参数:
            sequence: 目标日志条目序号。

        返回:
            找到并在当前过滤视图中可见时滚动选中并返回 ``True``；已被淘汰或被当前过滤条件隐藏时返回 ``False``。
        """

        source_row = self._model.row_for_sequence(sequence)
        if source_row is None:
            return False
        proxy_index = self._filter.mapFromSource(self._model.index(source_row, 0))
        if not proxy_index.isValid():
            return False
        self.table_view.selectRow(proxy_index.row())
        self.table_view.scrollTo(proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.table_view.setFocus()
        return True

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.table_view.viewport() and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._center_empty_state()
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    # 构建与槽函数
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)

        for level in LogLevel:
            chip = QToolButton()
            chip.setText(LEVEL_LABELS[level])
            chip.setCheckable(True)
            chip.setChecked(True)
            chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            chip.setIconSize(QSize(10, 10))
            chip.setProperty("chip", "level")
            chip.toggled.connect(self._apply_filters)
            self._level_boxes[level] = chip
            filter_row.addWidget(chip)

        filter_row.addSpacing(4)

        self.module_filter = QLineEdit()
        self.module_filter.setPlaceholderText("模块名…")
        self.module_filter.setClearButtonEnabled(True)
        self.module_filter.setMinimumWidth(95)
        self.module_filter.setMaximumWidth(145)
        self._module_search_action = QAction(self)
        self.module_filter.addAction(self._module_search_action, QLineEdit.ActionPosition.LeadingPosition)
        self.module_filter.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.module_filter)

        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("搜索日志关键字…")
        self.text_filter.setClearButtonEnabled(True)
        self.text_filter.setMinimumWidth(130)
        self._text_search_action = QAction(self)
        self.text_filter.addAction(self._text_search_action, QLineEdit.ActionPosition.LeadingPosition)
        self.text_filter.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.text_filter, stretch=1)

        self.reset_filter_btn = QToolButton()
        self.reset_filter_btn.setObjectName("log-reset-filters")
        self.reset_filter_btn.setToolTip("清空过滤条件")
        self.reset_filter_btn.setIconSize(QSize(14, 14))
        self.reset_filter_btn.clicked.connect(self.clear_filters)
        filter_row.addWidget(self.reset_filter_btn)

        self.autoscroll_box = QToolButton()
        self.autoscroll_box.setText("自动滚动")
        self.autoscroll_box.setCheckable(True)
        self.autoscroll_box.setChecked(True)
        self.autoscroll_box.setProperty("chip", "toggle")
        self.autoscroll_box.toggled.connect(self._on_autoscroll_toggled)
        filter_row.addWidget(self.autoscroll_box)

        layout.addLayout(filter_row)

        self.table_view = QTableView()
        self.table_view.setModel(self._filter)
        self.table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table_view.setAlternatingRowColors(False)
        self.table_view.setWordWrap(False)
        self.table_view.setShowGrid(False)
        self.table_view.setFont(monospace_font())
        v_header = self.table_view.verticalHeader()
        v_header.setVisible(False)
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        v_header.setDefaultSectionSize(25)

        self._level_delegate = LogLevelDelegate(self.table_view, tokens=self._tokens)
        self.table_view.setItemDelegateForColumn(2, self._level_delegate)

        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.table_view.setColumnWidth(0, 62)
        self.table_view.setColumnWidth(1, 106)
        self.table_view.setColumnWidth(2, 68)
        self.table_view.setColumnWidth(3, 120)

        self._empty_state = self._build_empty_state(self.table_view.viewport())
        layout.addWidget(self.table_view, stretch=1)

    def _build_empty_state(self, parent: QWidget) -> QWidget:
        overlay = QWidget(parent)
        overlay.setObjectName("log-empty-state")
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        box = QVBoxLayout(overlay)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)
        self._empty_icon = QLabel()
        self._empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._empty_icon)
        self._empty_title = QLabel()
        self._empty_title.setObjectName("log-empty-title")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._empty_title)
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("log-empty-hint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)
        box.addWidget(self._empty_hint)
        return overlay

    def _sync_empty_state(self, *_args: object) -> None:
        empty = self._filter.rowCount() == 0
        if empty:
            if self._model.rowCount() == 0:
                self._empty_title.setText("暂无串口日志")
                self._empty_hint.setText("请在顶部工具栏选择串口并点击「连接」，或通过「文件 → 导入日志…」加载文件")
            else:
                self._empty_title.setText("没有匹配当前过滤条件的日志")
                self._empty_hint.setText("可调整上方级别芯片或点击右侧清空按钮恢复显示")
            self._center_empty_state()
        self._empty_state.setVisible(empty)

    def _center_empty_state(self) -> None:
        viewport = self.table_view.viewport()
        self._empty_state.adjustSize()
        size = self._empty_state.sizeHint()
        x = max(8, (viewport.width() - size.width()) // 2)
        y = max(8, (viewport.height() - size.height()) // 2)
        self._empty_state.setGeometry(x, y, min(size.width(), max(160, viewport.width() - 16)), size.height())

    def _apply_filters(self) -> None:
        # 每个级别都有自己的芯片按钮，因此选中集就是唯一口径，不再有"全勾才不过滤"的特例。
        allowed = {level for level, box in self._level_boxes.items() if box.isChecked()}
        self._filter.set_allowed_levels(allowed)
        self._filter.set_module_filter(self.module_filter.text())
        self._filter.set_text_filter(self.text_filter.text())
        self._sync_empty_state()

    def _on_rows_inserted(self, parent: object, first: int, last: int) -> None:
        if self._autoscroll:
            self.table_view.scrollToBottom()

    def _on_autoscroll_toggled(self, enabled: bool) -> None:
        self._autoscroll = enabled
        self.autoscroll_toggled.emit(enabled)

    def _on_selection_changed(self) -> None:
        self.selection_changed.emit(
            [entry.sequence for entry in self.selected_log_entries()]
        )
