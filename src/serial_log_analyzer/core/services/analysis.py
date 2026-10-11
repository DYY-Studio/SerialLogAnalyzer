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

import json
from collections.abc import Callable

from serial_log_analyzer.core.errors import AppError, ConfigError, ResponseParseError
from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.llm.request import RequestBuilder
from serial_log_analyzer.core.llm.sse import SSEParser
from serial_log_analyzer.core.llm.stream import StreamOutcome, StreamProcessor
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.analysis import (
    AnalysisContext,
    AnalysisMessage,
    AnalysisRequest,
    AnalysisResult,
    AnalysisState,
    ContextSelector,
    MessageRole,
    TokenUsage,
)
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.core.models.provider import ProviderProfile
from serial_log_analyzer.core.ports import CancellationToken, CredentialProvider, HttpTransport
from serial_log_analyzer.core.prompts.loader import PromptLibrary

__all__ = ["AnalysisContextBuilder", "AnalysisService", "AnalysisServiceHandlers"]

ResultHandler = Callable[[AnalysisResult], None]
StateHandler = Callable[[AnalysisState], None]
ErrorHandler = Callable[[Exception], None]

# 非流式响应体上限；超过即视为异常响应，避免无界内存。
_MAX_BODY_BYTES = 8 * 1024 * 1024


class AnalysisContextBuilder:
    """把选中日志 / 最近日志 / 手动输入构造为 :class:`AnalysisContext`。

    参数:
        pipeline: 日志流水线（提供条目查询与渲染）。
    """

    def __init__(self, pipeline: LogPipeline) -> None:
        self._pipeline = pipeline

    def set_pipeline(self, pipeline: LogPipeline) -> None:
        """替换日志来源（切换日志 Preset 时由组合根调用）。"""

        self._pipeline = pipeline

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

        if selector is ContextSelector.MANUAL:
            text = manual_text.strip()
            if not text:
                raise ConfigError("手动上下文不能为空")
            return AnalysisContext(selector=selector, manual_text=text, window=window)

        entries = self._select(selector, selected_sequences, window, recent_count)
        if not entries:
            raise ConfigError(f"没有可用的日志上下文（{selector.value}）")
        return AnalysisContext(
            selector=selector, entries=tuple(self._pipeline.render(entries)), window=window
        )

    def _select(
        self,
        selector: ContextSelector,
        selected_sequences: list[int] | None,
        window: int,
        recent_count: int,
    ) -> list[LogEntry]:
        """按选择器取出参与上下文的条目。"""

        if selector is ContextSelector.RECENT:
            return list(self._pipeline.recent(recent_count))
        if selector is ContextSelector.ERRORS_ONLY:
            return list(self._pipeline.recent(recent_count, min_level=LogLevel.ERROR))

        sequences = list(selected_sequences or [])
        if not sequences:
            raise ConfigError("未选中任何日志行")
        if selector is ContextSelector.SELECTED_WITH_NEIGHBORS:
            return list(self._pipeline.selected_with_neighbors(sequences, window))
        wanted = set(sequences)
        return [entry for entry in self._pipeline.entries() if entry.sequence in wanted]


class AnalysisServiceHandlers:
    """分析服务对外回调集合。

    参数:
        on_result: 结果快照更新（每次增量后调用，携带累积后的完整结果）。
        on_state: 状态变化（开始流式 / 完成 / 出错 / 取消后回到空闲）。
        on_error: 错误通知。
    """

    def __init__(
        self,
        on_result: ResultHandler,
        on_state: StateHandler,
        on_error: ErrorHandler,
    ) -> None:
        self.on_result = on_result
        self.on_state = on_state
        self.on_error = on_error


class AnalysisService:
    """单次分析与多轮对话的编排。

    参数:
        adapter: 目标 Adapter。
        transport: HTTP 传输实现（由 ``io`` 提供）。
        prompts: Prompt 模板库。
        credentials: 凭据解析器。
        handlers: 对外回调；省略时需在发起分析前用 :meth:`set_handlers` 安装。
        profile: 目标 Profile；``stream`` 决定走 SSE 还是缓冲整包解析。

    请求前的配置与凭据错误（``ConfigError`` / ``CredentialError``）由 :meth:`ask`
    同步抛出；网络与响应解析错误通过 ``handlers.on_error`` 上报，终态回调只触发一次。
    """

    def __init__(
        self,
        adapter: JSONAdapter,
        transport: HttpTransport,
        prompts: PromptLibrary,
        credentials: CredentialProvider,
        handlers: AnalysisServiceHandlers | None = None,
        *,
        profile: ProviderProfile,
    ) -> None:
        self._adapter = adapter
        self._profile = profile
        self._transport = transport
        self._prompts = prompts
        self._credentials = credentials
        self._builder = RequestBuilder(adapter, profile, credentials)
        self._handlers = handlers
        self._conversation: list[AnalysisMessage] = []
        self._active = False
        self._token: CancellationToken | None = None
        self._result = AnalysisResult()
        self._cancelled = False
        self._sse: SSEParser | None = None
        self._processor: StreamProcessor | None = None
        self._buffer = bytearray()

    def set_handlers(self, handlers: AnalysisServiceHandlers) -> None:
        """安装对外回调；由 ``ui`` 控制器在构造后注入。

        参数:
            handlers: 分析服务回调集合。
        """

        self._handlers = handlers

    def set_profile(self, profile: ProviderProfile, adapter: JSONAdapter) -> None:
        """切换目标 Profile 与对应 Adapter，后续请求使用新配置。

        参数:
            profile: 新的 Profile 声明。
            adapter: 与 ``profile.adapter_id`` 匹配的 Adapter。

        异常:
            ConfigError: 已有进行中的请求，或 Profile 与 Adapter 不匹配。
        """

        if self._active:
            raise ConfigError("已有进行中的分析，无法切换 Profile")
        if adapter.adapter_id != profile.adapter_id:
            raise ConfigError("Profile 与 Adapter 不匹配")
        self._profile = profile
        self._adapter = adapter
        self._builder = RequestBuilder(adapter, profile, self._credentials)

    @property
    def conversation(self) -> list[AnalysisMessage]:
        """当前会话的消息历史（只读副本）。"""

        return list(self._conversation)

    def ask(self, request: AnalysisRequest) -> None:
        """开始一轮新的分析，沿用当前会话历史（重开用 :meth:`reset`）。

        异常:
            ConfigError: 已有进行中的请求，或上下文/目标非法。
            CredentialError: 凭据缺失。
        """

        self._ensure_idle()
        self._start(self._compose(request), request, self._summary(request))

    def follow_up(self, text: str) -> None:
        """在当前会话中追加一轮追问。

        异常:
            ConfigError: 尚无会话历史，或内容为空。
        """

        self._ensure_idle()
        if not self._conversation:
            raise ConfigError("尚无会话历史，无法追问")
        self._start(
            self._prompts.render_freeform(text),
            AnalysisRequest(user_input=text),
            text.strip(),
        )

    def cancel(self) -> None:
        """取消进行中的请求；未进行时为空操作。

        取消由用户发起，按空闲结束而不是错误，因此不会调用 ``handlers.on_error``。
        """

        token = self._token
        if not self._active or token is None:
            return
        self._cancelled = True
        token.cancel()

    def reset(self) -> None:
        """清空会话历史与结果。"""

        self.cancel()
        self._conversation.clear()
        self._result = AnalysisResult()

    def _ensure_idle(self) -> None:
        if self._handlers is None:
            raise ConfigError("未安装回调，无法发起分析")
        if self._active:
            raise ConfigError("已有进行中的分析，请先取消或等待完成")

    def _compose(self, request: AnalysisRequest) -> str:
        """把目标模板与上下文合成为本轮 user 消息。"""

        context = request.context.render() if request.context is not None else ""
        extra = request.user_input.strip()
        if request.goal_id:
            text = self._prompts.render(request.goal_id, context=context)
            return f"{text}\n\n{extra}" if extra else text
        if extra and context:
            return f"{extra}\n\n```\n{context}\n```"
        if extra:
            return self._prompts.render_freeform(extra)
        if context:
            return self._prompts.render_freeform(context)
        raise ConfigError("分析内容不能为空")

    def _summary(self, request: AnalysisRequest) -> str:
        """给界面用的短摘要：目标名 + 用户输入；都没有时说明只有日志上下文。"""

        goal = self._prompts.find(request.goal_id) if request.goal_id else None
        parts = [goal.display_name] if goal is not None else []
        text = request.user_input.strip()
        if text:
            parts.append(text)
        return " · ".join(parts) or "（仅日志上下文）"

    def _start(self, text: str, request: AnalysisRequest, summary: str) -> None:
        """发送一轮请求并进入流式状态机。"""

        message = AnalysisMessage(MessageRole.USER, text, summary)
        http = self._builder.build([*self._conversation, message], request)
        self._conversation.append(message)
        self._cancelled = False
        self._buffer.clear()
        self._result = AnalysisResult(state=AnalysisState.STREAMING)
        with_sse = self._profile.stream
        if with_sse:
            self._sse = SSEParser()
            self._processor = StreamProcessor(
                self._adapter,
                self._append_content,
                self._append_reasoning,
                self._set_usage,
            )
        else:
            self._sse = None
            self._processor = None
        self._handlers.on_state(AnalysisState.STREAMING)
        self._emit_result()
        self._active = True
        token = self._transport.send(http, self._on_chunk, self._on_done, self._on_error)
        if self._active:
            # 同步完成的传输（如测试替身）已在回调里收尾，此时不再保留令牌。
            self._token = token

    def _append_content(self, delta: str) -> None:
        self._result.content += delta

    def _append_reasoning(self, delta: str) -> None:
        self._result.reasoning = (self._result.reasoning or "") + delta

    def _set_usage(self, input_tokens: int, output_tokens: int, total_tokens: int) -> None:
        self._result.usage = TokenUsage(input_tokens, output_tokens, total_tokens)

    def _on_chunk(self, data: bytes) -> None:
        """网络分块回调：流式走 SSE 分帧，非流式累积整包。"""

        if not self._active:
            return
        if self._processor is None or self._sse is None:
            self._buffer.extend(data)
            if len(self._buffer) > _MAX_BODY_BYTES:
                self._fail(ResponseParseError("响应体超过上限，已中止解析"))
            return
        try:
            for event in self._sse.feed(data):
                outcome = self._processor.handle(event)
                if outcome != StreamOutcome.IGNORED:
                    self._emit_result()
                if outcome is StreamOutcome.TERMINAL:
                    break
        except AppError as exc:
            self._fail(exc)

    def _on_done(self) -> None:
        """请求正常结束回调。"""

        if not self._active:
            return
        try:
            if self._processor is not None:
                self._processor.finalize(clean_eof=True)
            else:
                self._parse_body()
        except AppError as exc:
            self._fail(exc)
            return
        if self._result.content:
            self._conversation.append(
                AnalysisMessage(MessageRole.ASSISTANT, self._result.content)
            )
        self._finish(AnalysisState.DONE)

    def _on_error(self, error: Exception) -> None:
        """请求失败回调；用户取消按空闲处理。"""

        if not self._active:
            return
        if self._cancelled:
            self._finish(AnalysisState.IDLE)
            return
        self._fail(error)

    def _parse_body(self) -> None:
        """解析非流式响应整包。"""

        try:
            payload = json.loads(self._buffer.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise ResponseParseError("响应不是合法 JSON") from exc
        content, reasoning = self._adapter.parse_response(payload)
        self._result.content = content
        self._result.reasoning = reasoning
        usage = self._adapter.extract_usage(payload)
        if usage is not None:
            self._set_usage(*usage)

    def _emit_result(self) -> None:
        """上报结果快照；附带会话历史，供界面显示轮数。"""

        self._result.conversation = list(self._conversation)
        self._handlers.on_result(self._result)

    def _fail(self, error: Exception) -> None:
        """进入错误终态：结果、状态与错误各上报一次。"""

        if not self._active:
            return
        self._result.state = AnalysisState.ERROR
        self._result.error = str(error)
        self._close()
        self._emit_result()
        self._handlers.on_state(AnalysisState.ERROR)
        self._handlers.on_error(error)

    def _finish(self, state: AnalysisState) -> None:
        """进入正常终态（完成 / 取消）。"""

        self._close()
        self._result.state = state
        self._emit_result()
        self._handlers.on_state(state)

    def _close(self) -> None:
        """结束本轮：中止未完成的传输并释放解析状态。"""

        token = self._token
        self._active = False
        self._token = None
        self._sse = None
        self._processor = None
        if token is not None:
            token.cancel()  # 已结束的传输按空操作处理
