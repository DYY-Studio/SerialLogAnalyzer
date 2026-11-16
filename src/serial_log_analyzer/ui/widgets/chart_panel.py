"""实时遥测数据图表：互斥标签胶囊切换单图 + 可选滑动时间窗口。

职责边界：
- 内部持有纯 Python 的 :class:`TelemetryBuffer`，只做单图渲染与交互控制，不解析原始日志行；
- 仅使用 ``ThemeTokens`` 中的克制语义配色，不添加渐变、阴影等过度装饰；
- 先声明 ``PYQTGRAPH_QT_LIB=PySide6`` 并导入 ``PySide6``，再导入 ``pyqtgraph``。
"""

from __future__ import annotations

import math
import os
import re

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# isort: split
import pyqtgraph as pg  # noqa: E402 - 须在环境变量与 PySide6 之后导入

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.logs.telemetry import TelemetryBuffer, TelemetrySample
from serial_log_analyzer.ui.icons import render_icon, render_pixmap
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens

__all__ = ["ChartPanel"]

_WINDOW_OPTIONS: tuple[tuple[str, float | None], ...] = (
    ("15 秒", 15.0),
    ("30 秒", 30.0),
    ("1 分钟", 60.0),
    ("5 分钟", 300.0),
    ("全部", None),
)
_DEFAULT_WINDOW_INDEX = 1
_SYMBOL_THRESHOLD = 80
_FIELD_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _series_palette(tokens: ThemeTokens) -> tuple[str, ...]:
    """从主题 Token 提取曲线语义色板（无硬编码外部颜色）。"""

    return (
        tokens.accent_primary,
        tokens.success,
        tokens.warning,
        tokens.info,
        tokens.level_unknown,
        tokens.danger,
    )


def _dot_icon(color_hex: str) -> QIcon:
    """绘制字段切换胶囊左侧彩色圆点（兼容 1x / 2x）。"""

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


def _format_num(value: float) -> str:
    """紧凑格式化有限数值，避免多余尾随零。"""

    if value == 0.0:
        return "0"
    return f"{value:.4g}"


def _field_chip_object_name(field: str) -> str:
    slug = _FIELD_SLUG_RE.sub("-", field.lower()).strip("-") or "field"
    return f"chart-field-{slug}"


def _y_bounds(values: Sequence[float]) -> tuple[float, float]:
    """计算纵轴范围：常数序列给 ±1.0 留白，否则上下加约 10% 边距。"""

    y_min = min(values)
    y_max = max(values)
    span = y_max - y_min
    if math.isclose(span, 0.0, abs_tol=1e-12):
        return y_min - 1.0, y_max + 1.0
    pad = span * 0.1
    return y_min - pad, y_max + pad


def _compute_x_window(xs: Sequence[float], window_s: float) -> tuple[float, float]:
    """根据有限时间窗口 ``window_s`` 计算水平可见区间 ``(x0, x1)``。"""

    t_min = min(xs)
    t_max = max(xs)
    if t_max - t_min <= window_s:
        return t_min, t_min + window_s
    return t_max - window_s, t_max + window_s * 0.02


def _compute_data_range(
    xs: Sequence[float],
    ys: Sequence[float],
    window_s: float | None,
) -> tuple[float, float, float, float]:
    """计算给定采样与时间窗口下的 ``(x0, x1, y0, y1)`` 视图范围。"""

    if window_s is not None:
        x0, x1 = _compute_x_window(xs, window_s)
        visible_ys = [y for x, y in zip(xs, ys, strict=True) if x0 <= x <= x1]
        y0, y1 = _y_bounds(visible_ys or ys)
        return x0, x1, y0, y1

    t_min = min(xs)
    t_max = max(xs)
    span_x = t_max - t_min
    if span_x <= 0.0:
        x0, x1 = t_min - 0.5, t_max + 0.5
    else:
        pad_x = span_x * 0.02
        x0, x1 = t_min - pad_x, t_max + pad_x
    y0, y1 = _y_bounds(ys)
    return x0, x1, y0, y1


def _nearest_sample(samples: tuple[TelemetrySample, ...], target_time: float) -> TelemetrySample:
    """在采样元组中查找距离 ``target_time`` 最近的样本。"""

    return min(samples, key=lambda item: abs(item.time_s - target_time))


class ChartPanel(QWidget):
    """基于 PyQtGraph 的单图切换式实时遥测趋势面板。

    参数:
        parent: 可选父对象。
        preset_fields: 当前 Preset 声明的字段名顺序（默认选中首个有效字段）。
        max_points: 单字段保留的最大采样点数。
        tokens: 可选主题 Token；缺省按当前应用探测。
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        preset_fields: Sequence[str] = (),
        max_points: int = 2000,
        tokens: ThemeTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else default_tokens()
        self._buffer = TelemetryBuffer(preset_fields, max_points=max_points)
        fields = self._buffer.field_names()
        self._selected_field: str | None = fields[0] if fields else None
        self._user_selected_field = False
        self._chip_buttons: dict[str, QToolButton] = {}
        self._chip_fields: tuple[str, ...] = ()
        self._field_colors: dict[str, str] = {}
        self._hover_time: float | None = None
        self._applying_range = False
        self._showing_full_reset = False

        self._build()
        self._sync_chips(force=True)
        self._sync_view(field_changed=True)
        self.set_theme_tokens(self._tokens)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def append_update(self, update: PipelineUpdate) -> None:
        """同步流水线增量（淘汰序号与新增有效数值字段）。"""

        if not self._buffer.apply_update(update):
            return
        fields = self._buffer.field_names()
        prev_field = self._selected_field
        if not fields:
            self._selected_field = None
            self._user_selected_field = False
        elif self._selected_field not in fields:
            self._selected_field = self._first_field_with_samples() or fields[0]
            self._user_selected_field = False
        elif not self._user_selected_field and not self._buffer.samples(self._selected_field):
            first_active = self._first_field_with_samples()
            if first_active is not None:
                self._selected_field = first_active

        self._sync_chips()
        self._sync_view(field_changed=self._selected_field != prev_field)

    def set_preset_fields(self, fields: Sequence[str]) -> None:
        """切换 Preset 时清空数据并默认选中第一个有效字段。"""

        self._buffer.reset(fields)
        self._hover_time = None
        self._crosshair.setVisible(False)
        self._user_selected_field = False
        names = self._buffer.field_names()
        self._selected_field = names[0] if names else None
        self._sync_chips(force=True)
        self._sync_view(field_changed=True)

    def clear(self) -> None:
        """清空已采样曲线数据，保留当前字段列表与选中状态。"""

        self._buffer.clear_samples()
        self._hover_time = None
        self._crosshair.setVisible(False)
        self._sync_view()

    def current_field(self) -> str | None:
        """返回当前选中的字段名；无可用字段时返回 ``None``。"""

        return self._selected_field

    def select_field(self, field: str) -> None:
        """切换单图展示的当前字段（未登记字段忽略）。"""

        if field not in self._buffer.field_names():
            return
        self._user_selected_field = True
        if self._selected_field == field:
            return
        self._selected_field = field
        self._sync_chip_selection()
        self._sync_view(field_changed=True)

    def window_seconds(self) -> float | None:
        """返回当前时间窗口秒数；选择「全部」时返回 ``None``。"""

        data = self.window_combo.currentData()
        return float(data) if data is not None else None

    def set_window_seconds(self, seconds: float | None) -> None:
        """设置时间窗口并主动开启「自动跟随」。

        参数:
            seconds: 目标窗口秒数（``15.0`` / ``30.0`` / ``60.0`` / ``300.0`` / ``None``）。

        异常:
            ConfigError: 传入不在预设档位中的窗口值。
        """

        target_index = self._find_window_index(seconds)
        if target_index < 0:
            raise ConfigError(f"不支持的时间窗口秒数：{seconds}")
        self.window_combo.blockSignals(True)
        self.window_combo.setCurrentIndex(target_index)
        self.window_combo.blockSignals(False)
        self._on_window_changed()

    def sample_count(self, field: str) -> int:
        """返回指定字段当前在缓冲中的采样点数。"""

        return len(self._buffer.samples(field))

    def field_names(self) -> tuple[str, ...]:
        """返回当前缓冲登记的全部有序字段名。"""

        return self._buffer.field_names()

    def hover_at_time(self, time_s: float) -> None:
        """将垂直参考线定位到 ``time_s`` 并刷新当前字段的最近样本读数。"""

        self._hover_time = float(time_s)
        self._crosshair.setPos(self._hover_time)
        self._crosshair.setVisible(self._content_stack.currentWidget() is self._plot_widget)
        self._refresh_readout()

    def clear_hover(self) -> None:
        """隐藏垂直参考线并将读数条恢复为最新值与极值摘要。"""

        if self._hover_time is None:
            return
        self._hover_time = None
        self._crosshair.setVisible(False)
        self._refresh_readout()

    def set_theme_tokens(self, tokens: ThemeTokens) -> None:
        """按主题 Token 刷新按钮图标、芯片色点、图表背景、坐标轴与曲线配色。"""

        self._tokens = tokens
        self._assign_field_colors()
        for field_name, chip in self._chip_buttons.items():
            chip.setIcon(_dot_icon(self._field_colors[field_name]))

        self.reset_zoom_btn.setIcon(render_icon("refresh", tokens.text_secondary, size=13))
        self.clear_btn.setIcon(render_icon("clear", tokens.text_secondary, size=13))
        self._empty_icon.setPixmap(render_pixmap("chart", tokens.text_muted, size=28, dpr=2.0))

        self._plot_widget.setBackground(tokens.bg_surface)
        self._style_plot(self._selected_field)
        self._crosshair.setPen(pg.mkPen(tokens.text_muted, width=1.0, style=Qt.PenStyle.DashLine))
        self._sync_plot_data(apply_range=False)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self._plot_widget and event.type() == QEvent.Type.Leave:
            self.clear_hover()
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    # 构建与内部同步
    # ------------------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self._no_fields_label = QLabel("暂无可绘制数值字段")
        self._no_fields_label.setObjectName("chart-no-fields")
        self._no_fields_label.setProperty("role", "muted-caption")
        top_bar.addWidget(self._no_fields_label)

        self._chips_scroll = QScrollArea()
        self._chips_scroll.setObjectName("chart-chips-scroll")
        self._chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chips_scroll.setWidgetResizable(True)
        self._chips_scroll.setFixedHeight(34)
        self._chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._chips_scroll.setStyleSheet(
            "QScrollArea#chart-chips-scroll { background: transparent; border: none; }"
        )
        self._chips_scroll.viewport().setAutoFillBackground(False)

        self._chips_container = QWidget()
        self._chips_container.setAutoFillBackground(False)
        self._chips_layout = QHBoxLayout(self._chips_container)
        self._chips_layout.setContentsMargins(0, 1, 0, 1)
        self._chips_layout.setSpacing(4)
        self._chips_layout.addStretch()
        self._chips_scroll.setWidget(self._chips_container)
        top_bar.addWidget(self._chips_scroll, stretch=1)

        self._field_group = QButtonGroup(self)
        self._field_group.setExclusive(True)
        self._field_group.buttonToggled.connect(self._on_field_button_toggled)
        self._field_group.buttonClicked.connect(self._on_field_button_clicked)

        self.window_combo = QComboBox()
        self.window_combo.setObjectName("chart-window-combo")
        for label, seconds in _WINDOW_OPTIONS:
            self.window_combo.addItem(label, seconds)
        self.window_combo.setCurrentIndex(_DEFAULT_WINDOW_INDEX)
        self.window_combo.setToolTip("选择自动跟随时展示的时间窗口跨度")
        self.window_combo.currentIndexChanged.connect(self._on_window_changed)
        top_bar.addWidget(self.window_combo)

        self.auto_follow_btn = QToolButton()
        self.auto_follow_btn.setObjectName("chart-auto-follow")
        self.auto_follow_btn.setText("自动跟随")
        self.auto_follow_btn.setCheckable(True)
        self.auto_follow_btn.setChecked(True)
        self.auto_follow_btn.setProperty("chip", "toggle")
        self.auto_follow_btn.setToolTip("新采样到达时按所选时间窗口平滑跟随并适配纵轴")
        self.auto_follow_btn.toggled.connect(self._on_auto_follow_toggled)
        top_bar.addWidget(self.auto_follow_btn)

        self.reset_zoom_btn = QToolButton()
        self.reset_zoom_btn.setObjectName("chart-reset-zoom")
        self.reset_zoom_btn.setText("重置缩放")
        self.reset_zoom_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.reset_zoom_btn.setIconSize(QSize(13, 13))
        self.reset_zoom_btn.setToolTip("显示当前字段完整采样数据范围")
        self.reset_zoom_btn.clicked.connect(self._reset_zoom)
        top_bar.addWidget(self.reset_zoom_btn)

        self.clear_btn = QToolButton()
        self.clear_btn.setObjectName("chart-clear")
        self.clear_btn.setText("清空图表")
        self.clear_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.clear_btn.setIconSize(QSize(13, 13))
        self.clear_btn.setToolTip("清空已采样曲线数据（保留当前字段配置）")
        self.clear_btn.clicked.connect(self.clear)
        top_bar.addWidget(self.clear_btn)

        root.addLayout(top_bar)

        self.readout_label = QLabel("等待数值采样…")
        self.readout_label.setObjectName("chart-readout")
        self.readout_label.setProperty("role", "muted-caption")
        self.readout_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.readout_label)

        self._content_stack = QStackedWidget()
        self._empty_page = self._build_empty_page()
        self._content_stack.addWidget(self._empty_page)

        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setObjectName("chart-plot-widget")
        self._plot_widget.setFrameShape(QFrame.Shape.NoFrame)
        self._plot_widget.setMouseTracking(True)
        self._plot_widget.installEventFilter(self)
        self._plot_widget.scene().sigMouseMoved.connect(self._on_scene_mouse_moved)

        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.hideButtons()
        self._plot_item.showGrid(x=True, y=True, alpha=0.18)
        self._plot_item.getAxis("left").enableAutoSIPrefix(False)
        self._plot_item.getAxis("bottom").enableAutoSIPrefix(False)
        self._plot_item.enableAutoRange(enable=False)
        self._plot_item.vb.sigRangeChangedManually.connect(self._on_manual_zoom)

        self._curve = self._plot_item.plot(
            [], [], pen=pg.mkPen(self._tokens.accent_primary, width=1.8)
        )
        self._crosshair = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen(self._tokens.text_muted, width=1.0, style=Qt.PenStyle.DashLine),
        )
        self._crosshair.setVisible(False)
        self._plot_item.addItem(self._crosshair, ignoreBounds=True)

        self._content_stack.addWidget(self._plot_widget)
        root.addWidget(self._content_stack, stretch=1)

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(6)
        box.addStretch()
        self._empty_icon = QLabel()
        self._empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._empty_icon)
        self._empty_title = QLabel()
        self._empty_title.setObjectName("chart-empty-title")
        self._empty_title.setProperty("role", "section-title")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._empty_title)
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("chart-empty-hint")
        self._empty_hint.setProperty("role", "muted-caption")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)
        box.addWidget(self._empty_hint)
        box.addStretch()
        return page

    def _first_field_with_samples(self) -> str | None:
        for name in self._buffer.field_names():
            if self._buffer.samples(name):
                return name
        return None

    def _find_window_index(self, seconds: float | None) -> int:
        if seconds is None:
            for index in range(self.window_combo.count()):
                if self.window_combo.itemData(index) is None:
                    return index
            return -1
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
        ):
            return -1
        target = float(seconds)
        for index in range(self.window_combo.count()):
            data = self.window_combo.itemData(index)
            if data is not None and math.isclose(float(data), target, rel_tol=0.0, abs_tol=1e-9):
                return index
        return -1

    def _assign_field_colors(self) -> None:
        palette = _series_palette(self._tokens)
        self._field_colors = {
            name: palette[index % len(palette)]
            for index, name in enumerate(self._buffer.field_names())
        }

    def _sync_chips(self, *, force: bool = False) -> None:
        fields = self._buffer.field_names()
        if force or fields != self._chip_fields:
            self._chip_fields = fields
            self._assign_field_colors()
            self._field_group.blockSignals(True)
            try:
                for button in self._chip_buttons.values():
                    self._field_group.removeButton(button)
                    self._chips_layout.removeWidget(button)
                    button.setParent(None)
                    button.deleteLater()
                self._chip_buttons.clear()

                has_fields = bool(fields)
                self._no_fields_label.setVisible(not has_fields)
                self._chips_scroll.setVisible(has_fields)
                if has_fields:
                    # 保留末尾 stretch，把字段胶囊插入其前面。
                    for insert_pos, field_name in enumerate(fields):
                        chip = QToolButton(self._chips_container)
                        chip.setObjectName(_field_chip_object_name(field_name))
                        chip.setText(field_name)
                        chip.setCheckable(True)
                        chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                        chip.setIconSize(QSize(10, 10))
                        chip.setIcon(_dot_icon(self._field_colors[field_name]))
                        chip.setProperty("chip", "toggle")
                        chip.setProperty("fieldName", field_name)
                        self._field_group.addButton(chip)
                        self._chips_layout.insertWidget(insert_pos, chip)
                        self._chip_buttons[field_name] = chip
            finally:
                self._field_group.blockSignals(False)
        self._sync_chip_selection()

    def _sync_chip_selection(self) -> None:
        self._field_group.blockSignals(True)
        try:
            for field_name, chip in self._chip_buttons.items():
                selected = field_name == self._selected_field
                if chip.isChecked() != selected:
                    chip.blockSignals(True)
                    chip.setChecked(selected)
                    chip.blockSignals(False)
        finally:
            self._field_group.blockSignals(False)

    def _sync_view(self, *, field_changed: bool = False) -> None:
        has_any_sample = any(self._buffer.samples(name) for name in self._buffer.field_names())
        field = self._selected_field
        samples = self._buffer.samples(field) if field is not None else ()

        if not has_any_sample or field is None or not samples:
            if not has_any_sample:
                self._empty_title.setText("暂无遥测数值采样")
                self._empty_hint.setText(
                    "收到含数值字段（如 temperature=29.7）的日志后将自动绘制时序曲线"
                )
            else:
                self._empty_title.setText(f"字段 {field} 暂无数值采样")
                self._empty_hint.setText("当前尚无该字段的数值日志，可选择上方其他有采样的字段标签")
            self._crosshair.setVisible(False)
            self._curve.setData([], [])
            self._content_stack.setCurrentWidget(self._empty_page)
            self._refresh_readout()
            return

        self._content_stack.setCurrentWidget(self._plot_widget)
        self._style_plot(field)
        self._sync_plot_data(apply_range=True, field_changed=field_changed)
        if self._hover_time is not None:
            self._crosshair.setPos(self._hover_time)
            self._crosshair.setVisible(True)
        self._refresh_readout()

    def _style_plot(self, field_name: str | None) -> None:
        axis_pen = pg.mkPen(self._tokens.border_strong)
        text_pen = pg.mkPen(self._tokens.text_secondary)
        for axis_name in ("left", "bottom"):
            axis = self._plot_item.getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(text_pen)
        self._plot_item.setLabel("left", field_name or "", color=self._tokens.text_secondary)
        self._plot_item.setLabel("bottom", "时间 (s)", color=self._tokens.text_secondary)

    def _apply_view_range(self, x0: float, x1: float, y0: float, y1: float) -> None:
        self._applying_range = True
        try:
            self._plot_item.enableAutoRange(enable=False)
            self._plot_item.setXRange(x0, x1, padding=0)
            self._plot_item.setYRange(y0, y1, padding=0)
        finally:
            self._applying_range = False

    def _visible_samples(
        self,
        samples: tuple[TelemetrySample, ...],
    ) -> tuple[list[TelemetrySample], bool]:
        """返回当前视图范围（或窗口）内可见样本及是否处于局部时间窗。"""

        if not samples:
            return [], False
        if self._showing_full_reset:
            return list(samples), False
        window_s = self.window_seconds()
        if self.auto_follow_btn.isChecked():
            if window_s is None:
                return list(samples), False
            x0, x1 = _compute_x_window([item.time_s for item in samples], window_s)
            return [item for item in samples if x0 <= item.time_s <= x1], True

        view_x0, view_x1 = self._plot_item.viewRange()[0]
        in_view = [item for item in samples if view_x0 <= item.time_s <= view_x1]
        if in_view:
            return in_view, len(in_view) < len(samples) or window_s is not None
        return list(samples), False

    def _sync_plot_data(self, *, apply_range: bool = True, field_changed: bool = False) -> None:
        field = self._selected_field
        if field is None:
            self._curve.setData([], [])
            return
        samples = self._buffer.samples(field)
        if not samples:
            self._curve.setData([], [])
            return

        xs = [sample.time_s for sample in samples]
        ys = [sample.value for sample in samples]
        window_s = self.window_seconds()

        if apply_range:
            self._showing_full_reset = False
            if self.auto_follow_btn.isChecked():
                x0, x1, y0, y1 = _compute_data_range(xs, ys, window_s)
                self._apply_view_range(x0, x1, y0, y1)
            elif field_changed:
                view_x0, view_x1 = self._plot_item.viewRange()[0]
                in_view_ys = [y for x, y in zip(xs, ys, strict=True) if view_x0 <= x <= view_x1]
                if in_view_ys:
                    y0, y1 = _y_bounds(in_view_ys)
                    self._apply_view_range(view_x0, view_x1, y0, y1)
                else:
                    x0, x1, y0, y1 = _compute_data_range(xs, ys, None)
                    self._apply_view_range(x0, x1, y0, y1)

        visible_samples, _ = self._visible_samples(samples)
        color = self._field_colors.get(field, self._tokens.accent_primary)
        pen = pg.mkPen(color, width=1.8)
        if 0 < len(visible_samples) <= _SYMBOL_THRESHOLD:
            self._curve.setData(
                xs,
                ys,
                pen=pen,
                symbol="o",
                symbolSize=5,
                symbolPen=None,
                symbolBrush=color,
            )
        else:
            self._curve.setData(xs, ys, pen=pen, symbol=None)

    def _refresh_readout(self) -> None:
        field = self._selected_field
        if field is None:
            self.readout_label.setText("暂无可绘制数值字段")
            return
        samples = self._buffer.samples(field)
        if not samples:
            has_any = any(self._buffer.samples(name) for name in self._buffer.field_names())
            self.readout_label.setText(
                f"{field} · 暂无数值采样" if has_any else "等待数值采样…"
            )
            return

        if self._hover_time is not None:
            nearest = _nearest_sample(samples, self._hover_time)
            self.readout_label.setText(
                f"指针 t={self._hover_time:.2f}s | {field}={_format_num(nearest.value)}"
            )
            return

        last = samples[-1]
        visible_samples, is_windowed = self._visible_samples(samples)
        stats_samples = visible_samples or list(samples)
        min_v = min(item.value for item in stats_samples)
        max_v = max(item.value for item in stats_samples)
        scope = "窗内" if is_windowed else "全量"
        self.readout_label.setText(
            f"{field} · 最新 t={last.time_s:.2f}s | 当前 {_format_num(last.value)}"
            f"（{scope}最小 {_format_num(min_v)} / 最大 {_format_num(max_v)}）"
        )

    # ------------------------------------------------------------------
    # 交互回调
    # ------------------------------------------------------------------

    def _on_field_button_toggled(self, button: QAbstractButton, checked: bool) -> None:
        if not checked:
            return
        field_name = button.property("fieldName")
        if isinstance(field_name, str):
            self.select_field(field_name)

    def _on_field_button_clicked(self, button: QAbstractButton) -> None:
        field_name = button.property("fieldName")
        if isinstance(field_name, str):
            self.select_field(field_name)

    def _on_window_changed(self, *_args: object) -> None:
        if not self.auto_follow_btn.isChecked():
            self.auto_follow_btn.blockSignals(True)
            self.auto_follow_btn.setChecked(True)
            self.auto_follow_btn.blockSignals(False)
        self._sync_plot_data(apply_range=True)
        self._refresh_readout()

    def _on_auto_follow_toggled(self, checked: bool) -> None:
        if checked:
            self._sync_plot_data(apply_range=True)
            self._refresh_readout()

    def _on_manual_zoom(self, *_args: object) -> None:
        if self._applying_range or not self.auto_follow_btn.isChecked():
            return
        self._showing_full_reset = False
        self.auto_follow_btn.blockSignals(True)
        self.auto_follow_btn.setChecked(False)
        self.auto_follow_btn.blockSignals(False)

    def _reset_zoom(self) -> None:
        field = self._selected_field
        if field is None:
            return
        samples = self._buffer.samples(field)
        if not samples:
            return
        xs = [sample.time_s for sample in samples]
        ys = [sample.value for sample in samples]
        x0, x1, y0, y1 = _compute_data_range(xs, ys, None)
        self._showing_full_reset = True
        self._apply_view_range(x0, x1, y0, y1)
        self._sync_plot_data(apply_range=False)
        self._refresh_readout()

    def _on_scene_mouse_moved(self, scene_pos: QPointF) -> None:
        if self._content_stack.currentWidget() is not self._plot_widget:
            return
        if self._plot_item.sceneBoundingRect().contains(scene_pos):
            view_pos = self._plot_item.vb.mapSceneToView(scene_pos)
            self.hover_at_time(float(view_pos.x()))
            return
        self.clear_hover()
