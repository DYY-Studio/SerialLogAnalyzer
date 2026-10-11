"""命令面板：向设备发送一行命令，并按顺序累计显示命令回复。

``@OK`` / ``@ERR`` 响应行由 ``core`` 的会话层拦截、不进日志流水线，因此在日志表格之外单独
呈现（DESIGN §7）：发出去的命令与设备回复追加在同一个可滚动区域里，便于回看。
只发射用户意图信号，不直接操作串口。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.device.command import CommandReply

__all__ = ["CommandPanel"]

# 回复历史保留的行数上限，超过后由 Qt 丢弃最旧的行，避免长时间运行一直涨内存。
_MAX_LINES = 1000


class CommandPanel(QWidget):
    """命令输入 + 回复历史。

    参数:
        parent: 可选父对象。

    信号:
        command_submitted(str): 请求发送一行命令。
    """

    command_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def append_reply(self, reply: CommandReply) -> None:
        """追加一条设备回复（失败时带上错误码）。"""

        if reply.ok:
            self._append(f"← {reply.text}")
            return
        code = f"[{reply.code}] " if reply.code is not None else ""
        self._append(f"← 失败 {code}{reply.text}")

    # ------------------------------------------------------------------
    # 构建与槽函数
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("命令:"))
        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText("PING / VERSION / HELP / TEST <name>")
        self.command_edit.returnPressed.connect(self._on_send)
        row.addWidget(self.command_edit, stretch=1)
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._on_send)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

        self.reply_view = QPlainTextEdit()
        self.reply_view.setReadOnly(True)
        self.reply_view.setPlaceholderText("命令回复将显示在这里")
        self.reply_view.setMaximumBlockCount(_MAX_LINES)
        layout.addWidget(self.reply_view, stretch=1)

    def _on_send(self) -> None:
        command = self.command_edit.text().strip()
        if not command:
            return
        self.command_edit.clear()
        self._append(f"→ {command}")
        self.command_submitted.emit(command)

    def _append(self, line: str) -> None:
        self.reply_view.appendPlainText(line)
