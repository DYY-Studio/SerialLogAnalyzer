"""
LLM 分析面板 - 右侧面板，用于日志上下文分析
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QPushButton,
    QTextEdit,
    QLabel,
    QGroupBox,
    QLineEdit,
)

from serial_log_analyzer.core.models.analysis import AnalysisMode, ContextSelector, AnalysisState


# 上下文选择选项
CONTEXT_OPTIONS = {
    "选中的日志": ContextSelector.SELECTED,
    "选中 + 前后各10条": ContextSelector.SELECTED_WITH_NEIGHBORS,
    "最近的50条": ContextSelector.RECENT,
    "仅错误日志": ContextSelector.ERRORS_ONLY,
}

# 预设分析目标
GOAL_OPTIONS = [
    "请分析以下日志，找出可能的错误原因并给出修复建议",
    "请解释以下日志中发生了什么",
    "请总结以下日志中的关键事件",
]


class AnalysisPanel(QWidget):
    """
    LLM 分析面板
    
    信号：
    - analyze_clicked(mode: AnalysisMode, selector: ContextSelector, user_input: str)
    - send_message_clicked(message: str)
    - new_session_clicked()
    """

    analyze_clicked = Signal(object, object, str)  # AnalysisMode, ContextSelector, user_input
    send_message_clicked = Signal(str)
    new_session_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._state = AnalysisState.IDLE

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(10)

        # 顶部控制区
        control_group = QGroupBox("分析设置")
        control_layout = QVBoxLayout(control_group)
        control_layout.setSpacing(10)
        control_layout.setContentsMargins(16, 20, 16, 16)

        # 上下文选择
        ctx_layout = QHBoxLayout()
        ctx_layout.addWidget(QLabel("上下文:"))
        self.context_combo = QComboBox()
        self.context_combo.setFixedHeight(30)
        for label in CONTEXT_OPTIONS:
            self.context_combo.addItem(label)
        ctx_layout.addWidget(self.context_combo)
        control_layout.addLayout(ctx_layout)

        # 分析目标
        goal_layout = QHBoxLayout()
        goal_layout.addWidget(QLabel("目标:"))
        self.goal_combo = QComboBox()
        self.goal_combo.setEditable(True)
        self.goal_combo.setFixedHeight(30)
        for goal in GOAL_OPTIONS:
            self.goal_combo.addItem(goal)
        goal_layout.addWidget(self.goal_combo)
        control_layout.addLayout(goal_layout)

        # 按钮区
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.analyze_btn = QPushButton("开始分析")
        self.analyze_btn.setFixedHeight(32)
        self.analyze_btn.setMinimumWidth(100)
        self.analyze_btn.clicked.connect(self._on_analyze_clicked)
        btn_layout.addWidget(self.analyze_btn)

        self.new_session_btn = QPushButton("新会话")
        self.new_session_btn.setFixedHeight(32)
        self.new_session_btn.clicked.connect(self.new_session_clicked.emit)
        btn_layout.addWidget(self.new_session_btn)

        control_layout.addLayout(btn_layout)
        layout.addWidget(control_group)

        # 结果显示区
        result_label = QLabel("分析结果 / 对话")
        result_label.setStyleSheet("color: #4a5568; font-weight: 600; padding: 4px 0;")
        layout.addWidget(result_label)

        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setPlaceholderText("分析结果将在这里显示...")
        layout.addWidget(self.result_view, stretch=1)

        # 底部输入区（多轮对话）
        input_widget = QWidget()
        input_widget.setFixedHeight(36)
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)
        input_layout.setAlignment(Qt.AlignVCenter)

        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("继续追问...")
        self.message_input.setFixedHeight(32)
        self.message_input.returnPressed.connect(self._on_send_message)
        input_layout.addWidget(self.message_input)

        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedHeight(32)
        self.send_btn.setMinimumWidth(60)
        self.send_btn.clicked.connect(self._on_send_message)
        input_layout.addWidget(self.send_btn)

        layout.addWidget(input_widget)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def append_stream_chunk(self, chunk: str) -> None:
        """追加流式输出内容"""
        cursor = self.result_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.result_view.setTextCursor(cursor)
        self.result_view.ensureCursorVisible()

    def append_result(self, content: str) -> None:
        """追加完整结果（带分隔符）"""
        self.result_view.append("\n---\n")
        self.result_view.append(content)
        self.result_view.append("\n")

    def clear_result(self) -> None:
        """清空结果区"""
        self.result_view.clear()

    def set_state(self, state: AnalysisState, message: str = "") -> None:
        """更新分析状态"""
        self._state = state

        if state == AnalysisState.IDLE:
            self.analyze_btn.setEnabled(True)
            self.send_btn.setEnabled(True)
        elif state == AnalysisState.STREAMING:
            self.analyze_btn.setEnabled(False)
            self.send_btn.setEnabled(False)
        elif state == AnalysisState.DONE:
            self.analyze_btn.setEnabled(True)
            self.send_btn.setEnabled(True)
        elif state == AnalysisState.ERROR:
            self.analyze_btn.setEnabled(True)
            self.send_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # 内部槽函数
    # ------------------------------------------------------------------

    def _on_analyze_clicked(self) -> None:
        ctx_label = self.context_combo.currentText()
        selector = CONTEXT_OPTIONS.get(ctx_label, ContextSelector.SELECTED)
        user_input = self.goal_combo.currentText().strip()

        # 判断模式：如果已有内容则是继续对话，否则是单次分析
        mode = AnalysisMode.CHAT if self.result_view.toPlainText().strip() else AnalysisMode.SINGLE

        self.analyze_clicked.emit(mode, selector, user_input)

    def _on_send_message(self) -> None:
        msg = self.message_input.text().strip()
        if msg:
            self.send_message_clicked.emit(msg)
            self.message_input.clear()
