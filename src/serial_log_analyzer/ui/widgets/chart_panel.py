"""实时遥测数据图表：按勾选字段纵向堆叠独立 PyQtGraph 子图。

职责边界：
- 内部持有纯 Python 的 :class:`TelemetryBuffer`，只做渲染与交互控制，不解析原始日志行；
- 仅使用 ``ThemeTokens`` 中的克制语义配色，不添加渐变、阴影等过度装饰；
- 先声明 ``PYQTGRAPH_QT_LIB=PySide6`` 并导入 ``PySide6``，再导入 ``pyqtgraph``。
"""

from __future__ import annotations

import os
import re

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
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

from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.logs.telemetry import TelemetryBuffer, TelemetrySample
from serial_log_analyzer.ui.icons import render_icon, render_pixmap
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens

__all__ = ["ChartPanel"]

_SUBPLOT_MIN_HEIGHT = 120
_SUBPLOT_ROW_STEP = 135
_MIN_CANVAS_HEIGHT = 160
_SYMBOL_THRESHOLD = 100
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
    """绘制字段勾选芯片左侧彩色圆点（兼容 1x / 2x）。"""

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


class ChartPanel(QWidget):
    """基于 PyQtGraph 的多传感器实时趋势面板。

    参数:
        parent: 可选父对象。
        preset_fields: 当前 Preset 声明的字段名顺序（优先排在前方并默认勾选）。
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
        self._checked_fields: dict[str, bool] = dict.fromkeys(self._buffer.field_names(), True)
        self._chip_buttons: dict[str, QToolButton] = {}
        self._chip_fields: tuple[str, ...] = ()
        self._field_colors: dict[str, str] = {}
        self._plotted_fields: tuple[str, ...] = ()
        self._plots: dict[str, pg.PlotItem] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._crosshairs: dict[str, pg.InfiniteLine] = {}
        self._hover_time: float | None = None

        self._build()
        self._sync_chips(force=True)
        self._sync_view(force_rebuild=True)
        self.set_theme_tokens(self._tokens)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def append_update(self, update: PipelineUpdate) -> None:
        """同步流水线增量（淘汰序号与新增有效数值字段）。"""

        if not self._buffer.apply_update(update):
            return
        for name in self._buffer.field_names():
            self._checked_fields.setdefault(name, True)
        self._sync_chips()
        self._sync_view()

    def set_preset_fields(self, fields: Sequence[str]) -> None:
        """切换 Preset 时重置时序缓冲与字段勾选集合。"""

        self._buffer.reset(fields)
        self._checked_fields = dict.fromkeys(self._buffer.field_names(), True)
        self._hover_time = None
        self._sync_chips(force=True)
        self._sync_view(force_rebuild=True)

    def clear(self) -> None:
        """清空已采样曲线数据，保留当前字段列表与勾选状态。"""

        self._buffer.clear_samples()
        self._hover_time = None
        self._sync_view()

    def visible_fields(self) -> tuple[str, ...]:
        """返回当前处于勾选状态的字段名元组（保持缓存顺序）。"""

        return tuple(
            name for name in self._buffer.field_names() if self._checked_fields.get(name, True)
        )

    def sample_count(self, field: str) -> int:
        """返回指定字段当前在缓冲中的采样点数。"""

        return len(self._buffer.samples(field))

    def field_names(self) -> tuple[str, ...]:
        """返回当前缓冲登记的全部有序字段名。"""

        return self._buffer.field_names()

    def hover_at_time(self, time_s: float) -> None:
        """将全部可见子图的垂直参考线定位到 ``time_s`` 并刷新最邻近数值读数。"""

        self._hover_time = float(time_s)
        for line in self._crosshairs.values():
            line.setPos(self._hover_time)
            line.setVisible(True)
        self._refresh_readout()

    def clear_hover(self) -> None:
        """隐藏垂直参考线并将状态栏读数恢复为最新值快照。"""

        if self._hover_time is None:
            return
        self._hover_time = None
        for line in self._crosshairs.values():
            line.setVisible(False)
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

        self._graphics_layout.setBackground(tokens.bg_surface)
        crosshair_pen = pg.mkPen(tokens.text_muted, width=1.0, style=Qt.PenStyle.DashLine)
        for field_name, plot in self._plots.items():
            self._style_plot(plot, field_name)
            curve = self._curves.get(field_name)
            if curve is not None:
                color = self._field_colors[field_name]
                curve.setPen(pg.mkPen(color, width=1.8))
                if curve.opts.get("symbol") is not None:
                    curve.setSymbolBrush(color)
            line = self._crosshairs.get(field_name)
            if line is not None:
                line.setPen(crosshair_pen)
        self._sync_curve_data()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self._graphics_layout and event.type() == QEvent.Type.Leave:
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
        self._chips_scroll.setFixedHeight(30)
        self._chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._chips_scroll.setStyleSheet(
            "QScrollArea#chart-chips-scroll { background: transparent; border: none; }"
        )
        self._chips_scroll.viewport().setAutoFillBackground(False)

        self._chips_container = QWidget()
        self._chips_container.setAutoFillBackground(False)
        self._chips_layout = QHBoxLayout(self._chips_container)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(4)
        self._chips_layout.addStretch()
        self._chips_scroll.setWidget(self._chips_container)
        top_bar.addWidget(self._chips_scroll, stretch=1)

        self.auto_follow_btn = QToolButton()
        self.auto_follow_btn.setObjectName("chart-auto-follow")
        self.auto_follow_btn.setText("自动跟随")
        self.auto_follow_btn.setCheckable(True)
        self.auto_follow_btn.setChecked(True)
        self.auto_follow_btn.setProperty("chip", "toggle")
        self.auto_follow_btn.setToolTip("新采样到达时自动缩放并跟踪最新时间窗口")
        self.auto_follow_btn.toggled.connect(self._on_auto_follow_toggled)
        top_bar.addWidget(self.auto_follow_btn)

        self.reset_zoom_btn = QToolButton()
        self.reset_zoom_btn.setObjectName("chart-reset-zoom")
        self.reset_zoom_btn.setText("重置缩放")
        self.reset_zoom_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.reset_zoom_btn.setIconSize(QSize(13, 13))
        self.reset_zoom_btn.setToolTip("将所有子图恢复为完整数据范围")
        self.reset_zoom_btn.clicked.connect(self._reset_zoom)
        top_bar.addWidget(self.reset_zoom_btn)

        self.clear_btn = QToolButton()
        self.clear_btn.setObjectName("chart-clear")
        self.clear_btn.setText("清空图表")
        self.clear_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.clear_btn.setIconSize(QSize(13, 13))
        self.clear_btn.setToolTip("清空已采样曲线数据（保留当前字段勾选）")
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

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("chart-scroll-area")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self._graphics_layout = pg.GraphicsLayoutWidget()
        self._graphics_layout.setObjectName("chart-graphics-layout")
        self._graphics_layout.setMouseTracking(True)
        self._graphics_layout.installEventFilter(self)
        self._graphics_layout.scene().sigMouseMoved.connect(self._on_scene_mouse_moved)

        self._scroll_area.setWidget(self._graphics_layout)
        self._content_stack.addWidget(self._scroll_area)
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

    def _assign_field_colors(self) -> None:
        palette = _series_palette(self._tokens)
        self._field_colors = {
            name: palette[index % len(palette)]
            for index, name in enumerate(self._buffer.field_names())
        }

    def _sync_chips(self, *, force: bool = False) -> None:
        fields = self._buffer.field_names()
        if not force and fields == self._chip_fields:
            return
        self._chip_fields = fields
        self._assign_field_colors()

        for button in self._chip_buttons.values():
            self._chips_layout.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self._chip_buttons.clear()

        has_fields = bool(fields)
        self._no_fields_label.setVisible(not has_fields)
        self._chips_scroll.setVisible(has_fields)
        if not has_fields:
            return

        # 保留末尾 stretch，把芯片插在其前面。
        for insert_pos, field_name in enumerate(fields):
            chip = QToolButton(self._chips_container)
            chip.setObjectName(_field_chip_object_name(field_name))
            chip.setText(field_name)
            chip.setCheckable(True)
            chip.setChecked(self._checked_fields.get(field_name, True))
            chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            chip.setIconSize(QSize(10, 10))
            chip.setIcon(_dot_icon(self._field_colors[field_name]))
            chip.setProperty("chip", "toggle")
            chip.toggled.connect(
                lambda checked, name=field_name: self._on_field_toggled(name, checked)
            )
            self._chips_layout.insertWidget(insert_pos, chip)
            self._chip_buttons[field_name] = chip

    def _sync_view(self, *, force_rebuild: bool = False) -> None:
        visible = self.visible_fields()
        has_any_sample = any(self._buffer.samples(name) for name in self._buffer.field_names())

        if not has_any_sample:
            self._empty_title.setText("暂无遥测数值采样")
            self._empty_hint.setText(
                "收到含数值字段（如 temperature=29.7）的日志后将自动绘制时序曲线"
            )
            self._content_stack.setCurrentWidget(self._empty_page)
            if force_rebuild or self._plotted_fields:
                self._clear_subplots()
            self._refresh_readout()
            return

        if not visible:
            self._empty_title.setText("未勾选任何展示字段")
            self._empty_hint.setText("请在上方勾选至少一个数值字段以查看实时趋势曲线")
            self._content_stack.setCurrentWidget(self._empty_page)
            if force_rebuild or self._plotted_fields:
                self._clear_subplots()
            self._refresh_readout()
            return

        self._content_stack.setCurrentWidget(self._scroll_area)
        if force_rebuild or visible != self._plotted_fields:
            self._rebuild_subplots(visible)
        self._sync_curve_data()
        self._refresh_readout()

    def _clear_subplots(self) -> None:
        self._graphics_layout.clear()
        self._plots.clear()
        self._curves.clear()
        self._crosshairs.clear()
        self._plotted_fields = ()

    def _rebuild_subplots(self, visible: tuple[str, ...]) -> None:
        self._clear_subplots()
        self._assign_field_colors()
        self._plotted_fields = visible

        ci_layout = self._graphics_layout.ci.layout
        ci_layout.setVerticalSpacing(6)
        self._graphics_layout.setMinimumHeight(
            max(_MIN_CANVAS_HEIGHT, len(visible) * _SUBPLOT_ROW_STEP)
        )

        crosshair_pen = pg.mkPen(self._tokens.text_muted, width=1.0, style=Qt.PenStyle.DashLine)
        first_plot: pg.PlotItem | None = None
        last_index = len(visible) - 1

        for row, field_name in enumerate(visible):
            plot = self._graphics_layout.addPlot(row=row, col=0)
            plot.setMinimumHeight(_SUBPLOT_MIN_HEIGHT)
            ci_layout.setRowMinimumHeight(row, _SUBPLOT_MIN_HEIGHT)
            plot.hideButtons()
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.getAxis("left").enableAutoSIPrefix(False)
            plot.getAxis("bottom").enableAutoSIPrefix(False)
            plot.getAxis("bottom").setStyle(showValues=(row == last_index))
            if row == last_index:
                plot.setLabel("bottom", "时间 (s)", color=self._tokens.text_secondary)
            self._style_plot(plot, field_name)

            if first_plot is None:
                first_plot = plot
            else:
                plot.setXLink(first_plot)

            color = self._field_colors[field_name]
            curve = plot.plot([], [], pen=pg.mkPen(color, width=1.8))
            crosshair = pg.InfiniteLine(angle=90, movable=False, pen=crosshair_pen)
            crosshair.setVisible(self._hover_time is not None)
            if self._hover_time is not None:
                crosshair.setPos(self._hover_time)
            plot.addItem(crosshair, ignoreBounds=True)
            plot.vb.sigRangeChangedManually.connect(self._on_manual_zoom)
            plot.enableAutoRange(enable=self.auto_follow_btn.isChecked())

            self._plots[field_name] = plot
            self._curves[field_name] = curve
            self._crosshairs[field_name] = crosshair

    def _style_plot(self, plot: pg.PlotItem, field_name: str) -> None:
        axis_pen = pg.mkPen(self._tokens.border_strong)
        text_pen = pg.mkPen(self._tokens.text_secondary)
        for axis_name in ("left", "bottom"):
            axis = plot.getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(text_pen)
        plot.setLabel("left", field_name, color=self._tokens.text_secondary)
        if field_name == (self._plotted_fields[-1] if self._plotted_fields else ""):
            plot.setLabel("bottom", "时间 (s)", color=self._tokens.text_secondary)

    def _sync_curve_data(self) -> None:
        auto_follow = self.auto_follow_btn.isChecked()
        for field_name, curve in self._curves.items():
            samples = self._buffer.samples(field_name)
            xs = [sample.time_s for sample in samples]
            ys = [sample.value for sample in samples]
            color = self._field_colors.get(field_name, self._tokens.accent_primary)
            if xs and len(xs) <= _SYMBOL_THRESHOLD:
                curve.setData(xs, ys, symbol="o", symbolSize=5, symbolPen=None, symbolBrush=color)
            else:
                curve.setData(xs, ys, symbol=None)
            plot = self._plots.get(field_name)
            if plot is not None and auto_follow:
                plot.enableAutoRange(enable=True)

    def _refresh_readout(self) -> None:
        visible = self.visible_fields()
        if not visible:
            self.readout_label.setText("未勾选展示字段")
            return

        if self._hover_time is not None:
            parts: list[str] = []
            for field_name in visible:
                samples = self._buffer.samples(field_name)
                if not samples:
                    continue
                nearest = _nearest_sample(samples, self._hover_time)
                parts.append(f"{field_name}={_format_num(nearest.value)}")
            if parts:
                self.readout_label.setText(f"指针 t={self._hover_time:.2f}s | " + "  ".join(parts))
                return

        latest_time: float | None = None
        latest_parts: list[str] = []
        for field_name in visible:
            samples = self._buffer.samples(field_name)
            if not samples:
                continue
            last = samples[-1]
            if latest_time is None or last.time_s > latest_time:
                latest_time = last.time_s
            latest_parts.append(f"{field_name}={_format_num(last.value)}")
        if latest_time is None:
            self.readout_label.setText("等待数值采样…")
            return
        self.readout_label.setText(f"最新 t={latest_time:.2f}s | " + "  ".join(latest_parts))

    # ------------------------------------------------------------------
    # 交互回调
    # ------------------------------------------------------------------

    def _on_field_toggled(self, field_name: str, checked: bool) -> None:
        self._checked_fields[field_name] = bool(checked)
        self._sync_view()

    def _on_auto_follow_toggled(self, checked: bool) -> None:
        for plot in self._plots.values():
            plot.enableAutoRange(enable=checked)
            if checked:
                plot.autoRange()

    def _on_manual_zoom(self, *_args: object) -> None:
        if not self.auto_follow_btn.isChecked():
            return
        self.auto_follow_btn.blockSignals(True)
        self.auto_follow_btn.setChecked(False)
        self.auto_follow_btn.blockSignals(False)
        for plot in self._plots.values():
            plot.enableAutoRange(enable=False)

    def _reset_zoom(self) -> None:
        auto_follow = self.auto_follow_btn.isChecked()
        for plot in self._plots.values():
            plot.enableAutoRange(enable=auto_follow)
            plot.autoRange()

    def _on_scene_mouse_moved(self, scene_pos: QPointF) -> None:
        if not self._plots:
            return
        for plot in self._plots.values():
            if plot.sceneBoundingRect().contains(scene_pos):
                view_pos = plot.vb.mapSceneToView(scene_pos)
                self.hover_at_time(float(view_pos.x()))
                return
        self.clear_hover()


def _nearest_sample(samples: tuple[TelemetrySample, ...], target_time: float) -> TelemetrySample:
    """在采样元组中查找距离 ``target_time`` 最近的样本。"""

    return min(samples, key=lambda item: abs(item.time_s - target_time))
