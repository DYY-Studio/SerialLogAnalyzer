"""LLM 分析相关的领域模型。

分析过程保持简单：构造上下文 → 构造请求 → 请求模型 → 解析响应 → 展示结果。
v1 不设计复杂的 Agent 状态机，仅用 :class:`AnalysisState` 表示面板状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "AnalysisContext",
    "AnalysisMessage",
    "AnalysisMode",
    "AnalysisRequest",
    "AnalysisResult",
    "AnalysisState",
    "ContextSelector",
    "MessageRole",
    "TokenUsage",
]


class AnalysisMode(Enum):
    """分析交互形态。"""

    SINGLE = "single"
    CHAT = "chat"


class ContextSelector(Enum):
    """提交给模型的日志上下文来源。"""

    SELECTED = "selected"
    SELECTED_WITH_NEIGHBORS = "selected_with_neighbors"
    RECENT = "recent"
    ERRORS_ONLY = "errors_only"
    MANUAL = "manual"


class AnalysisState(Enum):
    """分析面板状态机取值。"""

    IDLE = "idle"
    STREAMING = "streaming"
    DONE = "done"
    ERROR = "error"


class MessageRole(Enum):
    """对话消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class AnalysisMessage:
    """一条对话消息。"""

    role: MessageRole
    content: str


@dataclass(frozen=True)
class AnalysisContext:
    """一次分析所用的日志上下文。

    参数:
        selector: 上下文来源方式。
        entries: 参与上下文的日志条目文本（已渲染，含级别与模块前缀）。
        window: ``SELECTED_WITH_NEIGHBORS`` 使用的前后行数。
        manual_text: ``MANUAL`` 时用户手工输入的文本。
    """

    selector: ContextSelector
    entries: tuple[str, ...] = ()
    window: int = 10
    manual_text: str = ""

    def render(self) -> str:
        """把上下文渲染为提交给模型的纯文本块。"""

        if self.manual_text:
            return self.manual_text
        return "\n".join(self.entries)


@dataclass(frozen=True)
class AnalysisRequest:
    """一次分析请求的用户意图描述。

    参数:
        mode: 单次或对话模式。
        goal_id: 选择的预设分析目标 ID；自由输入时为 ``None``。
        user_input: 用户自由输入文本（可选）。
        context: 日志上下文。
        temperature: 采样温度。
        max_output_tokens: 最大输出 token 数；``0`` 表示使用 Adapter 默认（不出现在请求体）。
    """

    mode: AnalysisMode = AnalysisMode.SINGLE
    goal_id: str | None = None
    user_input: str = ""
    context: AnalysisContext | None = None
    temperature: float = 0.2
    max_output_tokens: int = 0


@dataclass(frozen=True)
class TokenUsage:
    """模型返回的用量统计；字段缺失时为 ``0``。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class AnalysisResult:
    """分析结果，支持流式增量累积。

    参数:
        content: 正文（流式过程中不断追加）。
        reasoning: 思考正文（部分模型返回），无则为 ``None``。
        usage: 用量统计。
        state: 当前状态。
        error: ``state == ERROR`` 时的用户可读错误信息。
    """

    content: str = ""
    reasoning: str | None = None
    usage: TokenUsage | None = None
    state: AnalysisState = AnalysisState.IDLE
    error: str | None = None
    conversation: list[AnalysisMessage] = field(default_factory=list)
