"""SSE（Server-Sent Events）帧解析。

网络分块不保证与事件边界对齐：一条 ``data:`` 可能跨多个 ``readyRead``，
一次回调也可能包含多个事件。本类自维护文本缓冲，仅在遇到空行（事件分隔符）
时才产出一个完整的 :class:`StreamEvent`。
"""

from __future__ import annotations

from serial_log_analyzer.core.models.provider import StreamEvent

__all__ = ["SSEParser"]


class SSEParser:
    """增量式 SSE 解析器。

    参数:
        encoding: 文本编码，默认 ``utf-8``（对跨块多字节字符会等待完整序列）。
        max_event_bytes: 单事件最大字节数，超出时报错以防异常数据撑爆内存。
    """

    def __init__(self, *, encoding: str = "utf-8", max_event_bytes: int = 1048576) -> None:
        self._encoding = encoding
        self._max_event_bytes = max_event_bytes
        self._buffer = ""

    def feed(self, data: bytes) -> list[StreamEvent]:
        """输入字节分块，返回本次可完整解析的事件。

        参数:
            data: 网络层收到的原始字节。

        返回:
            完整事件列表；未完成部分保留在内部缓冲。

        异常:
            ResponseParseError: 字节不是合法 UTF-8，或单个事件超出上限。
        """

        raise NotImplementedError

    def finalize(self) -> list[StreamEvent]:
        """请求结束时调用，处理缓冲中的残余事件（服务端可能未发结束空行）。

        返回:
            残余事件列表。
        """

        raise NotImplementedError

    def reset(self) -> None:
        """清空缓冲，用于重试或新会话。"""

        self._buffer = ""
