"""分析服务：上下文构造、请求编排与流式结果组装。

这是 UI 与分析子系统之间的唯一入口。它把“用户想分析什么”翻译为一次 HTTP 请求，
并把响应增量通过普通回调逐步推送给调用方；不涉及任何 Qt 类型。

生命周期：一个 :class:`AnalysisService` 实例对应一个会话：
- :meth:`ask` 开始一轮新分析（单次模式会清空历史）；
- :meth:`follow_up` 在当前会话上追加一轮追问；
- :meth:`cancel` 中止进行中的请求；
- :meth:`reset` 清空会话历史。
"""

from __future__ import annotations

from collections.abc import Callable

from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.analysis import (
    AnalysisContext,
    AnalysisMessage,
    AnalysisRequest,
    AnalysisResult,
    ContextSelector,
)
from serial_log_analyzer.core.ports import HttpTransport
from serial_log_analyzer.core.prompts.loader import PromptLibrary
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver

__all__ = ["AnalysisContextBuilder", "AnalysisService", "AnalysisServiceHandlers"]

ResultHandler = Callable[[AnalysisResult], None]
DeltaHandler = Callable[[str], None]


class AnalysisContextBuilder:
    """把选中日志 / 最近日志 / 手动输入构造为 :class:`AnalysisContext`。

    参数:
        pipeline: 日志流水线（提供条目查询与渲染）。
    """

    def __init__(self, pipeline: LogPipeline) -> None:
        raise NotImplementedError

    def build(
        self,
        selector: ContextSelector,
        *,
        selected_sequences: list[int] | None = None,
        window: int = 10,
        recent_count: int = 100,
        manual_text: str = "",
    ) -> AnalysisContext:
        """按选择器构造上下文。

        参数:
            selector: 上下文来源。
            selected_sequences: 用户在表格中选中的条目序号。
            window: 前后扩展行数。
            recent_count: ``RECENT`` / ``ERRORS_ONLY`` 使用的条数上限。
            manual_text: ``MANUAL`` 时的用户输入。

        异常:
            ConfigError: 选择器要求的数据缺失（例如未选中任何行）。
        """

        raise NotImplementedError


class AnalysisServiceHandlers:
    """分析服务对外回调集合。

    参数:
        on_result: 结果快照更新（每次增量后调用，携带累积后的完整结果）。
        on_state: 状态变化（开始流式 / 完成 / 出错）。
        on_error: 错误通知。
    """

    def __init__(
        self,
        on_result: ResultHandler,
        on_state: Callable[[str], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        raise NotImplementedError


class AnalysisService:
    """单次分析与多轮对话的编排。

    参数:
        adapter: 目标 Adapter。
        transport: HTTP 传输实现（由 ``io`` 提供）。
        prompts: Prompt 模板库。
        credentials: 凭据解析器。
        handlers: 对外回调。
    """

    def __init__(
        self,
        adapter: JSONAdapter,
        transport: HttpTransport,
        prompts: PromptLibrary,
        credentials: CredentialResolver,
        handlers: AnalysisServiceHandlers,
    ) -> None:
        raise NotImplementedError

    @property
    def conversation(self) -> list[AnalysisMessage]:
        """当前会话的消息历史（只读副本）。"""

        raise NotImplementedError

    def ask(self, request: AnalysisRequest) -> None:
        """开始一轮新的分析；单次模式会清空既有历史。"""

        raise NotImplementedError

    def follow_up(self, text: str) -> None:
        """在当前会话中追加一轮追问。

        异常:
            ConfigError: 尚无会话历史。
        """

        raise NotImplementedError

    def cancel(self) -> None:
        """取消进行中的请求；未进行时为空操作。"""

        raise NotImplementedError

    def reset(self) -> None:
        """清空会话历史与结果。"""

        raise NotImplementedError

    def _on_chunk(self, data: bytes) -> None:
        """网络分块回调：SSE 解析 → 流式组装 → 推送增量。"""

        raise NotImplementedError

    def _on_done(self) -> None:
        """请求正常结束回调。"""

        raise NotImplementedError

    def _on_error(self, error: Exception) -> None:
        """请求失败回调。"""

        raise NotImplementedError
