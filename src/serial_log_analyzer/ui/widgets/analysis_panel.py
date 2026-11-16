"""分析面板：目标与上下文选择、结果展示、追问与停止。

只与 :class:`AnalysisController` 交互：发出用户意图信号，接收结果快照与状态。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
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
    TokenUsage,
)
from serial_log_analyzer.core.models.provider import ProviderProfile
from serial_log_analyzer.core.prompts.loader import PromptGoal
from serial_log_analyzer.ui.icons import render_icon
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens
from serial_log_analyzer.ui.widgets.chat_view import ChatView

__all__ = ["AnalysisPanel"]

# 上下文选择项：(展示文案, 选择器)。
_CONTEXT_CHOICES: tuple[tuple[str, ContextSelector], ...] = (
    ("选中日志", ContextSelector.SELECTED),
    ("选中 + 前后各 10 行", ContextSelector.SELECTED_WITH_NEIGHBORS),
    ("最近 100 条", ContextSelector.RECENT),
    ("仅错误日志", ContextSelector.ERRORS_ONLY),
    ("无", ContextSelector.NONE),
)

_BOARD_PROMPT_PREVIEW_LIMIT = 180


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
        export_report_requested(): 请求导出结构化诊断报告。
        board_prompt_toggled(bool): 用户切换「注入板级说明」开关（携带是否启用）。
    """

    analyze_requested = Signal(object)
    follow_up_requested = Signal(str)
    cancel_requested = Signal()
    reset_requested = Signal()
    profile_changed = Signal(str)
    export_report_requested = Signal()
    board_prompt_toggled = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        tokens: ThemeTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens if tokens is not None else default_tokens()
        self._has_session = False
        self._streaming = False
        self._has_board_prompt = False
        self._board_prompt_pref = True
        self._build()
        self.set_theme_tokens(self._tokens)
        self.set_state(AnalysisState.IDLE)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def set_theme_tokens(self, tokens: ThemeTokens) -> None:
        """按主题 Token 刷新按钮图标与对话卡片样式。"""

        self._tokens = tokens
        self.new_session_btn.setIcon(render_icon("new-session", tokens.text_secondary, size=14))
        self.copy_btn.setIcon(render_icon("copy", tokens.text_secondary, size=14))
        self.export_report_btn.setIcon(render_icon("export", tokens.text_secondary, size=14))
        self.send_btn.setIcon(render_icon("send", tokens.text_on_accent, size=14))
        self.stop_btn.setIcon(render_icon("stop", tokens.danger, size=14))
        self.chat.set_theme_tokens(tokens)

    def set_result(self, result: AnalysisResult) -> None:
        """展示累积后的结果快照：转录按轮次刷新，并更新轮数与用量。"""

        self.chat.render(result)
        self._update_turns(result.conversation)
        self._has_session = bool(result.conversation)
        self._sync_enabled()
        usage_text = self._usage_text(result.usage)
        self.usage_label.setText(usage_text)
        self.usage_label.setVisible(bool(usage_text))
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
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        """按"是否流式中 / 是否已有会话"统一控件可用性与发/停槽位。"""

        idle = not self._streaming
        self.send_btn.setEnabled(idle)
        self.stop_btn.setEnabled(self._streaming)
        self._action_stack.setCurrentWidget(self.stop_btn if self._streaming else self.send_btn)
        self.new_session_btn.setEnabled(idle)
        # 追问不重复发送上下文，所以会话开始后目标与上下文不再生效，置灰并折叠成摘要条。
        first_turn = idle and not self._has_session
        self.goal_combo.setEnabled(first_turn)
        self.context_combo.setEnabled(first_turn)
        self.board_prompt_box.setEnabled(first_turn and self._has_board_prompt)
        self._scope_widget.setVisible(not self._has_session)
        self._scope_summary.setVisible(self._has_session)
        if self._has_session:
            board_note = "含板级说明" if self.include_board_prompt() else "不含板级说明"
            self._scope_summary.setText(
                f"首轮范围：{self.goal_combo.currentText()} · {self.context_combo.currentText()}"
                f" · {board_note}"
            )

    def set_board_prompt(self, preset_name: str, prompt: str) -> None:
        """设置当前 Preset 的板级说明，并同步「注入板级说明」复选框状态与提示。

        当 ``prompt`` 去除首尾空白后为空时，保留用户原有的全局勾选偏好，但把复选框
        视觉置灰并取消勾选（不触发 ``board_prompt_toggled``）。

        参数:
            preset_name: 当前日志 Preset 展示名称。
            prompt: Preset 声明的板级系统提示词。
        """

        cleaned = prompt.strip()
        self._has_board_prompt = bool(cleaned)
        self._sync_board_prompt_box()
        self.board_prompt_box.setToolTip(self._format_board_prompt_tooltip(preset_name, cleaned))
        self._sync_enabled()

    def set_include_board_prompt(self, enabled: bool) -> None:
        """更新「注入板级说明」首选项并同步复选框（不触发变更信号）。

        参数:
            enabled: 用户是否偏好在新建会话时注入板级说明。
        """

        self._board_prompt_pref = bool(enabled)
        self._sync_board_prompt_box()
        self._sync_enabled()

    def include_board_prompt(self) -> bool:
        """返回当前新建会话时是否实际注入板级说明。"""

        return bool(self._has_board_prompt and self._board_prompt_pref)

    def _sync_board_prompt_box(self) -> None:
        """在不触发信号的前提下把复选框勾选状态同步为当前生效开关。"""

        self.board_prompt_box.blockSignals(True)
        self.board_prompt_box.setChecked(self.include_board_prompt())
        self.board_prompt_box.blockSignals(False)

    @staticmethod
    def _format_board_prompt_tooltip(preset_name: str, prompt: str) -> str:
        """构造「注入板级说明」复选框的悬停提示文本。"""

        if not prompt:
            return "当前 Preset 未配置板级说明"
        preview = (
            prompt
            if len(prompt) <= _BOARD_PROMPT_PREVIEW_LIMIT
            else f"{prompt[:_BOARD_PROMPT_PREVIEW_LIMIT]}…"
        )
        title = preset_name.strip() or "当前 Preset"
        return f"「{title}」板级说明（新建会话时注入）：\n{preview}"

    def set_details_expanded(self, expanded: bool) -> None:
        """设置「思考 / 参考内容」折叠块的默认展开状态。"""

        self.chat.set_details_expanded(expanded)

    def set_goals(self, goals: list[PromptGoal]) -> None:
        """填充预设分析目标下拉列表；首项「无」= 不套目标模板，缺省仍选第一个真实目标。"""

        self.goal_combo.clear()
        self.goal_combo.addItem("无", "")
        for goal in goals:
            self.goal_combo.addItem(goal.display_name, goal.goal_id)
        if goals:
            self.goal_combo.setCurrentIndex(1)

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
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("panel-profile")
        self.profile_combo.setMinimumWidth(120)
        self.profile_combo.setToolTip("切换当前 LLM Profile")
        self.profile_combo.currentIndexChanged.connect(
            lambda _index: self.profile_changed.emit(self.current_profile())
        )
        header_row.addWidget(self.profile_combo, stretch=1)

        self.new_session_btn = QPushButton("新会话")
        self.new_session_btn.setProperty("variant", "ghost")
        self.new_session_btn.setToolTip("清空历史并开始新会话")
        self.new_session_btn.setIconSize(QSize(14, 14))
        self.new_session_btn.clicked.connect(self._on_reset)
        header_row.addWidget(self.new_session_btn)

        self.copy_btn = QPushButton("复制")
        self.copy_btn.setProperty("variant", "ghost")
        self.copy_btn.setToolTip("复制全部会话 Markdown 原文")
        self.copy_btn.setIconSize(QSize(14, 14))
        self.copy_btn.clicked.connect(self._on_copy)
        header_row.addWidget(self.copy_btn)

        self.export_report_btn = QPushButton("报告")
        self.export_report_btn.setObjectName("panel-export-report")
        self.export_report_btn.setProperty("variant", "ghost")
        self.export_report_btn.setToolTip("导出诊断报告（Markdown / JSON）")
        self.export_report_btn.setIconSize(QSize(14, 14))
        self.export_report_btn.clicked.connect(self.export_report_requested.emit)
        header_row.addWidget(self.export_report_btn)
        layout.addLayout(header_row)

        self._scope_widget = QWidget()
        scope_layout = QVBoxLayout(self._scope_widget)
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(4)

        scope_row = QHBoxLayout()
        scope_row.setContentsMargins(0, 0, 0, 0)
        scope_row.setSpacing(6)

        goal_col = QVBoxLayout()
        goal_col.setSpacing(2)
        goal_lbl = QLabel("目标")
        goal_lbl.setProperty("role", "muted-caption")
        goal_col.addWidget(goal_lbl)
        self.goal_combo = QComboBox()
        goal_col.addWidget(self.goal_combo)
        scope_row.addLayout(goal_col, stretch=1)

        ctx_col = QVBoxLayout()
        ctx_col.setSpacing(2)
        ctx_lbl = QLabel("上下文")
        ctx_lbl.setProperty("role", "muted-caption")
        ctx_col.addWidget(ctx_lbl)
        self.context_combo = QComboBox()
        for label, selector in _CONTEXT_CHOICES:
            self.context_combo.addItem(label, selector)
        ctx_col.addWidget(self.context_combo)
        scope_row.addLayout(ctx_col, stretch=1)
        scope_layout.addLayout(scope_row)

        self.board_prompt_box = QCheckBox("注入板级说明")
        self.board_prompt_box.setObjectName("panel-board-prompt")
        self.board_prompt_box.setChecked(True)
        self.board_prompt_box.setToolTip("当前 Preset 未配置板级说明")
        self.board_prompt_box.toggled.connect(self._on_board_prompt_toggled)
        scope_layout.addWidget(self.board_prompt_box)
        layout.addWidget(self._scope_widget)

        self._scope_summary = QLabel()
        self._scope_summary.setProperty("role", "muted-caption")
        self._scope_summary.setWordWrap(True)
        self._scope_summary.setVisible(False)
        layout.addWidget(self._scope_summary)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_label = QLabel()
        self.status_label.setProperty("role", "muted-caption")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        self.turns_label = QLabel()
        self.turns_label.setProperty("role", "status-pill")
        self.turns_label.setVisible(False)
        status_row.addWidget(self.turns_label)
        layout.addLayout(status_row)

        self.chat = ChatView()
        layout.addWidget(self.chat, stretch=1)

        self.usage_label = QLabel()
        self.usage_label.setProperty("role", "muted-caption")
        self.usage_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.usage_label.setVisible(False)
        layout.addWidget(self.usage_label)

        composer = QFrame()
        composer.setObjectName("chat-composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(6, 4, 6, 6)
        composer_layout.setSpacing(4)

        self.message_edit = _SubmitEdit()
        self.message_edit.setFrameShape(QFrame.Shape.NoFrame)
        self.message_edit.setStyleSheet("QPlainTextEdit { border: none; background: transparent; padding: 2px; }")
        self.message_edit.setPlaceholderText("输入分析要求或追问；Enter 发送，Shift+Enter 换行")
        self.message_edit.setMinimumHeight(54)
        self.message_edit.setMaximumHeight(82)
        self.message_edit.submitted.connect(self._on_send)
        composer_layout.addWidget(self.message_edit)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        hint = QLabel("Enter 发送 · Shift+Enter 换行")
        hint.setProperty("role", "muted-caption")
        footer.addWidget(hint)
        footer.addStretch()

        self._action_stack = QStackedWidget()
        self.send_btn = QPushButton("发送")
        self.send_btn.setProperty("variant", "primary")
        self.send_btn.setIconSize(QSize(14, 14))
        self.send_btn.clicked.connect(self._on_send)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setIconSize(QSize(14, 14))
        self.stop_btn.clicked.connect(self.cancel_requested.emit)
        self._action_stack.addWidget(self.send_btn)
        self._action_stack.addWidget(self.stop_btn)
        self._action_stack.setFixedHeight(self.send_btn.sizeHint().height())
        footer.addWidget(self._action_stack)
        composer_layout.addLayout(footer)
        layout.addWidget(composer)

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
            include_board_prompt=self.include_board_prompt(),
        )
        self.analyze_requested.emit((request, self.context_combo.currentData()))

    def _on_board_prompt_toggled(self, checked: bool) -> None:
        """响应用户切换「注入板级说明」复选框，仅在存在板级说明时更新偏好并通知外部。"""

        if not self._has_board_prompt:
            return
        self._board_prompt_pref = bool(checked)
        self._sync_enabled()
        self.board_prompt_toggled.emit(bool(checked))

    def _on_reset(self) -> None:
        self.chat.clear()
        self.usage_label.clear()
        self.usage_label.setVisible(False)
        self.turns_label.clear()
        self.turns_label.setVisible(False)
        self.message_edit.clear()
        self._has_session = False
        self._sync_enabled()
        self.reset_requested.emit()

    def _update_turns(self, conversation: list[AnalysisMessage]) -> None:
        """按会话历史里的 user 消息数量显示轮数；空会话不显示。"""

        rounds = sum(1 for message in conversation if message.role is MessageRole.USER)
        text = f"当前会话 {rounds} 轮" if rounds else ""
        self.turns_label.setText(text)
        self.turns_label.setVisible(bool(text))

    @staticmethod
    def _usage_text(usage: TokenUsage | None) -> str:
        """用量文案；Provider 报了缓存命中时把它标在输入后面。"""

        if usage is None:
            return ""
        cached = f"（缓存 {usage.cached_tokens}）" if usage.cached_tokens else ""
        return (
            f"输入 {usage.input_tokens}{cached} / 输出 {usage.output_tokens}"
            f" / 总计 {usage.total_tokens} tokens"
        )

    def _on_copy(self) -> None:
        QGuiApplication.clipboard().setText(self.chat.plain_text())
