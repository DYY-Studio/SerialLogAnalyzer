"""LLM 协议与模板测试：不启动 Qt，不访问外部服务。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from serial_log_analyzer.core.errors import (
    ConfigError,
    PointerError,
    ProviderError,
    ResponseParseError,
)
from serial_log_analyzer.core.llm.adapter_loader import load_adapter, load_adapters
from serial_log_analyzer.core.llm.client import LLMClient
from serial_log_analyzer.core.llm.pointer import parse_pointer, resolve_pointer
from serial_log_analyzer.core.llm.profile_loader import load_profile, load_profiles
from serial_log_analyzer.core.llm.request import RequestBuilder, join_url
from serial_log_analyzer.core.llm.sse import SSEParser
from serial_log_analyzer.core.llm.stream import StreamProcessor
from serial_log_analyzer.core.models.analysis import AnalysisMessage, AnalysisRequest, MessageRole
from serial_log_analyzer.core.models.provider import StreamEvent
from serial_log_analyzer.core.prompts.loader import PromptLibrary

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def resources(make_loader):
    files = {
        p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8-sig")
        for directory in ("providers", "prompts")
        for p in (ROOT / directory).rglob("*")
        if p.is_file()
    }
    return make_loader(files)


@pytest.fixture
def adapter(resources):
    return load_adapter(resources, "chat-completions-basic")


@pytest.mark.parametrize(
    ("pointer", "expected"), [("", {"a/b": {"~": [1, 2]}}), ("/a~1b/~0/-1", 2)]
)
def test_pointer(pointer, expected):
    assert resolve_pointer({"a/b": {"~": [1, 2]}}, pointer) == expected


@pytest.mark.parametrize(
    "pointer",
    [
        "bad",
        "/~",
        "/~2",
        "/a/-0",
        "/a/-",
        "/a/02",
        "/a/2",
        "/a/-3",
        "/a/name",
        "/a/0/x",
        "/missing",
    ],
)
def test_invalid_pointer(pointer):
    with pytest.raises(PointerError):
        resolve_pointer({"a": [1, 2]}, pointer)


def test_pointer_lexing():
    assert parse_pointer("/~01/~1") == ["~1", "/"]
    with pytest.raises(PointerError):
        resolve_pointer({"-1": 1}, "/-1")


def test_all_resources(resources):
    assert len(load_adapters(resources)) == 5
    profiles = load_profiles(resources)
    assert {"sensenova", "internlm"} <= {p.profile_id for p in profiles}
    for profile in profiles:
        RequestBuilder(load_adapter(resources, profile.adapter_id), profile, FakeCredentials())
    library = PromptLibrary(resources)
    assert len(library.goals()) == 4
    rendered = library.render("aggregate-anomalies", context="[E] malloc failed $ignored")
    assert "malloc failed $ignored" in rendered


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": 1},
        {"schema_version": True},
        {"messages_format": []},
        {"body": {"model": "prefix-${model}"}},
        {"headers": {"X": "${unknown}"}},
        {"response_content_pointer": "/~invalid"},
    ],
)
def test_adapter_rejects_bad_config(resources, make_loader, change):
    path = "providers/adapters/chat-completions-basic.yaml"
    raw = yaml.safe_load(resources.read_text(path))
    raw.update(change)
    with pytest.raises(ConfigError):
        load_adapter(make_loader({path: yaml.safe_dump(raw)}), "chat-completions-basic")


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://user:pass@example.com"},
        {"request_timeout_seconds": float("nan")},
        {"stream": "yes"},
        {"credential": {"kind": "environment"}},
        {"unknown": 2},
    ],
)
def test_profile_rejects_bad_config(resources, make_loader, change):
    path = "providers/profiles/internlm.yaml"
    raw = yaml.safe_load(resources.read_text(path))
    raw.update(change)
    with pytest.raises(ConfigError):
        load_profile(make_loader({path: yaml.safe_dump(raw)}), "internlm")


def test_duplicate_yaml(make_loader):
    with pytest.raises(ConfigError):
        load_adapter(
            make_loader({"providers/adapters/test.yaml": "schema_version: 3\nschema_version: 3"}),
            "test",
        )


class FakeCredentials:
    def resolve(self, credential):
        return "test-only-placeholder"


def test_request(adapter, resources):
    profile = load_profile(resources, "sensenova")
    messages = [
        AnalysisMessage(MessageRole.SYSTEM, "规则"),
        AnalysisMessage(MessageRole.USER, "日志"),
        AnalysisMessage(MessageRole.ASSISTANT, "回答"),
        AnalysisMessage(MessageRole.USER, "追问"),
    ]
    request = RequestBuilder(adapter, profile, FakeCredentials()).build(messages, AnalysisRequest())
    assert request.url == "https://token.sensenova.cn/v1/chat/completions"
    assert request.body["messages"] == [
        {"role": m.role.value, "content": m.content} for m in messages
    ]
    assert request.body["stream"] is True
    assert "max_tokens" not in request.body
    assert "stream_options" not in request.body
    assert join_url(
        "https://example.com/v1/", "/models/${model}:generateContent?alt=sse", "a/b"
    ) == ("https://example.com/v1/models/a%2Fb:generateContent?alt=sse")


@pytest.mark.parametrize(
    ("name", "key"), [("anthropic", "messages"), ("google-gemini", "contents")]
)
def test_message_conversion(resources, name, key):
    adapter = load_adapter(resources, name)
    _, body = adapter.build_request(
        api_key="fake",
        model="test",
        messages=[
            AnalysisMessage(MessageRole.SYSTEM, "规则"),
            AnalysisMessage(MessageRole.ASSISTANT, "回复"),
        ],
        temperature=0.2,
        max_output_tokens=0,
        stream=False,
    )
    assert len(body[key]) == 1
    if name == "anthropic":
        assert body["system"] == "规则"
        assert body["max_tokens"] == 4096
    else:
        assert body[key][0]["role"] == "model"


def test_conflicts_and_response(adapter):
    args = {
        "api_key": "fake",
        "model": "test",
        "messages": [],
        "temperature": 0.2,
        "max_output_tokens": 1,
        "stream": False,
    }
    with pytest.raises(ConfigError):
        adapter.build_request(**args, extra_body={"model": "override"})
    with pytest.raises(ConfigError):
        adapter.build_request(**args, extra_headers={"authorization": "override"})
    assert adapter.parse_response(
        {"choices": [{"message": {"content": "正文", "reasoning": "附加"}}]}
    ) == ("正文", "附加")
    with pytest.raises(ResponseParseError):
        adapter.parse_response({"choices": []})
    with pytest.raises(ResponseParseError):
        adapter.extract_usage({"usage": {"total_tokens": True}})


def test_text_blocks(resources):
    anthropic = load_adapter(resources, "anthropic")
    assert (
        anthropic.parse_response(
            {"content": [{"type": "text", "text": "甲"}, {"type": "text", "text": "乙"}]}
        )[0]
        == "甲乙"
    )
    responses = load_adapter(resources, "openai-responses")
    assert (
        responses.parse_response(
            {
                "output": [
                    {"type": "reasoning"},
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "甲"},
                            {"type": "output_text", "text": "乙"},
                        ],
                    },
                ]
            }
        )[0]
        == "甲乙"
    )


def test_sse_all_boundaries():
    raw = "\ufeff: heartbeat\r\nevent: delta\r\ndata: 中文\r\ndata: second\r\n\r\ndata: [DONE]".encode()
    for split in range(len(raw) + 1):
        parser = SSEParser()
        events = parser.feed(raw[:split]) + parser.feed(raw[split:]) + parser.finalize()
        assert [(e.data, e.event) for e in events] == [("中文\nsecond", "delta"), ("[DONE]", None)]
    parser = SSEParser()
    events = []
    for byte in raw:
        events.extend(parser.feed(bytes([byte])))
    events.extend(parser.finalize())
    assert events[0].data == "中文\nsecond"


@pytest.mark.parametrize("newline", ["\r", "\n", "\r\n"])
def test_sse_newlines(newline):
    parser = SSEParser()
    assert [e.data for e in parser.feed(f"data: x{newline}{newline}".encode())] == ["x"]


def test_sse_errors_and_reset():
    parser = SSEParser(max_event_bytes=5)
    with pytest.raises(ResponseParseError):
        parser.feed(b"data: x")
    parser = SSEParser()
    parser.feed(b"\xe4")
    with pytest.raises(ResponseParseError):
        parser.finalize()
    parser.reset()
    assert parser.feed(b"data: ok\n\n")[0].data == "ok"
    assert parser.finalize() == []
    assert parser.finalize() == []


def test_stream_terminal_and_usage(adapter):
    deltas, usages = [], []
    processor = StreamProcessor(adapter, deltas.append, on_usage=lambda *v: usages.append(v))
    processor.handle(StreamEvent('{"choices":[{"delta":{"content":"甲"}}]}'))
    processor.handle(
        StreamEvent(
            '{"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}'
        )
    )
    processor.handle(StreamEvent("[DONE]"))
    processor.handle(StreamEvent("invalid ignored after terminal"))
    processor.finalize(clean_eof=True)
    assert deltas == ["甲"] and usages == [(2, 3, 5)] and processor.finished


def test_stream_errors(adapter):
    with pytest.raises(ResponseParseError):
        StreamProcessor(adapter, lambda _: None).finalize(clean_eof=True)
    with pytest.raises(ProviderError):
        StreamProcessor(adapter, lambda _: None).handle(
            StreamEvent('{"error":{"message":"private"}}')
        )
    with pytest.raises(ResponseParseError):
        StreamProcessor(adapter, lambda _: None).handle(StreamEvent("not json"))


def test_final_event_content_and_usage(resources):
    adapter = load_adapter(resources, "google-gemini")
    deltas, usages = [], []
    processor = StreamProcessor(adapter, deltas.append, on_usage=lambda *v: usages.append(v))
    processor.handle(
        StreamEvent(
            json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "尾部"}]}, "finishReason": "STOP"}
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 2,
                        "candidatesTokenCount": 3,
                        "totalTokenCount": 5,
                    },
                }
            )
        )
    )
    assert processor.finished and deltas == ["尾部"] and usages == [(2, 3, 5)]


def test_split_usage(resources):
    adapter = load_adapter(resources, "anthropic")
    usages = []
    processor = StreamProcessor(adapter, lambda _: None, on_usage=lambda *v: usages.append(v))
    processor.handle(StreamEvent('{"type":"message_start","message":{"usage":{"input_tokens":5}}}'))
    processor.handle(StreamEvent('{"type":"message_delta","usage":{"output_tokens":3}}'))
    processor.handle(StreamEvent('{"type":"message_stop"}'))
    assert usages[-1] == (5, 3, 8)


class FakeTransport:
    def __init__(self, chunks):
        self.chunks = chunks

    def send(self, request, on_chunk, on_done, on_error):
        try:
            for chunk in self.chunks:
                on_chunk(chunk)
            on_done()
        except (ProviderError, ResponseParseError) as exc:
            on_error(exc)
        return self

    def cancel(self):
        pass


@pytest.mark.parametrize("stream", [True, False])
def test_client_closed_loop(resources, adapter, stream):
    profile = replace(load_profile(resources, "internlm"), stream=stream)
    prompt = PromptLibrary(resources).render("aggregate-anomalies", context="[E] malloc failed")
    builder = RequestBuilder(adapter, profile, FakeCredentials())
    payload = (
        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
        if stream
        else b'{"choices":[{"message":{"content":"ok"}}]}'
    )
    chunks = [bytes([byte]) for byte in payload]
    done, errors, deltas = [], [], []
    client = LLMClient(builder, adapter, FakeTransport(chunks))
    client.send(
        [AnalysisMessage(MessageRole.USER, prompt)],
        AnalysisRequest(),
        on_done=done.append,
        on_error=errors.append,
        on_delta=deltas.append,
    )
    assert not errors and len(done) == 1 and done[0].content == "ok"
    assert "".join(deltas) == ("ok" if stream else "")


def test_client_parse_error_once(resources, adapter):
    profile = replace(load_profile(resources, "internlm"), stream=False)
    done, errors = [], []
    client = LLMClient(
        RequestBuilder(adapter, profile, FakeCredentials()), adapter, FakeTransport([b"not json"])
    )
    client.send([], AnalysisRequest(), on_done=done.append, on_error=errors.append)
    assert not done and len(errors) == 1


def test_prompt_invalid_variable(make_loader):
    library = PromptLibrary(make_loader({"prompts/test.md": "# 名称\n$context $unknown"}))
    with pytest.raises(ConfigError):
        library.render("test", context="日志")


def test_null_condition_and_malformed_blocks(resources, make_loader):
    path = "providers/adapters/chat-completions-basic.yaml"
    raw = yaml.safe_load(resources.read_text(path))
    raw["streaming"]["terminal"] = {"when": {"pointer": "/finished", "equals": None}}
    adapter = load_adapter(make_loader({path: yaml.safe_dump(raw)}), "chat-completions-basic")
    assert adapter.is_terminal(StreamEvent('{"finished":null}'))
    assert not adapter.is_terminal(StreamEvent("{}"))
    responses = load_adapter(resources, "openai-responses")
    with pytest.raises(ResponseParseError):
        responses.parse_response({"output": [{"type": "message", "content": ["bad"]}]})
    with pytest.raises(ResponseParseError):
        StreamProcessor(adapter, lambda _: None).handle(StreamEvent("[]"))


def test_gemini_multiple_stream_blocks(resources):
    adapter = load_adapter(resources, "google-gemini")
    deltas = []
    processor = StreamProcessor(adapter, deltas.append)
    processor.handle(
        StreamEvent(
            json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "甲"},
                                    {"text": "推理", "thought": True},
                                    {"text": "乙"},
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ]
                }
            )
        )
    )
    assert deltas == ["甲", "乙"] and processor.finished


def test_clean_eof_allowed_only_when_configured(adapter):
    allowed = replace(adapter, streaming=replace(adapter.streaming, allow_clean_eof=True))
    processor = StreamProcessor(allowed, lambda _: None)
    processor.finalize(clean_eof=True)
    assert processor.finished
    with pytest.raises(ResponseParseError):
        StreamProcessor(allowed, lambda _: None).finalize(clean_eof=False)


def test_response_size_limit(resources, adapter):
    profile = replace(load_profile(resources, "internlm"), stream=False)
    errors = []
    client = LLMClient(
        RequestBuilder(adapter, profile, FakeCredentials()),
        adapter,
        FakeTransport([b"12345"]),
        max_response_bytes=4,
    )
    client.send(
        [],
        AnalysisRequest(),
        on_done=lambda _: pytest.fail("unexpected success"),
        on_error=errors.append,
    )
    assert len(errors) == 1 and isinstance(errors[0], ResponseParseError)
