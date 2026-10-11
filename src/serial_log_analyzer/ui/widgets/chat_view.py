"""分析结果区：按轮次展示的对话转录，思考与参考内容可折叠。

只做展示，数据全部来自 :class:`AnalysisResult` 快照：已定稿的轮次来自 ``conversation``，
尚未定稿的一轮用流式 ``content`` / ``reasoning`` 更新最后一张卡片。
思考不进请求，但留在卡片上，所以历史轮次的思考在界面里仍然看得到。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.models.analysis import (
    AnalysisMessage,
    AnalysisResult,
    AnalysisState,
    MessageRole,
)

__all__ = ["ChatView"]

_ROLE_TITLES = {MessageRole.USER: "你", MessageRole.ASSISTANT: "LLM"}
_THINKING_TITLE = "思考"
_CONTEXT_TITLE = "参考内容"
_EMPTY_HINT = "分析结果将显示在这里"


class _CollapsibleBlock(QWidget):
    """可折叠的一段正文：标题按钮 + 自动换行、可复制的只读文本。"""

    def __init__(self, title: str, *, expanded: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setAutoRaise(True)
        self._toggle.setText(title)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._body)

        self.setVisible(False)  # 没有内容时整块不出现（set_text 会按内容显隐）
        self._toggle.setChecked(expanded)  # 触发 _on_toggled 同步箭头与可见性

    @property
    def title(self) -> str:
        """折叠块标题。"""

        return self._title

    def text(self) -> str:
        """折叠块正文（与是否展开无关）。"""

        return self._body.text()

    def set_text(self, text: str) -> None:
        """更新正文；空文本时整块隐藏。"""

        self._body.setText(text)
        self.setVisible(bool(text))

    def set_expanded(self, expanded: bool) -> None:
        """设置展开状态（不改变折叠块的可见性）。"""

        self._toggle.setChecked(bool(expanded))

    def is_expanded(self) -> bool:
        """返回当前是否展开。"""

        return self._toggle.isChecked()

    def _on_toggled(self, expanded: bool) -> None:
        self._body.setVisible(expanded)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )


class _TurnCard(QFrame):
    """一轮对话：角色标题 + 可折叠的细节（思考 / 参考内容）+ 正文。"""

    def __init__(self, role: MessageRole, *, expanded: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        detail_title = _THINKING_TITLE if role is MessageRole.ASSISTANT else _CONTEXT_TITLE
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        self.title = QLabel(_ROLE_TITLES[role])
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        layout.addWidget(self.title)

        self.detail = _CollapsibleBlock(detail_title, expanded=expanded)
        layout.addWidget(self.detail)

        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.body)

    def set_detail(self, text: str) -> None:
        """更新细节块（思考 / 参考内容）。"""

        self.detail.set_text(text)

    def set_body(self, text: str) -> None:
        """更新正文（用户轮为摘要，LLM 轮为回答）。"""

        self.body.setText(text)

    def set_details_expanded(self, expanded: bool) -> None:
        self.detail.set_expanded(expanded)


class ChatView(QScrollArea):
    """按轮次堆叠卡片的分析结果区。

    参数:
        parent: 可选父对象。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded = False
        self._cards: list[_TurnCard] = []
        self._message_cards: list[_TurnCard] = []
        self._live: _TurnCard | None = None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)  # 结果区整体要有一圈边框，便于辨认
        # 输出区至少要能看几轮对话，避免被日志/命令面板挤扁（停靠面板会尊重这个下限）。
        self.setMinimumHeight(160)

        body = QWidget()
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(6)
        self._hint = QLabel(_EMPTY_HINT)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._hint)
        self._layout.addStretch(1)
        self.setWidget(body)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def set_details_expanded(self, expanded: bool) -> None:
        """设置「思考 / 参考内容」折叠块的默认展开状态，并应用到已有卡片。"""

        self._expanded = bool(expanded)
        for card in self._cards:
            card.set_details_expanded(self._expanded)

    def render(self, result: AnalysisResult) -> None:
        """按结果快照刷新转录（已定稿轮次按会话补卡片，未定稿一轮就地更新）。"""

        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        streaming = result.state is AnalysisState.STREAMING
        pending = list(result.conversation[len(self._message_cards) :])

        # 本轮结束：成功时把流式卡片收编为这一条 assistant 消息的卡片，
        # 出错 / 取消时把它留作历史卡片（可能带部分正文）。
        if self._live is not None and not streaming:
            live = self._live
            self._live = None
            if pending and pending[-1].role is MessageRole.ASSISTANT:
                live.set_body(pending[-1].content)
                self._message_cards.append(live)
                pending = pending[:-1]

        appended = bool(pending)
        for message in pending:
            self._message_cards.append(self._append_card(message))

        if streaming:
            if self._live is None:
                self._live = self._append_card(
                    AnalysisMessage(MessageRole.ASSISTANT, "")
                )
                appended = True
            self._live.set_detail(result.reasoning or "")
            self._live.set_body(result.content)

        self._hint.setVisible(not self._cards)
        if appended or at_bottom:
            bar.setValue(bar.maximum())

    def plain_text(self) -> str:
        """把整段转录导出为纯文本（忽略折叠状态），供「复制结果」使用。"""

        blocks: list[str] = []
        for card in self._cards:
            parts = [f"【{card.title.text()}】"]
            if card.detail.text():
                parts.append(f"【{card.detail.title}】{card.detail.text()}")
            parts.append(card.body.text())
            blocks.append("\n".join(parts))
        return "\n\n".join(blocks)

    def clear(self) -> None:
        """清空全部卡片（新会话）。"""

        for card in self._cards:
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._message_cards.clear()
        self._live = None
        self._hint.setVisible(True)

    # ------------------------------------------------------------------

    def _append_card(self, message: AnalysisMessage) -> _TurnCard:
        """按消息落一张卡片，插在末尾（卡片区尾部有 stretch）。"""

        card = _TurnCard(message.role, expanded=self._expanded)
        if message.role is MessageRole.USER:
            card.set_body(message.summary or message.content)
            if message.content.strip() != (message.summary or "").strip():
                card.set_detail(message.content)
        else:
            card.set_body(message.content)
        self._cards.append(card)
        self._layout.insertWidget(self._layout.count() - 1, card)
        return card
