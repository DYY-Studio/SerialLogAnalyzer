"""应用日志面板：显示程序自身日志文件的尾部。

取数由组合根注入（`diagnostics.app_logging.read_tail`），界面层不直接读文件；
面板可见时才定时刷新，隐藏后停止。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["AppLogPanel"]

_REFRESH_MS = 1000
_MAX_LINES = 1000
_COPY_HINT_MS = 1200


class _PathLabel(QLabel):
    """路径标签：按当前宽度中间省略，点击复制完整路径。

    长路径既不撑大面板最小宽度，也仍然看得到盘符与文件名；完整值在 tooltip 里。
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_tooltip()
        self._apply()

    def full_text(self) -> str:
        """完整路径。"""

        return self._full

    def sizeHint(self) -> QSize:
        return QSize(140, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(60, super().minimumSizeHint().height())

    def resizeEvent(self, event: object) -> None:
        self._apply()
        super().resizeEvent(event)

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            QGuiApplication.clipboard().setText(self._full)
            self.setToolTip("已复制")
            QTimer.singleShot(_COPY_HINT_MS, self._reset_tooltip)
        super().mouseReleaseEvent(event)

    def _reset_tooltip(self) -> None:
        self.setToolTip(f"{self._full}\n（点击复制）")

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        width = max(0, self.width() - 4)
        super().setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideMiddle, width))


class AppLogPanel(QWidget):
    """应用日志尾部视图。

    参数:
        read_lines: 取数回调，返回日志末尾若干行。
        log_path: 日志文件路径，展示在标题行（可复制）。
        parent: 可选父对象。
    """

    def __init__(
        self,
        read_lines: Callable[[], list[str]],
        log_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._read_lines = read_lines
        self._build(log_path)
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self.reload)

    def reload(self) -> None:
        """重新读取日志尾部；内容没变就不重绘。"""

        text = "\n".join(self._read_lines())
        if text == self._view.toPlainText():
            return
        self._view.setPlainText(text)
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def showEvent(self, event: object) -> None:
        self._timer.start()
        self.reload()
        super().showEvent(event)

    def hideEvent(self, event: object) -> None:
        self._timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------------

    def _build(self, log_path: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("文件:"))
        self.path_label = _PathLabel(log_path)
        row.addWidget(self.path_label, stretch=1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        layout.addLayout(row)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setPlaceholderText("暂无日志输出")
        self._view.setMaximumBlockCount(_MAX_LINES)
        layout.addWidget(self._view, stretch=1)
