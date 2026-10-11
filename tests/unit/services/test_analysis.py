"""``core/services/analysis.py`` 的上下文构造与请求编排测试（不启动 Qt）。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from serial_log_analyzer.core.errors import (
    ConfigError,
    CredentialError,
    NetworkError,
    ResponseParseError,
)
from serial_log_analyzer.core.llm.adapter_loader import load_adapter
from serial_log_analyzer.core.llm.profile_loader import load_profile
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.analysis import (
    AnalysisRequest,
    AnalysisState,
    ContextSelector,
)
from serial_log_analyzer.core.prompts.loader import PromptLibrary
from serial_log_analyzer.core.services.analysis import (
    AnalysisContextBuilder,
    AnalysisService,
    AnalysisServiceHandlers,
)

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def resources(make_loader):
    files = {
        path.relative_to(_ROOT).as_posix(): path.read_text(encoding="utf-8-sig")
        for directory in ("providers", "prompts")
        for path in (_ROOT / directory).rglob("*")
        if path.is_file()
    }
    return make_loader(files)


class FakeCredentials:
    """凭据解析替身，避免测试触碰钥匙串或环境。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error

    def resolve(self, credential: object) -> str:
        if self._error is not None:
            raise self._error
        return "test-only-placeholder"


class FakeTransport:
    """手动驱动的 HttpTransport 替身：由测试决定何时推送分块。"""

    def __init__(self) -> None:
        self.requests: list[object] = []
        self.cancelled = False
        self._callbacks: tuple[object, object, object] | None = None

    def send(self, request, on_chunk, on_done, on_error):
        self.requests.append(request)
        self._callbacks = (on_chunk, on_done, on_error)
        return self

    def push(self, payload: bytes) -> None:
        assert self._callbacks is not None
        self._callbacks[0](payload)

    def done(self) -> None:
        assert self._callbacks is not None
        self._callbacks[1]()

    def fail(self, error: Exception) -> None:
        assert self._callbacks is not None
        self._callbacks[2](error)

    def cancel(self) -> None:
        """模拟 Qt 传输：取消会走一次错误回调。"""

        self.cancelled = True
        self.fail(NetworkError("模型请求已取消"))


class Recorder:
    """收集回调：结果快照、状态序列与错误；持有传输替身。"""

    def __init__(self) -> None:
        self.results: list[object] = []
        self.states: list[AnalysisState] = []
        self.errors: list[Exception] = []
        self.transport = FakeTransport()

    def service(
        self,
        resources,
        *,
        stream: bool = True,
        credentials: object | None = None,
    ) -> AnalysisService:
        profile = load_profile(resources, "openai-default")
        adapter = load_adapter(resources, profile.adapter_id)
        return AnalysisService(
            adapter,
            self.transport,
            PromptLibrary(resources),
            credentials or FakeCredentials(),
            AnalysisServiceHandlers(
                self.results.append, self.states.append, self.errors.append
            ),
            profile=replace(profile, stream=stream),
        )


def _pipeline(parser) -> LogPipeline:
    pipe = LogPipeline(parser)
    lines = ["[I] [wifi] connected", "[E] [uart] rx overflow", "    at uart_isr (uart.c:12)"]
    for index, line in enumerate(lines):
        pipe.feed(line, float(index))
    return pipe


def _sse(*payloads: str) -> bytes:
    return b"".join(b"data: " + item.encode() + b"\n\n" for item in payloads)


def test_context_builder_selects_entries(parser) -> None:
    builder = AnalysisContextBuilder(_pipeline(parser))

    recent = builder.build(ContextSelector.RECENT, recent_count=2)
    assert len(recent.entries) == 2 and "[I] [wifi] connected" not in recent.render()

    errors = builder.build(ContextSelector.ERRORS_ONLY)
    assert len(errors.entries) == 1 and "rx overflow" in errors.render()

    selected = builder.build(ContextSelector.SELECTED, selected_sequences=[0])
    assert len(selected.entries) == 1 and "connected" in selected.render()

    neighbors = builder.build(
        ContextSelector.SELECTED_WITH_NEIGHBORS, selected_sequences=[0], window=1
    )
    assert len(neighbors.entries) == 2

    manual = builder.build(ContextSelector.MANUAL, manual_text="  粘贴的日志  ")
    assert manual.render() == "粘贴的日志"


@pytest.mark.parametrize(
    ("selector", "kwargs"),
    [
        (ContextSelector.SELECTED, {}),
        (ContextSelector.SELECTED_WITH_NEIGHBORS, {}),
        (ContextSelector.MANUAL, {"manual_text": "   "}),
    ],
)
def test_context_builder_rejects_missing_input(parser, selector, kwargs) -> None:
    builder = AnalysisContextBuilder(_pipeline(parser))

    with pytest.raises(ConfigError):
        builder.build(selector, **kwargs)


def test_context_builder_rejects_empty_pipeline(parser) -> None:
    builder = AnalysisContextBuilder(LogPipeline(parser))

    with pytest.raises(ConfigError):
        builder.build(ContextSelector.RECENT)


def test_ask_streams_content_usage_and_finishes(resources, parser) -> None:
    recorder = Recorder()
    service = recorder.service(resources)
    transport = recorder.transport
    context = AnalysisContextBuilder(_pipeline(parser)).build(ContextSelector.RECENT)

    service.ask(AnalysisRequest(goal_id="explain-logs", context=context))
    transport.push(_sse('{"choices":[{"delta":{"content":"甲"}}]}'))
    transport.push(
        _sse('{"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}')
    )
    transport.push(_sse("[DONE]"))
    transport.done()

    final = recorder.results[-1]
    assert final.content == "甲" and final.state is AnalysisState.DONE
    assert (final.usage.input_tokens, final.usage.total_tokens) == (2, 5)
    assert recorder.states == [AnalysisState.STREAMING, AnalysisState.DONE]
    assert not recorder.errors
    assert [message.role.value for message in service.conversation] == ["user", "assistant"]

    body = transport.requests[0].body
    assert "connected" in body["messages"][0]["content"]
    assert body["stream"] is True


def test_ask_keeps_history_until_reset(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources)
    transport = recorder.transport

    service.ask(AnalysisRequest(user_input="第一次"))
    transport.push(_sse('{"choices":[{"delta":{"content":"答一"}}]}', "[DONE]"))
    transport.done()
    assert len(service.conversation) == 2

    service.ask(AnalysisRequest(user_input="第二次"))
    transport.push(_sse('{"choices":[{"delta":{"content":"答二"}}]}', "[DONE]"))
    transport.done()
    assert [message.content for message in service.conversation] == [
        "第一次",
        "答一",
        "第二次",
        "答二",
    ]
    # 结果快照带上会话历史，界面据此显示轮数
    assert len(recorder.results[-1].conversation) == 4

    service.reset()
    assert service.conversation == []


def test_history_rounds_keep_first_turn_plus_recent_rounds(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources)
    transport = recorder.transport

    def _turn(text: str) -> None:
        service.ask(AnalysisRequest(user_input=text))
        transport.push(_sse(f'{{"choices":[{{"delta":{{"content":"答{text}"}}}}]}}', "[DONE]"))
        transport.done()

    for index in range(3):
        _turn(f"第{index}问")
    assert len(service.conversation) == 6

    service.set_history_rounds(1)
    service.ask(AnalysisRequest(user_input="第3问"))

    sent = transport.requests[-1].body["messages"]
    # 首轮（带着日志上下文的那一轮）始终保留，再加最近 1 轮
    assert [message["content"] for message in sent] == ["第0问", "第2问", "答第2问", "第3问"]

    transport.push(_sse('{"choices":[{"delta":{"content":"答第3问"}}]}', "[DONE]"))
    transport.done()
    service.set_history_rounds(0)
    service.ask(AnalysisRequest(user_input="第4问"))

    # 0 = 不裁剪：4 轮历史 + 本轮；会话本身始终完整（界面要显示全部轮次）
    assert len(transport.requests[-1].body["messages"]) == 9
    assert len(service.conversation) == 9  # 4 轮共 8 条 + 本轮的 user 消息


def test_follow_up_requires_history_then_appends(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources)
    transport = recorder.transport

    with pytest.raises(ConfigError):
        service.follow_up("追问")

    service.ask(AnalysisRequest(user_input="第一轮"))
    transport.push(_sse('{"choices":[{"delta":{"content":"答"}}]}', "[DONE]"))
    transport.done()

    service.follow_up("追问")
    transport.push(_sse('{"choices":[{"delta":{"content":"再答"}}]}', "[DONE]"))
    transport.done()

    assert [message.content for message in service.conversation] == [
        "第一轮",
        "答",
        "追问",
        "再答",
    ]


def test_cancel_returns_to_idle_without_error(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources)
    transport = recorder.transport

    service.ask(AnalysisRequest(user_input="分析"))
    transport.push(_sse('{"choices":[{"delta":{"content":"半"}}]}'))
    service.cancel()
    service.cancel()

    assert transport.cancelled is True
    assert recorder.states[-1] is AnalysisState.IDLE
    assert not recorder.errors


def test_transport_error_reports_once_and_ignores_late_callbacks(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources)
    transport = recorder.transport

    service.ask(AnalysisRequest(user_input="分析"))
    transport.fail(ResponseParseError("响应不是合法 JSON"))
    transport.push(_sse('{"choices":[{"delta":{"content":"晚到"}}]}'))
    transport.done()

    assert recorder.states[-1] is AnalysisState.ERROR
    assert len(recorder.errors) == 1
    assert "响应不是合法 JSON" in str(recorder.results[-1].error)


def test_pending_request_rejects_new_ask(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources)

    service.ask(AnalysisRequest(user_input="分析"))

    with pytest.raises(ConfigError):
        service.ask(AnalysisRequest(user_input="又来"))
    with pytest.raises(ConfigError):
        service.follow_up("追问")


def test_unknown_goal_raises_synchronously_without_touching_history(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources)

    with pytest.raises(ConfigError):
        service.ask(AnalysisRequest(goal_id="absent", user_input="分析"))

    assert service.conversation == []
    assert recorder.transport.requests == []


def test_missing_credential_raises_synchronously(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources, credentials=FakeCredentials(error=CredentialError("缺少密钥")))

    with pytest.raises(CredentialError):
        service.ask(AnalysisRequest(user_input="分析"))

    assert service.conversation == []
    assert recorder.transport.requests == []


def test_set_profile_switches_target_and_blocks_while_streaming(resources) -> None:
    from serial_log_analyzer.core.errors import ConfigError
    from serial_log_analyzer.core.llm.adapter_loader import load_adapter
    from serial_log_analyzer.core.llm.profile_loader import load_profile

    recorder = Recorder()
    service = recorder.service(resources)
    transport = recorder.transport

    target = load_profile(resources, "sensenova")
    service.set_profile(target, load_adapter(resources, target.adapter_id))

    service.ask(AnalysisRequest(user_input="分析"))
    assert transport.requests[-1].url.startswith("https://token.sensenova.cn/v1")

    with pytest.raises(ConfigError):
        service.set_profile(
            load_profile(resources, "openai-default"),
            load_adapter(resources, "openai-compatible"),
        )


def test_set_profile_rejects_adapter_mismatch(resources) -> None:
    from serial_log_analyzer.core.errors import ConfigError
    from serial_log_analyzer.core.llm.adapter_loader import load_adapter
    from serial_log_analyzer.core.llm.profile_loader import load_profile

    recorder = Recorder()
    service = recorder.service(resources)

    with pytest.raises(ConfigError):
        service.set_profile(
            load_profile(resources, "sensenova"), load_adapter(resources, "anthropic")
        )


def test_context_builder_follows_pipeline_swap(parser) -> None:
    builder = AnalysisContextBuilder(_pipeline(parser))
    other = LogPipeline(parser)
    other.feed("[E] [mem] malloc failed", 9.0)

    builder.set_pipeline(other)

    context = builder.build(ContextSelector.RECENT)
    assert "malloc failed" in context.render()


def test_ask_without_handlers_fails_loudly(resources, parser) -> None:
    from serial_log_analyzer.core.llm.adapter_loader import load_adapter
    from serial_log_analyzer.core.llm.profile_loader import load_profile
    from serial_log_analyzer.core.prompts.loader import PromptLibrary
    from serial_log_analyzer.core.services.analysis import AnalysisService

    profile = load_profile(resources, "openai-default")
    service = AnalysisService(
        load_adapter(resources, profile.adapter_id),
        FakeTransport(),
        PromptLibrary(resources),
        FakeCredentials(),
        profile=profile,
    )

    with pytest.raises(ConfigError):
        service.ask(AnalysisRequest(user_input="分析"))


def test_non_streaming_parses_body(resources) -> None:
    recorder = Recorder()
    service = recorder.service(resources, stream=False)
    transport = recorder.transport

    service.ask(AnalysisRequest(user_input="分析"))
    transport.push('{"choices":[{"message":{"content":"整包回答"}}],"usage":{"prompt_tokens":1}}'.encode())
    transport.done()

    final = recorder.results[-1]
    assert final.content == "整包回答" and final.state is AnalysisState.DONE
    assert final.usage.input_tokens == 1 and final.usage.total_tokens == 1


def test_non_streaming_rejects_oversized_body(resources, monkeypatch) -> None:
    recorder = Recorder()
    service = recorder.service(resources, stream=False)
    transport = recorder.transport
    monkeypatch.setattr("serial_log_analyzer.core.services.analysis._MAX_BODY_BYTES", 8)

    service.ask(AnalysisRequest(user_input="分析"))
    transport.push(b"x" * 32)
    transport.done()

    assert recorder.states[-1] is AnalysisState.ERROR
    assert isinstance(recorder.errors[0], ResponseParseError)


def test_clean_eof_without_terminal_follows_adapter_policy(resources) -> None:
    """openai-compatible 声明 allow_clean_eof=true，缺终止事件的正常结束按完成处理。"""

    recorder = Recorder()
    service = recorder.service(resources)
    transport = recorder.transport

    service.ask(AnalysisRequest(user_input="分析"))
    transport.push(_sse('{"choices":[{"delta":{"content":"半"}}]}'))
    transport.done()

    assert recorder.states[-1] is AnalysisState.DONE
    assert not recorder.errors
