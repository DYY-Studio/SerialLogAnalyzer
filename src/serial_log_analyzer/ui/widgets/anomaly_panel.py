"""异常与告警面板：展示只读异常簇快照、处理状态与证据跳转入口。

只渲染控制器推送的 :class:`AnomalyCluster` 与 :class:`AlertEvent` 只读快照，
不持有可变的规则或聚合状态；用户动作通过信号交给控制器处理。
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.models.anomaly import (
    AlertEvent,
    AnomalyCluster,
    AnomalySeverity,
    ClusterStatus,
)
from serial_log_analyzer.ui.icons import render_icon, render_pixmap
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens, monospace_font

__all__ = ["AnomalyPanel"]

_SEVERITY_LABELS: dict[AnomalySeverity, str] = {
    AnomalySeverity.CRITICAL: "严重",
    AnomalySeverity.HIGH: "高",
    AnomalySeverity.MEDIUM: "中",
    AnomalySeverity.LOW: "低",
}

_STATUS_LABELS: dict[ClusterStatus, str] = {
    ClusterStatus.ACTIVE: "活动",
    ClusterStatus.ACKNOWLEDGED: "已确认",
    ClusterStatus.RESOLVED: "已解决",
}

_FILTER_CHOICES: tuple[tuple[str, ClusterStatus | None], ...] = (
    ("全部", None),
    ("活动", ClusterStatus.ACTIVE),
    ("已确认", ClusterStatus.ACKNOWLEDGED),
    ("已解决", ClusterStatus.RESOLVED),
)


_PILL_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def _severity_palette(tokens: ThemeTokens, severity: AnomalySeverity) -> tuple[str, str, str | None]:
    """返回 ``(前景色, 底色, 可选边框色)`` 用于渲染异常严重度胶囊。"""

    if severity is AnomalySeverity.CRITICAL:
        return tokens.text_on_accent, tokens.danger, None
    if severity is AnomalySeverity.HIGH:
        return tokens.danger, tokens.danger_bg, tokens.danger
    if severity is AnomalySeverity.MEDIUM:
        return tokens.warning, tokens.warning_bg, None
    return tokens.info, tokens.info_bg, None


def _status_palette(tokens: ThemeTokens, status: ClusterStatus) -> tuple[str, str, str | None]:
    """返回 ``(前景色, 底色, 可选边框色)`` 用于渲染异常簇处理状态胶囊。"""

    if status is ClusterStatus.ACTIVE:
        return tokens.warning, tokens.warning_bg, None
    if status is ClusterStatus.ACKNOWLEDGED:
        return tokens.info, tokens.info_bg, None
    return tokens.success, tokens.success_bg, None


class _PillDelegate(QStyledItemDelegate):
    """在异常表格单元格内直接绘制胶囊标签，避免 cellWidget 重建残影。"""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: object,
    ) -> None:
        payload = index.data(_PILL_ROLE)
        if not isinstance(payload, tuple) or len(payload) != 4:
            super().paint(painter, option, index)
            return

        text, fg_hex, bg_hex, border_hex = payload
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        font = QFont(option.font)
        font.setPointSize(max(8, font.pointSize() - 1))
        font.setBold(True)
        painter.setFont(font)

        metrics = QFontMetrics(font)
        pill_w = min(option.rect.width() - 10, max(44, metrics.horizontalAdvance(text) + 16))
        pill_h = min(option.rect.height() - 8, max(19, metrics.height() + 5))
        pill_rect = QRectF(
            option.rect.x() + (option.rect.width() - pill_w) / 2.0,
            option.rect.y() + (option.rect.height() - pill_h) / 2.0,
            pill_w,
            pill_h,
        )
        if border_hex:
            painter.setPen(QPen(QColor(border_hex), 1.0))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg_hex))
        painter.drawRoundedRect(pill_rect, 4.0, 4.0)

        painter.setPen(QColor(fg_hex))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: object) -> QSize:
        payload = index.data(_PILL_ROLE)
        if not isinstance(payload, tuple) or len(payload) != 4:
            return super().sizeHint(option, index)
        font = QFont(option.font)
        font.setPointSize(max(8, font.pointSize() - 1))
        font.setBold(True)
        width = QFontMetrics(font).horizontalAdvance(payload[0]) + 30
        return QSize(max(64, width), 32)


def _format_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return "-"


class AnomalyPanel(QWidget):
    """异常集群与告警停靠面板。

    内部主容器使用 :class:`QStackedWidget`（``view_stack``）：第 0 页为异常簇视图，
    结构上保留后续扩展告警回执分页的能力。

    参数:
        parent: 可选父对象。
        tokens: 可选主题 Token；缺省按当前应用主题探测。

    信号:
        locate_requested(int): 用户请求跳转到对应证据日志序号。
        analyze_requested(object): 用户请求由 LLM 分析指定 :class:`AnomalyCluster`。
        acknowledge_requested(str): 用户请求确认指定 ``cluster_id``。
        resolve_requested(str): 用户请求解决指定 ``cluster_id``。
    """

    locate_requested = Signal(int)
    analyze_requested = Signal(object)
    acknowledge_requested = Signal(str)
    resolve_requested = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        tokens: ThemeTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else default_tokens()
        self._clusters: tuple[AnomalyCluster, ...] = ()
        self._visible_clusters: tuple[AnomalyCluster, ...] = ()
        self._status_filter: ClusterStatus | None = None
        self._latest_alert: AlertEvent | None = None
        self._filter_buttons: dict[ClusterStatus | None, QToolButton] = {}
        self._build()
        self.set_theme_tokens(self._tokens)
        self._render()

    @property
    def view_stack(self) -> QStackedWidget:
        """外层分页容器（第 0 页为异常簇面板，供后续里程碑扩展回执页）。"""

        return self._view_stack

    def set_theme_tokens(self, tokens: ThemeTokens) -> None:
        """按主题 Token 刷新图标、提醒横幅与表格徽标样式。"""

        self._tokens = tokens
        self._empty_icon.setPixmap(render_pixmap("alert", tokens.text_muted, size=26, dpr=2.0))
        self._refresh_banner()
        self._render_table()

    def set_clusters(self, clusters: list[AnomalyCluster] | tuple[AnomalyCluster, ...]) -> None:
        """用最新的只读异常簇列表刷新视图。

        参数:
            clusters: 只读 :class:`AnomalyCluster` 快照集合。
        """

        self._clusters = tuple(clusters)
        self._render()

    def clusters(self) -> list[AnomalyCluster]:
        """返回当前展示的全量只读异常簇快照列表。"""

        return list(self._clusters)

    def visible_clusters(self) -> list[AnomalyCluster]:
        """返回经状态过滤后当前表格可见的异常簇列表。"""

        return list(self._visible_clusters)

    def set_status_filter(self, status: ClusterStatus | None) -> None:
        """按处理状态过滤展示的异常簇（``None`` 表示全部）。"""

        self._status_filter = status
        button = self._filter_buttons.get(status)
        if button is not None and not button.isChecked():
            button.blockSignals(True)
            button.setChecked(True)
            button.blockSignals(False)
        self._render()

    def push_alert(self, alert: AlertEvent) -> None:
        """展示一条新触发告警的非阻塞面板内提示横幅。"""

        self._latest_alert = alert
        self._refresh_banner()

    def clear_alert_banner(self) -> None:
        """隐藏并清空面板内告警提示横幅。"""

        self._latest_alert = None
        self.alert_banner.setVisible(False)

    def clear(self) -> None:
        """清空异常簇列表并收起提示横幅。"""

        self._clusters = ()
        self._visible_clusters = ()
        self.clear_alert_banner()
        self._render()

    # ------------------------------------------------------------------
    # 构建与渲染
    # ------------------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        self._view_stack = QStackedWidget()
        self._anomaly_page = QWidget()
        page_layout = QVBoxLayout(self._anomaly_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(6)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for label, status in _FILTER_CHOICES:
            chip = QToolButton()
            chip.setText(label)
            chip.setCheckable(True)
            chip.setProperty("chip", "toggle")
            if status is None:
                chip.setChecked(True)
            chip.clicked.connect(lambda _checked=False, s=status: self.set_status_filter(s))
            self._filter_group.addButton(chip)
            self._filter_buttons[status] = chip
            filter_row.addWidget(chip)

        filter_row.addStretch()
        self.summary_label = QLabel("0 簇 · 0 活动")
        self.summary_label.setProperty("role", "muted-caption")
        filter_row.addWidget(self.summary_label)
        page_layout.addLayout(filter_row)

        self.alert_banner = QFrame()
        self.alert_banner.setObjectName("anomaly-alert-banner")
        self.alert_banner.setVisible(False)
        banner_row = QHBoxLayout(self.alert_banner)
        banner_row.setContentsMargins(8, 4, 6, 4)
        banner_row.setSpacing(6)
        self._banner_icon = QLabel()
        banner_row.addWidget(self._banner_icon)
        self._banner_text = QLabel()
        self._banner_text.setWordWrap(False)
        banner_row.addWidget(self._banner_text, stretch=1)
        self.banner_locate_btn = QPushButton("定位")
        self.banner_locate_btn.setProperty("variant", "ghost")
        self.banner_locate_btn.setProperty("compact", "row")
        self.banner_locate_btn.setToolTip("定位到触发该告警的最新日志证据")
        self.banner_locate_btn.clicked.connect(self._locate_latest_alert)
        banner_row.addWidget(self.banner_locate_btn)
        self.banner_dismiss_btn = QPushButton("忽略")
        self.banner_dismiss_btn.setProperty("variant", "ghost")
        self.banner_dismiss_btn.setProperty("compact", "row")
        self.banner_dismiss_btn.setToolTip("收起此提醒")
        self.banner_dismiss_btn.clicked.connect(self.clear_alert_banner)
        banner_row.addWidget(self.banner_dismiss_btn)
        page_layout.addWidget(self.alert_banner)

        self._content_stack = QStackedWidget()
        self._empty_page = self._build_empty_page()
        self._content_stack.addWidget(self._empty_page)

        self.table = QTableWidget(0, 7)
        self.table.setObjectName("anomaly-table")
        self.table.setHorizontalHeaderLabels(
            ["级别", "类别 / 规则", "模块", "异常摘要", "次数", "状态", "操作"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        v_header = self.table.verticalHeader()
        v_header.setVisible(False)
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        v_header.setDefaultSectionSize(32)
        h_header = self.table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        h_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        h_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(1, 195)
        self.table.setColumnWidth(2, 68)
        pill_delegate = _PillDelegate(self.table)
        self.table.setItemDelegateForColumn(0, pill_delegate)
        self.table.setItemDelegateForColumn(5, pill_delegate)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self._content_stack.addWidget(self.table)

        page_layout.addWidget(self._content_stack, stretch=1)
        self._view_stack.addWidget(self._anomaly_page)
        root.addWidget(self._view_stack, stretch=1)

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
        self._empty_title.setObjectName("anomaly-empty-title")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._empty_title)
        self._empty_hint = QLabel()
        self._empty_hint.setObjectName("anomaly-empty-hint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)
        box.addWidget(self._empty_hint)
        box.addStretch()
        return page

    def _render(self) -> None:
        active_count = sum(1 for item in self._clusters if item.status is ClusterStatus.ACTIVE)
        self.summary_label.setText(f"{len(self._clusters)} 簇 · {active_count} 活动")

        if self._status_filter is None:
            visible = self._clusters
        else:
            visible = tuple(item for item in self._clusters if item.status is self._status_filter)
        self._visible_clusters = visible

        if not visible:
            if not self._clusters:
                self._empty_title.setText("暂无检测到的异常")
                self._empty_hint.setText("串口连接并收到匹配异常规则的日志后，将在此聚合并提示告警")
            else:
                label = _STATUS_LABELS[self._status_filter] if self._status_filter else ""
                self._empty_title.setText(f"暂无「{label}」状态的异常簇")
                self._empty_hint.setText("可切换上方状态筛选芯片查看其他异常记录")
            self._content_stack.setCurrentWidget(self._empty_page)
            self.table.setRowCount(0)
            return

        self._content_stack.setCurrentWidget(self.table)
        self._render_table()

    def _clear_action_widgets(self) -> None:
        """显式卸载并隐藏旧行内按钮，防止重建表格时留存视图残影。"""

        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 6)
            if widget is not None:
                self.table.removeCellWidget(row, 6)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _render_table(self) -> None:
        visible = self._visible_clusters
        if not visible:
            self._clear_action_widgets()
            self.table.setRowCount(0)
            return

        tokens = self._tokens
        mono = monospace_font()
        self.table.setUpdatesEnabled(False)
        try:
            self._clear_action_widgets()
            self.table.setRowCount(len(visible))
            for row, cluster in enumerate(visible):
                sev_fg, sev_bg, sev_border = _severity_palette(tokens, cluster.severity)
                sev_item = QTableWidgetItem()
                sev_item.setData(
                    _PILL_ROLE,
                    (_SEVERITY_LABELS[cluster.severity], sev_fg, sev_bg, sev_border),
                )
                self.table.setItem(row, 0, sev_item)

                rule_item = QTableWidgetItem(f"{cluster.category} · {cluster.rule_id}")
                rule_item.setToolTip(
                    f"集群 {cluster.cluster_id}\n规则：{cluster.rule_id}\n类别：{cluster.category}\n"
                    f"首见：{_format_ts(cluster.first_seen)} · 末见：{_format_ts(cluster.last_seen)}"
                )
                self.table.setItem(row, 1, rule_item)

                modules_text = ", ".join(cluster.modules) or "-"
                module_item = QTableWidgetItem(modules_text)
                module_item.setToolTip(modules_text)
                self.table.setItem(row, 2, module_item)

                msg_item = QTableWidgetItem(cluster.normalized_message)
                msg_item.setFont(mono)
                seq_preview = ", ".join(f"#{seq}" for seq in cluster.evidence_sequences) or "无（已淘汰）"
                msg_item.setToolTip(
                    f"{cluster.normalized_message}\n证据序号：{seq_preview}"
                )
                self.table.setItem(row, 3, msg_item)

                count_item = QTableWidgetItem(str(cluster.occurrence_count))
                count_item.setFont(mono)
                count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 4, count_item)

                st_fg, st_bg, st_border = _status_palette(tokens, cluster.status)
                status_item = QTableWidgetItem()
                status_item.setData(
                    _PILL_ROLE,
                    (_STATUS_LABELS[cluster.status], st_fg, st_bg, st_border),
                )
                self.table.setItem(row, 5, status_item)
                self.table.setCellWidget(row, 6, self._build_action_cell(cluster))
        finally:
            self.table.setUpdatesEnabled(True)

    def _build_action_cell(self, cluster: AnomalyCluster) -> QWidget:
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)

        has_evidence = bool(cluster.evidence_sequences)
        locate_btn = QPushButton("定位")
        locate_btn.setProperty("variant", "ghost")
        locate_btn.setProperty("compact", "row")
        locate_btn.setEnabled(has_evidence)
        locate_btn.setToolTip(
            "定位到最新证据日志行（双击行亦可）"
            if has_evidence
            else "原始证据已超出日志缓冲容量并被淘汰"
        )
        locate_btn.clicked.connect(
            lambda _checked=False, c=cluster: self._emit_locate(c)
        )
        row.addWidget(locate_btn)

        analyze_btn = QPushButton("LLM")
        analyze_btn.setProperty("variant", "ghost")
        analyze_btn.setProperty("compact", "row")
        analyze_btn.setEnabled(has_evidence)
        analyze_btn.setToolTip(
            "使用 LLM 分析该异常簇及上下文日志"
            if has_evidence
            else "缺少可用于分析的日志证据"
        )
        analyze_btn.clicked.connect(
            lambda _checked=False, c=cluster: self.analyze_requested.emit(c)
        )
        row.addWidget(analyze_btn)

        ack_btn = QPushButton("确认")
        ack_btn.setProperty("variant", "ghost")
        ack_btn.setProperty("compact", "row")
        ack_btn.setEnabled(cluster.status is ClusterStatus.ACTIVE)
        ack_btn.setToolTip("标记为已确认")
        ack_btn.clicked.connect(
            lambda _checked=False, cid=cluster.cluster_id: self.acknowledge_requested.emit(cid)
        )
        row.addWidget(ack_btn)

        resolve_btn = QPushButton("解决")
        resolve_btn.setProperty("variant", "ghost")
        resolve_btn.setProperty("compact", "row")
        resolve_btn.setEnabled(cluster.status is not ClusterStatus.RESOLVED)
        resolve_btn.setToolTip("标记为已解决")
        resolve_btn.clicked.connect(
            lambda _checked=False, cid=cluster.cluster_id: self.resolve_requested.emit(cid)
        )
        row.addWidget(resolve_btn)
        return cell

    def _emit_locate(self, cluster: AnomalyCluster) -> None:
        if cluster.evidence_sequences:
            self.locate_requested.emit(cluster.evidence_sequences[-1])

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._visible_clusters):
            self._emit_locate(self._visible_clusters[row])

    def _refresh_banner(self) -> None:
        alert = self._latest_alert
        if alert is None:
            self.alert_banner.setVisible(False)
            return
        tokens = self._tokens
        high_or_crit = alert.severity >= AnomalySeverity.HIGH
        icon_color = tokens.danger if high_or_crit else tokens.warning
        self.alert_banner.setProperty("severity", alert.severity.name.lower())
        self.alert_banner.style().unpolish(self.alert_banner)
        self.alert_banner.style().polish(self.alert_banner)
        self._banner_icon.setPixmap(render_pixmap("alert", icon_color, size=14, dpr=2.0))
        sev_label = _SEVERITY_LABELS[alert.severity]
        self._banner_text.setText(
            f"新告警 [{sev_label}] {alert.title} · {alert.reason}"
        )
        self._banner_text.setToolTip(
            f"{alert.title}\n级别：{sev_label}\n规则：{alert.rule_id}\n原因：{alert.reason}"
        )
        self.banner_locate_btn.setEnabled(bool(alert.evidence_sequences))
        self.banner_locate_btn.setIcon(render_icon("locate", icon_color, size=12))
        self.alert_banner.setVisible(True)

    def _locate_latest_alert(self) -> None:
        alert = self._latest_alert
        if alert is not None and alert.evidence_sequences:
            self.locate_requested.emit(alert.evidence_sequences[-1])
