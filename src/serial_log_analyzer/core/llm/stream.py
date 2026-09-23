"""流式响应组装：把 SSE 事件序列转换为正文增量与结束状态。

职责：
- 接收 :class:`StreamEvent`，交给 Adapter 提取正文 / 思考增量；
- 处理终止哨兵与终止条件；
- 识别服务端错误事件；
- 累积用量统计；
- 以回调形式向调用方（``AnalysisService``）推送增量。
"""

from __future__ import annotations

from collections.abc import Callable

from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.models.provider import StreamEvent

__all__ = ["StreamOutcome", "StreamProcessor"]

DeltaHandler = Callable[[str], None]
ReasoningHandler = Callable[[str], None]


class StreamOutcome:
    """单个事件的处理结果类型。"""

    DELTA = "delta"
    TERMINAL = "terminal"
    ERROR = "error"
    IGNORED = "ignored"


class StreamProcessor:
    """把流式事件组装为分析结果。

    参数:
        adapter: 目标 Adapter（提供增量提取与终止判断）。
        on_delta: 收到正文增量时的回调。
        on_reasoning: 收到思考正文增量时的回调；无则忽略思考内容。
        on_usage: 完整用量可用时的回调。
    """

    def __init__(
        self,
        adapter: JSONAdapter,
        on_delta: DeltaHandler,
        on_reasoning: ReasoningHandler | None = None,
        on_usage: Callable[[int, int, int], None] | None = None,
    ) -> None:
        raise NotImplementedError

    def handle(self, event: StreamEvent) -> str:
        """处理单个事件。

        返回:
            :class:`StreamOutcome` 中的取值，供调用方决定是否继续。

        异常:
            ResponseParseError: 事件 JSON 非法或增量类型不是字符串。
        """

        raise NotImplementedError

    @property
    def finished(self) -> bool:
        """是否已收到终止事件或错误事件。"""

        raise NotImplementedError

    def finalize(self, *, clean_eof: bool) -> None:
        """输入结束时收尾。

        参数:
            clean_eof: 是否是连接正常关闭（未收到显式终止事件）。

        异常:
            ResponseParseError: 既无终止事件又非正常关闭，且 Adapter 不允许干净 EOF。
        """

        raise NotImplementedError
