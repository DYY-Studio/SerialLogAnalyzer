"""分析面板：目标与上下文选择、结果展示、追问与停止。

只与 :class:`AnalysisController` 交互：发出用户意图信号，接收结果快照与状态。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.models.analysis import (
    AnalysisMessage,
    AnalysisRequest,
    AnalysisResult,
    AnalysisState,
    ContextSelector,
    MessageRole,
)
from serial_log_analyzer.core.models.provider import ProviderProfile
from serial_log_analyzer.core.prompts.loader import PromptGoal

__all__ = ["AnalysisPanel"]

# 上下文选择项：(展示文案, 选择器)。
_CONTEXT_CHOICES: tuple[tuple[str, ContextSelector], ...] = (
    ("选中日志", ContextSelector.SELECTED),
    ("选中 + 前后各 10 行", ContextSelector.SELECTED_WITH_NEIGHBORS),
    ("最近 100 条", ContextSelector.RECENT),
    ("仅错误日志", ContextSelector.ERRORS_ONLY),
    ("手动输入", ContextSelector.MANUAL),
)


class _SubmitEdit(QPlainTextEdit):
    """多行输入框：Enter 发送，Shift+Enter 换行。"""

    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class AnalysisPanel(QWidget):
    """LLM 分析面板。

    参数:
        parent: 可选父对象。

    发送框只有一个：会话未开始时发首轮分析（目标 + 上下文 + 输入文本，文本可为空），
    已开始时发追问（只用文本，不再重复发送上下文），因此「目标 / 上下文」只在首轮生效。

    信号（由控制器连接）:
        analyze_requested(object): 携带 ``(AnalysisRequest, ContextSelector)``；
            上下文由控制器用 ``AnalysisContextBuilder`` 构造后填入请求。
        follow_up_requested(str): 追问文本。
        cancel_requested(): 请求取消。
        reset_requested(): 请求清空会话。
        profile_changed(str): 用户切换了 LLM Profile（携带 profile_id）。
    """

    analyze_requested = Signal(object)
    follow_up_requested = Signal(str)
    cancel_requested = Signal()
    reset_requested = Signal()
    profile_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._has_session = False
        self._streaming = False
        self._build()
        self.set_state(AnalysisState.IDLE)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def set_result(self, result: AnalysisResult) -> None:
        """展示累积后的完整结果快照，并刷新会话轮数。"""

        self.result_view.setPlainText(result.content)
        self._update_turns(result.conversation)
        self._has_session = bool(result.conversation)
        self._sync_enabled()
        usage = result.usage
        self.usage_label.setText(
            f"输入 {usage.input_tokens} / 输出 {usage.output_tokens} / 总计 {usage.total_tokens} tokens"
            if usage
            else ""
        )
        if result.state is AnalysisState.ERROR and result.error:
            self.status_label.setText(f"出错：{result.error}")

    def set_state(self, state: AnalysisState) -> None:
        """按分析状态切换按钮可用性与提示。"""

        self.status_label.setText(
            {
                AnalysisState.IDLE: "就绪",
                AnalysisState.STREAMING: "正在分析…",
                AnalysisState.DONE: "分析完成",
                AnalysisState.ERROR: "分析失败",
            }[state]
        )
        self._streaming = state is AnalysisState.STREAMING
        self.stop_btn.setEnabled(self._streaming)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        """按"是否流式中 / 是否已有会话"统一控件可用性。"""

        idle = not self._streaming
        self.send_btn.setEnabled(idle)
        self.new_session_btn.setEnabled(idle)
        # 追问不重复发送上下文，所以会话开始后目标与上下文不再生效，置灰避免静默忽略。
        first_turn = idle and not self._has_session
        self.goal_combo.setEnabled(first_turn)
        self.context_combo.setEnabled(first_turn)

    def set_goals(self, goals: list[PromptGoal]) -> None:
        """填充预设分析目标下拉列表。"""

        self.goal_combo.clear()
        for goal in goals:
            self.goal_combo.addItem(goal.display_name, goal.goal_id)

    def set_profiles(self, profiles: list[ProviderProfile], current: str = "") -> None:
        """填充 LLM Profile 下拉并选中 ``current``（不存在时选第一个）。"""

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in profiles:
            self.profile_combo.addItem(
                f"{profile.profile_id} · {profile.model}", profile.profile_id
            )
        index = self.profile_combo.findData(current)
        self.profile_combo.setCurrentIndex(index if index >= 0 else 0)
        self.profile_combo.blockSignals(False)

    def current_profile(self) -> str:
        """返回当前选中的 Profile 标识。"""

        return str(self.profile_combo.currentData() or "")

    def set_current_profile(self, profile_id: str) -> None:
        """在不触发信号的前提下把下拉切到指定 Profile。"""

        index = self.profile_combo.findData(profile_id)
        if index < 0:
            return
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # 构建与槽函数
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("模型:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("panel-profile")
        self.profile_combo.currentIndexChanged.connect(
            lambda _index: self.profile_changed.emit(self.current_profile())
        )
        profile_row.addWidget(self.profile_combo, stretch=1)
        layout.addLayout(profile_row)

        context_row = QHBoxLayout()
        context_row.addWidget(QLabel("上下文:"))
        self.context_combo = QComboBox()
        for label, selector in _CONTEXT_CHOICES:
            self.context_combo.addItem(label, selector)
        context_row.addWidget(self.context_combo)
        context_row.addStretch()
        layout.addLayout(context_row)

        goal_row = QHBoxLayout()
        goal_row.addWidget(QLabel("目标:"))
        self.goal_combo = QComboBox()
        goal_row.addWidget(self.goal_combo)
        goal_row.addStretch()
        layout.addLayout(goal_row)

        buttons = QHBoxLayout()
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.cancel_requested.emit)
        buttons.addWidget(self.stop_btn)
        self.new_session_btn = QPushButton("新会话")
        self.new_session_btn.clicked.connect(self._on_reset)
        buttons.addWidget(self.new_session_btn)
        self.copy_btn = QPushButton("复制结果")
        self.copy_btn.clicked.connect(self._on_copy)
        buttons.addWidget(self.copy_btn)
        layout.addLayout(buttons)

        status_row = QHBoxLayout()
        self.status_label = QLabel()
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        self.turns_label = QLabel()
        status_row.addWidget(self.turns_label)
        layout.addLayout(status_row)

        self.result_view = QPlainTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setPlaceholderText("分析结果将显示在这里")
        layout.addWidget(self.result_view, stretch=1)

        self.usage_label = QLabel()
        layout.addWidget(self.usage_label)

        input_row = QHBoxLayout()
        self.message_edit = _SubmitEdit()
        self.message_edit.setPlaceholderText("输入分析要求或追问；Enter 发送，Shift+Enter 换行")
        self.message_edit.setFixedHeight(84)
        self.message_edit.submitted.connect(self._on_send)
        input_row.addWidget(self.message_edit)
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

    def _on_send(self) -> None:
        """发送：会话未开始时作为首轮分析，已开始时作为追问。"""

        text = self.message_edit.toPlainText().strip()
        if self._has_session:
            if not text:
                return
            self.message_edit.clear()
            self.follow_up_requested.emit(text)
            return
        self.message_edit.clear()
        request = AnalysisRequest(
            goal_id=self.goal_combo.currentData(),
            user_input=text,
            context=None,
        )
        self.analyze_requested.emit((request, self.context_combo.currentData()))

    def _on_reset(self) -> None:
        self.result_view.clear()
        self.usage_label.clear()
        self.turns_label.clear()
        self.message_edit.clear()
        self._has_session = False
        self._sync_enabled()
        self.reset_requested.emit()

    def _update_turns(self, conversation: list[AnalysisMessage]) -> None:
        """按会话历史里的 user 消息数量显示轮数；空会话不显示。"""

        rounds = sum(1 for message in conversation if message.role is MessageRole.USER)
        self.turns_label.setText(f"当前会话 {rounds} 轮" if rounds else "")

    def _on_copy(self) -> None:
        self.result_view.selectAll()
        self.result_view.copy()
