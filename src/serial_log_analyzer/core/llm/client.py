"""单次 LLM 调用编排，供分析服务注入；不管理 UI 和会话历史。"""

from __future__ import annotations

import json
from collections.abc import Callable

from serial_log_analyzer.core.errors import AppError, ConfigError, ResponseParseError
from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.llm.request import RequestBuilder
from serial_log_analyzer.core.llm.sse import SSEParser
from serial_log_analyzer.core.llm.stream import StreamProcessor
from serial_log_analyzer.core.models.analysis import (
    AnalysisMessage,
    AnalysisRequest,
    AnalysisResult,
    AnalysisState,
    TokenUsage,
)
from serial_log_analyzer.core.ports import CancellationToken, HttpTransport


class LLMClient:
    """用 builder、adapter、transport 完成一次调用，max_response_bytes 限制普通响应。"""

    def __init__(
        self,
        builder: RequestBuilder,
        adapter: JSONAdapter,
        transport: HttpTransport,
        *,
        max_response_bytes: int = 8388608,
    ) -> None:
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ConfigError("响应大小上限必须为正整数")
        self._builder = builder
        self._adapter = adapter
        self._transport = transport
        self._max_response_bytes = max_response_bytes

    def send(
        self,
        messages: list[AnalysisMessage],
        request: AnalysisRequest,
        *,
        on_done: Callable[[AnalysisResult], None],
        on_error: Callable[[AppError], None],
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
    ) -> CancellationToken:
        """发送已准备的消息；回调交付结果/错误与可选增量，返回取消令牌。

        配置或凭据错误在发送前抛出；网络及解析错误交给 on_error。调用方负责历史与上下文。
        """
        http_request = self._builder.build(messages, request)
        result = AnalysisResult(state=AnalysisState.STREAMING)
        parser = SSEParser()
        buffer = bytearray()
        ended = False

        def delta(text):
            if ended:
                return
            result.content += text
            if on_delta:
                on_delta(text)

        def reasoning(text):
            if ended:
                return
            result.reasoning = (result.reasoning or "") + text
            if on_reasoning:
                on_reasoning(text)

        def usage(input_tokens, output_tokens, total_tokens):
            result.usage = TokenUsage(input_tokens, output_tokens, total_tokens)

        processor = (
            StreamProcessor(self._adapter, delta, reasoning, usage) if http_request.stream else None
        )

        def chunk(data):
            if ended:
                return
            if processor:
                for event in parser.feed(data):
                    if ended:
                        break
                    processor.handle(event)
            else:
                if len(buffer) + len(data) > self._max_response_bytes:
                    raise ResponseParseError("模型响应超出大小上限")
                buffer.extend(data)

        def error(exc):
            nonlocal ended
            if not ended:
                ended = True
                result.state = AnalysisState.ERROR
                result.error = str(exc)
                on_error(exc)

        def done():
            nonlocal ended
            if ended:
                return
            try:
                if processor:
                    for event in parser.finalize():
                        processor.handle(event)
                    processor.finalize(clean_eof=True)
                else:
                    try:
                        payload = json.loads(buffer)
                    except (ValueError, UnicodeError) as exc:
                        raise ResponseParseError("模型响应不是合法 JSON") from exc
                    result.content, result.reasoning = self._adapter.parse_response(payload)
                    extracted = self._adapter.extract_usage(payload)
                    if extracted:
                        result.usage = TokenUsage(*extracted)
            except AppError as exc:
                error(exc)
                return
            ended = True
            result.state = AnalysisState.DONE
            on_done(result)

        return self._transport.send(http_request, chunk, done, error)
