"""按 Adapter 规则处理 SSE 事件与终止状态。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from serial_log_analyzer.core.errors import ProviderError, ResponseParseError
from serial_log_analyzer.core.llm.adapter import (
    JSONAdapter,
    UsageSpec,
    _first_optional,
    _optional,
    _payload,
    build_usage,
)
from serial_log_analyzer.core.models.analysis import TokenUsage
from serial_log_analyzer.core.models.provider import StreamEvent


class StreamOutcome:
    """单个流式事件的处理结果。"""

    DELTA = "delta"
    TERMINAL = "terminal"
    ERROR = "error"
    IGNORED = "ignored"


class StreamProcessor:
    """通过 adapter 提取事件，向 on_delta/on_reasoning/on_usage 推送增量。"""

    def __init__(
        self,
        adapter: JSONAdapter,
        on_delta: Callable[[str], None],
        on_reasoning: Callable[[str], None] | None = None,
        on_usage: Callable[[TokenUsage], None] | None = None,
    ) -> None:
        if not adapter.streaming_supported:
            raise ProviderError("此 Adapter 不支持流式")
        self._adapter = adapter
        self._on_delta = on_delta
        self._on_reasoning = on_reasoning
        self._on_usage = on_usage
        self._finished = False
        self._failed = False
        self._usage_values = [None, None, None]
        self._usage_cached: Any = None
        self._usage_extras: dict[str, Any] = {}
        self._last_usage: TokenUsage | None = None

    @property
    def finished(self) -> bool:
        """返回是否已终止（含错误）。"""
        return self._finished

    def _collect_usage(self, payload: Any, spec: UsageSpec) -> TokenUsage | None:
        """把本事件里的用量字段累积下来，并返回归一化后的用量。"""

        for index, candidates in enumerate((spec.input, spec.output, spec.total)):
            for pointer in candidates:
                value = _optional(payload, pointer)
                if value is not None:
                    self._usage_values[index] = value
                    break
        cached = _first_optional(payload, spec.cached)
        if cached is not None:
            self._usage_cached = cached
        for pointer in spec.extra_input:
            value = _optional(payload, pointer)
            if value is not None:
                self._usage_extras[pointer] = value
        return build_usage(
            *self._usage_values,
            cached_tokens=self._usage_cached,
            extra_input_tokens=list(self._usage_extras.values()),
        )

    def handle(self, event: StreamEvent) -> str:
        """处理事件；服务错误抛出 ProviderError，数据错误抛出 ResponseParseError。"""
        if self._finished:
            return StreamOutcome.IGNORED
        try:
            error = self._adapter.stream_error(event)
            if error:
                raise ProviderError(error)
            deltas = self._adapter.stream_content_deltas(event)
            reasoning = self._adapter.stream_reasoning_deltas(event)
            spec = self._adapter.streaming
            if event.data != spec.terminal_sentinel:
                payload = _payload(event)
                usage = self._collect_usage(payload, spec.usage)
                if usage is not None and usage != self._last_usage and self._on_usage:
                    self._last_usage = usage
                    self._on_usage(usage)
            for delta in deltas:
                self._on_delta(delta)
            if self._on_reasoning:
                for delta in reasoning:
                    self._on_reasoning(delta)
            if self._adapter.is_terminal(event):
                self._finished = True
                return StreamOutcome.TERMINAL
            return StreamOutcome.DELTA if deltas or reasoning else StreamOutcome.IGNORED
        except (ProviderError, ResponseParseError):
            self._failed = self._finished = True
            raise

    def finalize(self, *, clean_eof: bool) -> None:
        """收尾；只有显式终止或配置允许的正常 EOF 才算成功。"""
        if self._failed:
            raise ResponseParseError("流式请求已失败")
        if self._finished:
            return
        self._finished = True
        if not (clean_eof and self._adapter.streaming.allow_clean_eof):
            self._failed = True
            raise ResponseParseError("流式响应缺少终止事件，可能被截断")
