"""命令面板：向设备发送一行命令，并按顺序累计显示命令回复。

``@OK`` / ``@ERR`` 响应行由 ``core`` 的会话层拦截、不进日志流水线，因此在日志表格之外单独
呈现（DESIGN §7）：发出去的命令与设备回复追加在同一个可滚动区域里，便于回看。
只发射用户意图信号，不直接操作串口。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.device.command import CommandReply
from serial_log_analyzer.ui.icons import render_icon
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens, monospace_font

__all__ = ["CommandPanel"]

# 回复历史保留的行数上限，超过后由 Qt 丢弃最旧的行，避免长时间运行一直涨内存。
_MAX_LINES = 1000
_QUICK_COMMANDS = ("PING", "VERSION", "HELP")


class CommandPanel(QWidget):
    """命令输入 + 回复历史。

    参数:
        parent: 可选父对象。
        tokens: 可选主题 Token；缺省按当前应用探测。

    信号:
        command_submitted(str): 请求发送一行命令。
    """

    command_submitted = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        tokens: ThemeTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else default_tokens()
        self._build()
        self.set_theme_tokens(self._tokens)

    def set_theme_tokens(self, tokens: ThemeTokens) -> None:
        """按主题 Token 刷新按钮图标与命令输出区的历史语义着色。"""

        self._tokens = tokens
        self.send_btn.setIcon(render_icon("send", tokens.text_on_accent, size=14))
        self.clear_btn.setIcon(render_icon("clear", tokens.text_secondary, size=14))
        self._recolor_history()

    def append_reply(self, reply: CommandReply) -> None:
        """追加一条设备回复（失败时带上错误码）。"""

        if reply.ok:
            self._append(f"← {reply.text}")
            return
        code = f"[{reply.code}] " if reply.code is not None else ""
        self._append(f"← 失败 {code}{reply.text}")

    def append_timeout(self, command: str) -> None:
        """追加一条命令响应超时提示。"""

        self._append(f"⏱ 超时未收到响应：{command}")

    # ------------------------------------------------------------------
    # 构建与槽函数
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(4)
        quick_label = QLabel("快捷:")
        quick_label.setProperty("role", "muted-caption")
        chip_row.addWidget(quick_label)
        for cmd in _QUICK_COMMANDS:
            chip = QToolButton()
            chip.setObjectName(f"cmd-chip-{cmd.lower()}")
            chip.setText(cmd)
            chip.setProperty("chip", "cmd")
            chip.clicked.connect(lambda _checked=False, c=cmd: self._submit_command(c))
            chip_row.addWidget(chip)
        test_chip = QToolButton()
        test_chip.setObjectName("cmd-chip-test")
        test_chip.setText("TEST …")
        test_chip.setToolTip("预填 TEST 前缀（需补充场景名，如 wifi / uart / gpio / memory）")
        test_chip.setProperty("chip", "cmd")
        test_chip.clicked.connect(self._prefill_test)
        chip_row.addWidget(test_chip)
        chip_row.addStretch()
        self.clear_btn = QToolButton()
        self.clear_btn.setObjectName("cmd-clear")
        self.clear_btn.setToolTip("清空命令记录")
        self.clear_btn.setIconSize(QSize(14, 14))
        self.clear_btn.clicked.connect(self.reply_view_clear)
        chip_row.addWidget(self.clear_btn)
        layout.addLayout(chip_row)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.command_edit = QLineEdit()
        self.command_edit.setFont(monospace_font())
        self.command_edit.setPlaceholderText("输入板端命令：PING / VERSION / HELP / TEST <name>")
        self.command_edit.returnPressed.connect(self._on_send)
        row.addWidget(self.command_edit, stretch=1)
        self.send_btn = QPushButton("发送")
        self.send_btn.setProperty("variant", "primary")
        self.send_btn.setIconSize(QSize(14, 14))
        self.send_btn.clicked.connect(self._on_send)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

        self.reply_view = QPlainTextEdit()
        self.reply_view.setReadOnly(True)
        self.reply_view.setFont(monospace_font())
        self.reply_view.setPlaceholderText("命令回复将显示在这里")
        self.reply_view.setMaximumBlockCount(_MAX_LINES)
        layout.addWidget(self.reply_view, stretch=1)

    def reply_view_clear(self) -> None:
        """清空命令回复历史区域。"""

        self.reply_view.clear()

    def _prefill_test(self) -> None:
        self.command_edit.setText("TEST ")
        self.command_edit.setFocus()
        self.command_edit.setCursorPosition(len("TEST "))

    def _on_send(self) -> None:
        command = self.command_edit.text().strip()
        if not command:
            return
        self.command_edit.clear()
        self._submit_command(command)

    def _submit_command(self, command: str) -> None:
        self._append(f"→ {command}")
        self.command_submitted.emit(command)

    def _append(self, line: str) -> None:
        cursor = self.reply_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.reply_view.document().isEmpty():
            cursor.insertBlock()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._color_for_line(line)))
        cursor.setCharFormat(fmt)
        cursor.insertText(line, fmt)
        bar = self.reply_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _recolor_history(self) -> None:
        doc = self.reply_view.document()
        if doc.isEmpty():
            return
        block = doc.begin()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        while block.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self._color_for_line(block.text())))
            cursor.setPosition(block.position())
            cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(fmt)
            block = block.next()
        cursor.endEditBlock()

    def _color_for_line(self, line: str) -> str:
        if line.startswith("→"):
            return self._tokens.text_muted
        if line.startswith("← 失败"):
            return self._tokens.danger
        if line.startswith("←"):
            return self._tokens.success
        if line.startswith("⏱"):
            return self._tokens.warning
        return self._tokens.text_primary
