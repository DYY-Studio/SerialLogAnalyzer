"""日志流水线：环形缓冲、多行合并与批量刷新载荷。

职责：
- 持有 ``LogEntry`` 序列与递增序号；
- 执行 continuation 合并（修改上一条而非新建）；
- 维护内存上限（环形缓冲），超出时丢弃最旧条目；
- 产出供 UI 增量刷新的 :class:`PipelineUpdate`。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from itertools import islice

from serial_log_analyzer.core.logs.parser import LogParser, ParseOutcome
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
    _entries: deque[LogEntry] = field(default_factory=deque, repr=False)
    _next_sequence: int = 0

    def feed(self, line: str, received_at: float) -> PipelineUpdate:
        """处理一行文本并返回增量更新。

        参数:
            line: 文本行。
            received_at: PC 接收时刻。

        返回:
            :class:`PipelineUpdate`；可能同时包含新增与被修改的条目。
        """

        result = self.parser.parse(line, self._next_sequence, received_at)
        added: list[LogEntry] = []
        updated: list[LogEntry] = []

        if result.outcome in (ParseOutcome.MATCHED, ParseOutcome.FALLBACK):
            added.append(self._store(result.entry))
        elif result.outcome == ParseOutcome.CONTINUATION:
            if self._entries:
                last = self._entries[-1]
                last.message = f"{last.message}\n{result.continuation_text}"
                last.raw = f"{last.raw}\n{result.continuation_text}"
                last.continuation = True
                updated.append(last)
            else:
                added.append(self._store(self._orphan_entry(result.continuation_text, received_at)))

        dropped = self._enforce_capacity()
        return PipelineUpdate(tuple(added), tuple(updated), dropped)

    def entries(self) -> list[LogEntry]:
        """返回当前全部条目（只读语义，调用方不应修改）。"""

        return list(self._entries)

    def recent(self, count: int, *, min_level: LogLevel | None = None) -> list[LogEntry]:
        """返回最近 ``count`` 条（可选按最低级别过滤），用于构造分析上下文。"""

        if count <= 0:
            return []
        if min_level is not None:
            return [entry for entry in self._entries if entry.level.value >= min_level.value][-count:]
        # deque 不支持切片；反向迭代取尾部，避免整表复制。
        return list(islice(reversed(self._entries), count))[::-1]

    def selected_with_neighbors(self, sequences: list[int], window: int) -> list[LogEntry]:
        """返回选中序号及其前后 ``window`` 行范围内的条目。"""

        if not sequences:
            return []
        index = {entry.sequence: position for position, entry in enumerate(self._entries)}
        wanted: set[int] = set()
        for sequence in sequences:
            position = index.get(sequence)
            if position is None:
                continue
            wanted.update(
                range(max(0, position - window), min(len(self._entries), position + window + 1))
            )
        return [entry for position, entry in enumerate(self._entries) if position in wanted]

    def clear(self) -> None:
        """清空条目并重置序号。"""

        self._entries.clear()
        self._next_sequence = 0

    def enforce_capacity(self) -> tuple[int, ...]:
        """按当前 ``capacity`` 立即移除超出部分，返回被移除的条目序号。

        供运行时调整容量后同步界面使用；返回的序号应交给
        ``LogTableModel.remove_sequences``。
        """

        return self._enforce_capacity()

    def render(self, entries: list[LogEntry]) -> list[str]:
        """把条目渲染为 LLM 上下文文本行。"""

        return [self.parser.render_for_llm(entry) for entry in entries]

    def __len__(self) -> int:
        return len(self._entries)

    def _store(self, entry: LogEntry) -> LogEntry:
        """追加条目并推进序号。"""

        self._entries.append(entry)
        self._next_sequence += 1
        return entry

    def _orphan_entry(self, text: str, received_at: float) -> LogEntry:
        """无上一条时的孤立续行，降级为独立条目，避免丢失。"""

        return LogEntry(
            sequence=self._next_sequence,
            received_at=received_at,
            level=self.parser.preset.fallback.level,
            message=text.strip(),
            raw=text,
        )

    def _enforce_capacity(self) -> tuple[int, ...]:
        """超出容量时丢弃最旧条目，返回被移除的序号。"""

        dropped: list[int] = []
        while len(self._entries) > self.capacity:
            dropped.append(self._entries.popleft().sequence)
        return tuple(dropped)
