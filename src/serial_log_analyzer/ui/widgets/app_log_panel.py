"""应用日志面板：显示程序自身日志文件的尾部。

取数由组合根注入（`diagnostics.app_logging.read_tail`），界面层不直接读文件；
面板可见时才定时刷新，隐藏后停止。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
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
        path_label = QLabel(log_path)
        path_label.setToolTip(log_path)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(path_label, stretch=1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        layout.addLayout(row)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setPlaceholderText("暂无日志输出")
        self._view.setMaximumBlockCount(_MAX_LINES)
        layout.addWidget(self._view, stretch=1)
