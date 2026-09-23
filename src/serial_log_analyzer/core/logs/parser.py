"""日志解析器：把文本行转换为 :class:`LogEntry`。

解析流程（单行）：
1. 用 Preset 行规则匹配；
2. 命中则提取 level / module / message / time 与额外命名组；
3. 未命中时：若匹配 continuation 规则且上一条存在，则并入上一条；
4. 否则按 fallback 规则生成 ``UNKNOWN`` 条目（原始文本保留在 ``raw``）。
"""

from __future__ import annotations

from serial_log_analyzer.core.logs.preset import LogPreset
from serial_log_analyzer.core.models.logs import LogEntry

__all__ = ["LogParser", "ParseOutcome", "ParseResult"]


class ParseOutcome:
    """单行解析结果的三种可能。"""

    MATCHED = "matched"
    CONTINUATION = "continuation"
    FALLBACK = "fallback"
    IGNORED = "ignored"


class ParseResult:
    """单行解析结果。

    参数:
        outcome: 见 :class:`ParseOutcome`。
        entry: 新条目（``MATCHED`` / ``FALLBACK`` 时非空）。
        continuation_text: 需并入上一条的文本（``CONTINUATION`` 时非空）。
    """

    def __init__(
        self,
        outcome: str,
        entry: LogEntry | None = None,
        continuation_text: str = "",
    ) -> None:
        raise NotImplementedError


class LogParser:
    """基于 :class:`LogPreset` 的行解析器。

    参数:
        preset: 已校验的解析 Preset。
    """

    def __init__(self, preset: LogPreset) -> None:
        self._preset = preset

    @property
    def preset(self) -> LogPreset:
        """当前使用的 Preset。"""

        return self._preset

    def parse(self, line: str, sequence: int, received_at: float) -> ParseResult:
        """解析单行文本。

        参数:
            line: 不含行尾符的文本行。
            sequence: 由流水线分配的递增序号。
            received_at: PC 接收时刻（``time.time()`` 秒）。

        返回:
            :class:`ParseResult`；调用方据此新建条目或并入上一条。

        说明:
            本方法不修改任何外部状态，可安全重复调用；
            continuation 的“并入上一条”动作由 :class:`LogPipeline` 完成。
        """

        raise NotImplementedError

    def render_for_llm(self, entry: LogEntry) -> str:
        """把条目渲染为提交给 LLM 的文本行（含级别与模块前缀）。"""

        raise NotImplementedError
