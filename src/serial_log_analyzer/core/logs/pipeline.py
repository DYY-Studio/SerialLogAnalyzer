"""日志流水线：环形缓冲、多行合并与批量刷新载荷。

职责：
- 持有 ``LogEntry`` 序列与递增序号；
- 执行 continuation 合并（修改上一条而非新建）；
- 维护内存上限（环形缓冲），超出时丢弃最旧条目；
- 产出供 UI 增量刷新的 :class:`PipelineUpdate`。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel

__all__ = ["LogPipeline", "PipelineUpdate"]


@dataclass(frozen=True)
class PipelineUpdate:
    """一次 ``feed`` 调用产生的增量结果，供 UI 批量刷新。

    参数:
        added: 新增条目。
        updated: 因 continuation 合并而被修改的已有条目（通常为上一条）。
        dropped_sequences: 因超出内存上限被移除的条目序号。
    """

    added: tuple[LogEntry, ...] = ()
    updated: tuple[LogEntry, ...] = ()
    dropped_sequences: tuple[int, ...] = ()


@dataclass
class LogPipeline:
    """日志条目容器与解析编排。

    参数:
        parser: 行解析器。
        capacity: 内存中保留的最大条目数，超出后丢弃最旧条目；默认 100000。
    """

    parser: LogParser
    capacity: int = 100000
    _entries: list[LogEntry] = field(default_factory=list, repr=False)
    _next_sequence: int = 0

    def feed(self, line: str, received_at: float) -> PipelineUpdate:
        """处理一行文本并返回增量更新。

        参数:
            line: 文本行。
            received_at: PC 接收时刻。

        返回:
            :class:`PipelineUpdate`；可能同时包含新增与被修改的条目。
        """

        raise NotImplementedError

    def entries(self) -> list[LogEntry]:
        """返回当前全部条目（只读语义，调用方不应修改）。"""

        return list(self._entries)

    def recent(self, count: int, *, min_level: LogLevel | None = None) -> list[LogEntry]:
        """返回最近 ``count`` 条（可选按最低级别过滤），用于构造分析上下文。"""

        raise NotImplementedError

    def selected_with_neighbors(self, sequences: list[int], window: int) -> list[LogEntry]:
        """返回选中序号及其前后 ``window`` 行范围内的条目。"""

        raise NotImplementedError

    def clear(self) -> None:
        """清空条目并重置序号。"""

        raise NotImplementedError

    def render(self, entries: list[LogEntry]) -> list[str]:
        """把条目渲染为 LLM 上下文文本行。"""

        raise NotImplementedError

    def __len__(self) -> int:
        return len(self._entries)
