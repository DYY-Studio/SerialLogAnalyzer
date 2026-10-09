"""日志解析器：把文本行转换为 :class:`LogEntry`。

解析流程（单行）：
1. 空行或纯空白行直接忽略；
2. 用 Preset 行规则匹配；命中则提取 level / module / message / time；
3. 未命中但匹配 continuation 规则时，报告为续行，交由流水线并入上一条；
4. 否则按 fallback 规则生成 ``UNKNOWN`` 条目（原始文本保留在 ``raw``）。
"""

from __future__ import annotations

import re

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
        self.outcome = outcome
        self.entry = entry
        self.continuation_text = continuation_text


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

        if not line.strip():
            return ParseResult(ParseOutcome.IGNORED)

        rule = self._preset.line
        match = rule.pattern.match(line)
        if match is not None:
            return ParseResult(
                ParseOutcome.MATCHED,
                entry=self._matched_entry(match, line, sequence, received_at),
            )

        if rule.continuation_pattern is not None and rule.continuation_pattern.match(line):
            return ParseResult(ParseOutcome.CONTINUATION, continuation_text=line)

        if self._preset.fallback.enabled:
            return ParseResult(
                ParseOutcome.FALLBACK,
                entry=self._fallback_entry(line, sequence, received_at),
            )
        return ParseResult(ParseOutcome.IGNORED)

    def render_for_llm(self, entry: LogEntry) -> str:
        """把条目渲染为提交给 LLM 的文本行（含级别与模块前缀）。"""

        return f"[{entry.level.name}] [{entry.module or '-'}] {entry.message}"

    def _matched_entry(
        self, match, line: str, sequence: int, received_at: float
    ) -> LogEntry:
        """由正则匹配结果构造条目。"""

        rule = self._preset.line
        groups = match.groupdict()
        module = groups.get(rule.module_group)
        if not module or module == "-":
            module = None
        device_time = groups.get(rule.time_group) if rule.time_group else None
        message = groups.get(rule.message_group) or ""
        return LogEntry(
            sequence=sequence,
            received_at=received_at,
            level=self._preset.level_from_token(groups.get(rule.level_group) or ""),
            message=message,
            raw=line,
            device_time=device_time,
            module=module,
            extra=_extract_fields(rule.fields, message),
        )

    def _fallback_entry(self, line: str, sequence: int, received_at: float) -> LogEntry:
        """由降级规则构造条目。"""

        return LogEntry(
            sequence=sequence,
            received_at=received_at,
            level=self._preset.fallback.level,
            message=line.strip(),
            raw=line,
        )


def _extract_fields(fields: dict[str, re.Pattern[str]], message: str) -> dict[str, str]:
    """按字段正则从 ``message`` 中抽取结构化字段。

    命中取第一个捕获组，无捕获组则取整体匹配；未命中的字段不出现。
    """

    if not fields:
        return {}
    extra: dict[str, str] = {}
    for name, pattern in fields.items():
        found = pattern.search(message)
        if found is not None:
            extra[name] = found.group(1) if pattern.groups else found.group(0)
    return extra
