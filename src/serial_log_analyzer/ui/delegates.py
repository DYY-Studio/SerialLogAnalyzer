"""日志表格自定义单元格委托：将级别列绘制为语义胶囊徽章。"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.ui.models.log_table_model import LEVEL_LABELS, LOG_LEVEL_ROLE
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens, level_styles

__all__ = ["LogLevelDelegate"]

_PILL_HEIGHT = 18.0
_PILL_MIN_WIDTH = 42.0
_PILL_RADIUS = 9.0
_PILL_H_PADDING = 14.0


class LogLevelDelegate(QStyledItemDelegate):
    """日志级别列胶囊委托：结合主题语义色绘制低饱和圆角徽章。

    参数:
        parent: 可选父对象。
        tokens: 初始主题 Token；缺省按当前应用探测。
    """

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        tokens: ThemeTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else default_tokens()
        self._styles = level_styles(self._tokens)

    def set_tokens(self, tokens: ThemeTokens) -> None:
        """更新主题 Token，确保胶囊颜色随明暗模式同步。"""

        self._tokens = tokens
        self._styles = level_styles(tokens)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """先由 Qt 样式绘制行底色/选中态，再叠加居中级别胶囊。"""

        level = index.data(LOG_LEVEL_ROLE)
        if not isinstance(level, LogLevel):
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        label = opt.text or LEVEL_LABELS.get(level, level.name)
        opt.text = ""

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        painter.save()
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        level_style = self._styles[level]
        pill_font = QFont(opt.font)
        pill_font.setPointSizeF(max(7.5, pill_font.pointSizeF() - 0.5))
        pill_font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetrics(pill_font)

        max_w = max(16.0, float(opt.rect.width()) - 8.0)
        pill_w = min(max_w, max(_PILL_MIN_WIDTH, float(metrics.horizontalAdvance(label)) + _PILL_H_PADDING))
        pill_h = min(max(14.0, float(opt.rect.height()) - 6.0), _PILL_HEIGHT)
        pill_rect = QRectF(
            opt.rect.x() + (opt.rect.width() - pill_w) / 2.0,
            opt.rect.y() + (opt.rect.height() - pill_h) / 2.0,
            pill_w,
            pill_h,
        )

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(level_style.pill_bg))
        painter.drawRoundedRect(pill_rect, _PILL_RADIUS, _PILL_RADIUS)

        painter.setFont(pill_font)
        painter.setPen(QColor(level_style.foreground))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        base = super().sizeHint(option, index)
        return QSize(max(base.width(), 64), max(base.height(), 25))
