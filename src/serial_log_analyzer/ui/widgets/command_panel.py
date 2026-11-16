"""命令面板：向设备发送一行命令，并按顺序累计显示命令回复。

``@OK`` / ``@ERR`` 响应行由 ``core`` 的会话层拦截、不进日志流水线，因此在日志表格之外单独
呈现（DESIGN §7）：发出去的命令与设备回复追加在同一个可滚动区域里，便于回看。
只发射用户意图信号，不直接操作串口。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

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
from serial_log_analyzer.core.logs.preset import PresetCommand, PresetCommandMode
from serial_log_analyzer.ui.icons import render_icon
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens, monospace_font

__all__ = ["CommandPanel"]

# 回复历史保留的行数上限，超过后由 Qt 丢弃最旧的行，避免长时间运行一直涨内存。
_MAX_LINES = 1000
_MAX_PLACEHOLDER_ITEMS = 6
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_DEFAULT_COMMANDS: tuple[PresetCommand, ...] = (
    PresetCommand(label="PING", command="PING"),
    PresetCommand(label="VERSION", command="VERSION"),
    PresetCommand(label="HELP", command="HELP"),
    PresetCommand(
        label="TEST …",
        command="TEST ",
        mode=PresetCommandMode.PREFILL,
        tooltip="预填 TEST 前缀（需补充场景名，如 wifi / uart / gpio / memory）",
    ),
)


def _unique_chip_object_name(command: PresetCommand, used: set[str]) -> str:
    """为快捷命令按钮生成稳定且不重名的 ``objectName``。"""

    slug = _SLUG_RE.sub("-", command.label.lower()).strip("-")
    if not slug:
        slug = _SLUG_RE.sub("-", command.command.lower()).strip("-") or "item"
    base = f"cmd-chip-{slug}"
    name = base
    index = 2
    while name in used:
        name = f"{base}-{index}"
        index += 1
    used.add(name)
    return name


def _format_placeholder(commands: tuple[PresetCommand, ...]) -> str:
    """按当前快捷命令集合生成输入框提示文案。"""

    if not commands:
        return "输入板端命令"
    labels = [item.label for item in commands[:_MAX_PLACEHOLDER_ITEMS]]
    if len(commands) > _MAX_PLACEHOLDER_ITEMS:
        labels.append("…")
    return "输入板端命令：" + " / ".join(labels)


class CommandPanel(QWidget):
    """命令输入 + 回复历史。

    参数:
        parent: 可选父对象。
        commands: 可选 Preset 快捷命令列表；``None`` 时使用内置默认列表，传空序列时隐藏快捷栏。
        tokens: 可选主题 Token；缺省按当前应用探测。

    信号:
        command_submitted(str): 请求发送一行命令。
    """

    command_submitted = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        commands: Sequence[PresetCommand] | None = None,
        tokens: ThemeTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else default_tokens()
        self._chip_buttons: list[QToolButton] = []
        self._build()
        self.set_commands(_DEFAULT_COMMANDS if commands is None else commands)
        self.set_theme_tokens(self._tokens)

    def set_commands(self, commands: Sequence[PresetCommand]) -> None:
        """替换快捷命令按钮列表与输入提示（传入空序列时隐藏快捷栏）。

        参数:
            commands: 目标快捷命令序列。
        """

        for button in self._chip_buttons:
            self._chips_layout.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self._chip_buttons.clear()

        items = tuple(commands)
        has_commands = bool(items)
        self._quick_label.setVisible(has_commands)
        self._chips_container.setVisible(has_commands)

        used_names: set[str] = set()
        for cmd in items:
            chip = QToolButton(self._chips_container)
            chip.setObjectName(_unique_chip_object_name(cmd, used_names))
            chip.setText(cmd.label)
            chip.setProperty("chip", "cmd")
            if cmd.tooltip:
                chip.setToolTip(cmd.tooltip)
            if cmd.mode is PresetCommandMode.PREFILL:
                chip.clicked.connect(
                    lambda _checked=False, text=cmd.command: self._prefill_command(text)
                )
            else:
                chip.clicked.connect(
                    lambda _checked=False, text=cmd.command: self._submit_command(text)
                )
            self._chips_layout.addWidget(chip)
            self._chip_buttons.append(chip)
        self.command_edit.setPlaceholderText(_format_placeholder(items))

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
        self._quick_label = QLabel("快捷:")
        self._quick_label.setObjectName("cmd-quick-label")
        self._quick_label.setProperty("role", "muted-caption")
        chip_row.addWidget(self._quick_label)
        self._chips_container = QWidget()
        self._chips_container.setObjectName("cmd-chips-container")
        self._chips_layout = QHBoxLayout(self._chips_container)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(4)
        chip_row.addWidget(self._chips_container)
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

    def _prefill_command(self, text: str) -> None:
        self.command_edit.setText(text)
        self.command_edit.setFocus()
        self.command_edit.setCursorPosition(len(text))

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
