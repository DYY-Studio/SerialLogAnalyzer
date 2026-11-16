"""分析结果区：按轮次展示的对话转录，思考与参考内容可折叠。

只做展示，数据全部来自 :class:`AnalysisResult` 快照：已定稿的轮次来自 ``conversation``，
尚未定稿的一轮用流式 ``content`` / ``reasoning`` 更新最后一张卡片。
思考不进请求，但留在卡片上，所以历史轮次的思考在界面里仍然看得到。

文本按 Markdown 渲染（:class:`MarkdownRenderer`），但卡片上同时留着 Markdown 原文，
「复制结果」导出的是原文而不是渲染后的 HTML。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
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
from serial_log_analyzer.ui.icons import render_icon, render_pixmap
from serial_log_analyzer.ui.markdown import MarkdownRenderer
from serial_log_analyzer.ui.theme import ThemeTokens, default_tokens

__all__ = ["ChatView"]

_ROLE_TITLES = {MessageRole.USER: "你", MessageRole.ASSISTANT: "LLM"}
_THINKING_TITLE = "思考"
_CONTEXT_TITLE = "参考内容"
_EMPTY_HINT = "分析结果将显示在这里"
_BOTTOM_SLACK = 4  # 距底部多少像素以内算「贴底」


class _CollapsibleBlock(QFrame):
    """可折叠的一段正文：标题按钮 + 自动换行、可复制的 Markdown 文本。"""

    def __init__(
        self,
        title: str,
        *,
        renderer: MarkdownRenderer,
        tokens: ThemeTokens,
        expanded: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("collapsible-block")
        self._title = title
        self._renderer = renderer
        self._tokens = tokens
        self._text = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 6)
        layout.setSpacing(3)

        self._apply_palette(renderer)

        self._toggle = QToolButton()
        self._toggle.setProperty("role", "disclosure")
        self._toggle.setCheckable(True)
        self._toggle.setAutoRaise(True)
        self._toggle.setText(title)
        self._toggle.setIconSize(QSize(12, 12))
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._body)

        self.setVisible(False)  # 没有内容时整块不出现（set_text 会按内容显隐）
        self._toggle.setChecked(expanded)  # 触发 _on_toggled 同步图标与可见性
        self._sync_chevron(expanded)

    @property
    def title(self) -> str:
        """折叠块标题。"""

        return self._title

    def text(self) -> str:
        """折叠块正文的 Markdown 原文（与是否展开无关）。"""

        return self._text

    def set_text(self, text: str) -> None:
        """更新正文；空文本时整块隐藏。"""

        self._text = text
        self._body.setText(self._renderer.html(text))
        self.setVisible(bool(text))

    def set_expanded(self, expanded: bool) -> None:
        """设置展开状态（不改变折叠块的可见性）。"""

        self._toggle.setChecked(bool(expanded))

    def is_expanded(self) -> bool:
        """返回当前是否展开。"""

        return self._toggle.isChecked()

    def refresh_theme(self, renderer: MarkdownRenderer, tokens: ThemeTokens) -> None:
        """按新渲染器刷新容器配色、图标与已渲染的 Markdown 正文。"""

        self._renderer = renderer
        self._tokens = tokens
        self._apply_palette(renderer)
        self._sync_chevron(self._toggle.isChecked())
        if self._text:
            self._body.setText(renderer.html(self._text))

    def _apply_palette(self, renderer: MarkdownRenderer) -> None:
        # 次要材料：淡底色 + 灰字，和正文区分开。底色比代码块再淡一档，
        # 否则块内的代码块与容器同色、看不出边界。
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, renderer.faint)
        palette.setColor(QPalette.ColorRole.Text, renderer.muted)
        palette.setColor(QPalette.ColorRole.WindowText, renderer.muted)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

    def _on_toggled(self, expanded: bool) -> None:
        self._body.setVisible(expanded)
        self._sync_chevron(expanded)

    def _sync_chevron(self, expanded: bool) -> None:
        name = "chevron-down" if expanded else "chevron-right"
        self._toggle.setIcon(render_icon(name, self._tokens.text_muted, size=12))


class _TurnCard(QFrame):
    """一轮对话：角色徽章 + 单轮复制 + 可折叠细节（思考 / 参考内容）+ 正文。"""

    def __init__(
        self,
        role: MessageRole,
        *,
        renderer: MarkdownRenderer,
        tokens: ThemeTokens,
        expanded: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("turn-card")
        self.setProperty("role", "assistant" if role is MessageRole.ASSISTANT else "user")
        self.role = role
        self._renderer = renderer
        self._tokens = tokens
        self._body_text = ""
        detail_title = _THINKING_TITLE if role is MessageRole.ASSISTANT else _CONTEXT_TITLE
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.title = QLabel(_ROLE_TITLES[role])
        self.title.setProperty("role", "card-badge")
        header.addWidget(self.title)
        header.addStretch()
        self.copy_card_btn = QToolButton()
        self.copy_card_btn.setToolTip("复制本轮正文原文")
        self.copy_card_btn.setIconSize(QSize(13, 13))
        self.copy_card_btn.clicked.connect(self._copy_body)
        header.addWidget(self.copy_card_btn)
        layout.addLayout(header)

        self.detail = _CollapsibleBlock(
            detail_title, renderer=renderer, tokens=tokens, expanded=expanded
        )
        layout.addWidget(self.detail)

        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.body)
        self._sync_copy_icon()

    def set_detail(self, text: str) -> None:
        """更新细节块（思考 / 参考内容）。"""

        self.detail.set_text(text)

    def body_text(self) -> str:
        """正文的 Markdown 原文（界面里显示的是渲染结果）。"""

        return self._body_text

    def set_body(self, text: str) -> None:
        """更新正文（用户轮为摘要，LLM 轮为回答）。"""

        self._body_text = text
        self.body.setText(self._renderer.html(text))

    def set_details_expanded(self, expanded: bool) -> None:
        self.detail.set_expanded(expanded)

    def refresh_theme(self, renderer: MarkdownRenderer, tokens: ThemeTokens) -> None:
        """使用新渲染器刷新细节块、图标与正文。"""

        self._renderer = renderer
        self._tokens = tokens
        self._sync_copy_icon()
        self.detail.refresh_theme(renderer, tokens)
        if self._body_text:
            self.body.setText(renderer.html(self._body_text))

    def _copy_body(self) -> None:
        if self._body_text:
            QGuiApplication.clipboard().setText(self._body_text)

    def _sync_copy_icon(self) -> None:
        self.copy_card_btn.setIcon(render_icon("copy", self._tokens.text_muted, size=13))


class ChatView(QScrollArea):
    """按轮次堆叠卡片的分析结果区。

    参数:
        parent: 可选父对象。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chat-view")
        self._expanded = False
        self._tokens: ThemeTokens = default_tokens()
        self._md = MarkdownRenderer(self.palette(), self.font().pointSizeF())
        self._cards: list[_TurnCard] = []
        self._message_cards: list[_TurnCard] = []
        self._live: _TurnCard | None = None
        self._follow = True
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self._on_value_changed)
        bar.rangeChanged.connect(self._on_range_changed)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)  # 结果区整体要有一圈边框，便于辨认
        # 输出区至少要能看几轮对话，避免被日志/命令面板挤扁（停靠面板会尊重这个下限）。
        self.setMinimumHeight(160)

        body = QWidget()
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(8)
        self._empty_box = QWidget()
        empty_layout = QVBoxLayout(self._empty_box)
        empty_layout.setContentsMargins(12, 24, 12, 16)
        empty_layout.setSpacing(6)
        self._empty_icon = QLabel()
        self._empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_icon)
        self._hint = QLabel(_EMPTY_HINT)
        self._hint.setObjectName("chat-empty-title")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._hint)
        sub_hint = QLabel("在左侧日志表选中关键行，选择目标后按 Enter 开始诊断")
        sub_hint.setObjectName("chat-empty-hint")
        sub_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_hint.setWordWrap(True)
        empty_layout.addWidget(sub_hint)
        self._layout.addWidget(self._empty_box)
        self._layout.addStretch(1)
        self.setWidget(body)
        self._sync_empty_icon()

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def set_details_expanded(self, expanded: bool) -> None:
        """设置「思考 / 参考内容」折叠块的默认展开状态，并应用到已有卡片。"""

        self._expanded = bool(expanded)
        for card in self._cards:
            card.set_details_expanded(self._expanded)

    def set_theme_tokens(self, tokens: ThemeTokens) -> None:
        """更新主题 Token 并同步重绘已有对话卡片。"""

        self._tokens = tokens
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """按当前主题 Token 或调色板重建 Markdown 渲染器并重绘已有卡片。"""

        palette = QPalette(self.palette())
        palette.setColor(QPalette.ColorRole.Base, QColor(self._tokens.bg_surface))
        palette.setColor(QPalette.ColorRole.Text, QColor(self._tokens.text_primary))
        palette.setColor(QPalette.ColorRole.Link, QColor(self._tokens.accent_primary))
        self._md = MarkdownRenderer(palette, self.font().pointSizeF())
        self._sync_empty_icon()
        for card in self._cards:
            card.refresh_theme(self._md, self._tokens)

    def _sync_empty_icon(self) -> None:
        self._empty_icon.setPixmap(
            render_pixmap("search", self._tokens.text_muted, size=24, dpr=2.0)
        )

    def render(self, result: AnalysisResult) -> None:
        """按结果快照刷新转录（已定稿轮次按会话补卡片，未定稿一轮就地更新）。"""

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

        self._empty_box.setVisible(not self._cards)
        if appended:  # 新一轮出现时重新贴底跟随
            self._follow = True

    def _on_value_changed(self, value: int) -> None:
        """滚动位置变化：贴底就继续跟随，用户手动往上滚则暂停跟随。"""

        bar = self.verticalScrollBar()
        self._follow = value >= bar.maximum() - _BOTTOM_SLACK

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        """内容长高后跟随到底。

        必须在 ``rangeChanged``（布局重算完成）里做：``render`` 末尾直接
        ``setValue(maximum())`` 拿到的是重算前的旧上限，等于每次都被设回原位，
        于是流式期间一直停在上面不动。
        """

        if self._follow:
            self.verticalScrollBar().setValue(maximum)

    def plain_text(self) -> str:
        """把整段转录导出为 Markdown 原文（忽略折叠状态），供「复制结果」使用。"""

        blocks: list[str] = []
        for card in self._cards:
            parts = [f"【{card.title.text()}】"]
            if card.detail.text():
                parts.append(f"【{card.detail.title}】{card.detail.text()}")
            parts.append(card.body_text())
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
        self._follow = True
        self._empty_box.setVisible(True)

    # ------------------------------------------------------------------

    def _append_card(self, message: AnalysisMessage) -> _TurnCard:
        """按消息落一张卡片，插在末尾（卡片区尾部有 stretch）。"""

        card = _TurnCard(
            message.role,
            renderer=self._md,
            tokens=self._tokens,
            expanded=self._expanded,
        )
        if message.role is MessageRole.USER:
            card.set_body(message.summary or message.content)
            if message.content.strip() != (message.summary or "").strip():
                card.set_detail(message.content)
        else:
            card.set_body(message.content)
        self._cards.append(card)
        self._layout.insertWidget(self._layout.count() - 1, card)
        return card
