"""``core/llm/adapter_loader.py`` 的 Adapter 声明校验测试。"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.adapter import StreamCondition, StreamRule, UsageSpec
from serial_log_analyzer.core.llm.adapter_loader import load_adapter, load_adapters

_ADAPTER_DIR = "providers/adapters"


def _base(adapter_id: str = "demo") -> dict[str, Any]:
    return {
        "schema_version": 3,
        "adapter_id": adapter_id,
        "endpoint": "/v1/chat/completions",
        "response_content_pointer": "/choices/0/message/content",
    }


def _yaml(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _load(make_loader, data: dict[str, Any], adapter_id: str = "demo"):
    loader = make_loader({f"{_ADAPTER_DIR}/{adapter_id}.yaml": _yaml(data)})
    return load_adapter(loader, adapter_id)


def test_minimal_adapter_uses_documented_defaults(make_loader):
    adapter = _load(make_loader, _base())

    assert adapter.adapter_id == "demo"
    assert adapter.endpoint == "/v1/chat/completions"
    assert adapter.headers_template == {}
    assert adapter.body_template == {}
    assert adapter.messages_format == "openai"
    assert adapter.reasoning_pointers == ()
    assert adapter.model_discovery is None
    assert adapter.usage == UsageSpec()
    assert adapter.streaming is None
    assert adapter.streaming_supported is False
    assert adapter.schema_version == 3
    assert adapter.source_path.endswith("demo.yaml")


def test_full_adapter_parses_headers_body_and_pointers(make_loader):
    data = _base()
    data.update(
        {
            "headers": {"Authorization": "Bearer ${api_key}", "Content-Type": "application/json"},
            "body": {"model": "${model}", "messages": "${messages}", "stream": "${stream}"},
            "messages_format": "anthropic",
            "response_reasoning_content_pointers": ["/choices/0/message/reasoning_content"],
            "models": {
                "endpoint": "/v1/models",
                "response_models_pointer": "/data",
                "response_model_id": "id",
            },
            "usage": {
                "input_tokens_pointer": "/usage/prompt_tokens",
                "output_tokens_pointer": "/usage/completion_tokens",
                "input_cached_tokens_pointers": ["/usage/prompt_tokens_details/cached_tokens"],
            },
        }
    )

    adapter = _load(make_loader, data)

    assert adapter.headers_template["Authorization"] == "Bearer ${api_key}"
    assert adapter.body_template["messages"] == "${messages}"
    assert adapter.messages_format == "anthropic"
    assert adapter.reasoning_pointers == ("/choices/0/message/reasoning_content",)
    assert adapter.usage == UsageSpec(
        input=("/usage/prompt_tokens",),
        output=("/usage/completion_tokens",),
        cached=("/usage/prompt_tokens_details/cached_tokens",),
    )
    assert adapter.model_discovery is not None
    assert adapter.model_discovery["endpoint"] == "/v1/models"
    assert adapter.model_discovery["response_models_pointer"] == "/data"


def test_model_id_is_a_plain_key_not_a_pointer(make_loader):
    data = _base()
    data["models"] = {
        "endpoint": "/v1/models",
        "response_models_pointer": "/data",
        "response_model_id": "id",
        "response_model_display": "display_name",
        "response_model_strip_prefix": "models/",
    }

    adapter = _load(make_loader, data)

    assert adapter.model_discovery is not None
    assert adapter.model_discovery["response_model_strip_prefix"] == "models/"


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": 2},
        {"schema_version": "3"},
        {"adapter_id": "Other"},
        {"adapter_id": "with_underscore"},
        {"endpoint": "https://api.example.com/v1/chat"},
        {"endpoint": "//api.example.com/v1"},
        {"endpoint": ""},
        {"messages_format": "mistral"},
        {"response_content_pointer": "choices/0/message/content"},
        {"response_content_pointer": "/choices/~2/content"},
        {"response_content_pointer": "/choices/-0/content"},
        {"response_content_pointer": None},
        {"headers": ["Authorization"]},
        {"body": ["model"]},
        {"response_reasoning_content_pointers": "/path"},
        {"unknown_field": 1},
    ],
)
def test_invalid_adapter_fields_are_rejected(make_loader, overrides):
    data = _base()
    data.update(overrides)

    with pytest.raises(ConfigError):
        _load(make_loader, data)


def test_missing_required_field_is_rejected(make_loader):
    data = _base()
    del data["response_content_pointer"]

    with pytest.raises(ConfigError):
        _load(make_loader, data)


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "${token}"},
        {"Authorization": "Bearer ${api_key}", "X-Trace": "${nope}"},
        {"Authorization": 1},
    ],
)
def test_header_placeholders_are_whitelisted(make_loader, headers):
    data = _base()
    data["headers"] = headers

    with pytest.raises(ConfigError):
        _load(make_loader, data)


def test_endpoint_accepts_whitelisted_placeholder(make_loader):
    data = _base()
    data["endpoint"] = "/openai/deployments/${model}/chat/completions"

    adapter = _load(make_loader, data)

    assert adapter.endpoint == "/openai/deployments/${model}/chat/completions"


@pytest.mark.parametrize("endpoint", ["/models/${bogus}", "/models/${token}"])
def test_endpoint_rejects_placeholder_outside_whitelist(make_loader, endpoint):
    data = _base()
    data["endpoint"] = endpoint

    with pytest.raises(ConfigError):
        _load(make_loader, data)


def test_streaming_endpoint_rejects_unknown_placeholder(make_loader):
    data = _base()
    streaming = _streaming()
    streaming["endpoint"] = "/stream/${nope}"
    data["streaming"] = streaming

    with pytest.raises(ConfigError):
        _load(make_loader, data)


def test_body_placeholder_must_own_the_whole_string(make_loader):
    data = _base()
    data["body"] = {"model": "pre-${model}"}

    with pytest.raises(ConfigError):
        _load(make_loader, data)


def test_body_with_plain_values_is_accepted(make_loader):
    data = _base()
    data["body"] = {"model": "${model}", "temperature": 0.7, "n": 1, "flag": True}

    adapter = _load(make_loader, data)

    assert adapter.body_template["temperature"] == 0.7
    assert adapter.body_template["flag"] is True


def test_usage_requires_at_least_one_pointer(make_loader):
    data = _base()
    data["usage"] = {}

    with pytest.raises(ConfigError):
        _load(make_loader, data)


def test_models_requires_endpoint_and_pointer(make_loader):
    data = _base()
    data["models"] = {"endpoint": "/v1/models"}
    with pytest.raises(ConfigError):
        _load(make_loader, data)

    data = _base()
    data["models"] = {"endpoint": "/v1/models", "response_models_pointer": "data"}
    with pytest.raises(ConfigError):
        _load(make_loader, data)


def _streaming() -> dict[str, Any]:
    return {
        "transport": "sse",
        "endpoint": "/v1/chat/completions",
        "request_body": {"stream_options": {"include_usage": True}},
        "content_events": [{"pointer": "/choices/0/delta/content"}],
        "reasoning_events": [{"pointer": "/choices/0/delta/reasoning_content"}],
        "terminal": {"sentinel": "[DONE]"},
        "allow_clean_eof": True,
        "error_events": [
            {
                "when": {"pointer": "/choices/0/finish_reason", "equals": "error"},
                "message_pointer": "/error/message",
                "status_pointer": "/error/status",
            }
        ],
        "usage": {
            "input_tokens_pointers": ["/usage/prompt_tokens"],
            "output_tokens_pointers": ["/usage/completion_tokens"],
            "total_tokens_pointers": ["/usage/total_tokens"],
        },
    }


def test_streaming_block_is_parsed(make_loader):
    data = _base()
    data["streaming"] = _streaming()

    adapter = _load(make_loader, data)

    spec = adapter.streaming
    assert adapter.streaming_supported is True
    assert spec is not None
    assert spec.endpoint == "/v1/chat/completions"
    assert spec.content_events == (StreamRule(pointer="/choices/0/delta/content"),)
    assert spec.reasoning_events == (
        StreamRule(pointer="/choices/0/delta/reasoning_content"),
    )
    assert spec.terminal_sentinel == "[DONE]"
    assert spec.terminal_when is None
    assert spec.allow_clean_eof is True
    assert spec.request_body == {"stream_options": {"include_usage": True}}
    assert spec.usage == UsageSpec(
        input=("/usage/prompt_tokens",),
        output=("/usage/completion_tokens",),
        total=("/usage/total_tokens",),
    )
    assert spec.error_events == (
        (
            StreamCondition(pointer="/choices/0/finish_reason", equals="error"),
            "/error/message",
            "/error/status",
        ),
    )


def test_streaming_terminal_condition_instead_of_sentinel(make_loader):
    streaming = _streaming()
    streaming["terminal"] = {"when": {"pointer": "/done", "exists": True}}
    data = _base()
    data["streaming"] = streaming

    adapter = _load(make_loader, data)

    assert adapter.streaming is not None
    assert adapter.streaming.terminal_sentinel is None
    assert adapter.streaming.terminal_when == StreamCondition(pointer="/done", exists=True)


def test_streaming_defaults_for_optional_parts(make_loader):
    data = _base()
    data["streaming"] = {
        "transport": "sse",
        "endpoint": "/v1/chat/completions",
        "content_events": [{"pointer": "/delta"}],
        "terminal": {"sentinel": "[DONE]"},
    }

    adapter = _load(make_loader, data)

    assert adapter.streaming is not None
    assert adapter.streaming.reasoning_events == ()
    assert adapter.streaming.request_body == {}
    assert adapter.streaming.error_events == ()
    assert adapter.streaming.allow_clean_eof is False
    assert adapter.streaming.usage == UsageSpec()


@pytest.mark.parametrize(
    "patch",
    [
        {"transport": "websocket"},
        {"endpoint": "https://api.example.com/v1/chat"},
        {"endpoint": ""},
        {"content_events": []},
        {"content_events": [{"when": {"pointer": "/x", "exists": True}}]},
        {"terminal": None},
        {"terminal": {"sentinel": "[DONE]", "when": {"pointer": "/done", "exists": True}}},
        {"terminal": {"when": {"pointer": "/done"}}},
        {"allow_clean_eof": "yes"},
        {"error_events": [{"when": {"pointer": "/x", "exists": True}}]},
        {"error_events": [{"message_pointer": "/error/message"}]},
        {"usage": {}},
        {"usage": {"input_tokens_pointers": []}},
        {"unknown_field": 1},
        {"request_body": ["stream"]},
        {"content_events": [{"pointer": "/delta", "text_blocks": "yes"}]},
        {"content_events": [{"pointer": "/delta", "text_blocks": 1}]},
    ],
)
def test_invalid_streaming_blocks_are_rejected(make_loader, patch):
    streaming = _streaming()
    streaming.update(patch)
    data = _base()
    data["streaming"] = streaming

    with pytest.raises(ConfigError):
        _load(make_loader, data)


def test_load_adapter_rejects_invalid_and_missing_ids(make_loader):
    loader = make_loader({f"{_ADAPTER_DIR}/demo.yaml": _yaml(_base())})

    with pytest.raises(ConfigError):
        load_adapter(loader, "Bad_Id")
    with pytest.raises(ConfigError) as excinfo:
        load_adapter(loader, "absent")
    assert "absent" in str(excinfo.value)


def test_load_adapter_rejects_broken_yaml(make_loader):
    loader = make_loader({f"{_ADAPTER_DIR}/demo.yaml": "schema_version: [3\n"})

    with pytest.raises(ConfigError):
        load_adapter(loader, "demo")


def test_load_adapter_rejects_non_mapping_document(make_loader):
    loader = make_loader({f"{_ADAPTER_DIR}/demo.yaml": "- a\n- b\n"})

    with pytest.raises(ConfigError):
        load_adapter(loader, "demo")


def test_load_adapters_sorts_by_id(make_loader):
    loader = make_loader(
        {
            f"{_ADAPTER_DIR}/zeta.yaml": _yaml(_base("zeta")),
            f"{_ADAPTER_DIR}/alpha.yaml": _yaml(_base("alpha")),
            f"{_ADAPTER_DIR}/ignored.txt": "not yaml",
        }
    )

    adapters = load_adapters(loader)

    assert [item.adapter_id for item in adapters] == ["alpha", "zeta"]


def test_adapter_parses_text_blocks_and_default_output_tokens(make_loader):
    data = _base()
    data.update(
        {
            "response_text_blocks_pointer": "/content",
            "default_max_output_tokens": 4096,
            "streaming": {
                "transport": "sse",
                "endpoint": "/candidates/0/content/parts",
                "content_events": [{"pointer": "/candidates/0/content/parts", "text_blocks": True}],
                "terminal": {"sentinel": "[DONE]"},
            },
        }
    )

    adapter = _load(make_loader, data)

    assert adapter.response_text_blocks_pointer == "/content"
    assert adapter.default_max_output_tokens == 4096
    assert adapter.streaming is not None
    assert adapter.streaming.content_events == (
        StreamRule(pointer="/candidates/0/content/parts", when=None, text_blocks=True),
    )


def test_adapter_defaults_for_text_blocks_and_output_tokens(make_loader):
    adapter = _load(make_loader, _base())

    assert adapter.response_text_blocks_pointer is None
    assert adapter.default_max_output_tokens == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"default_max_output_tokens": -1},
        {"default_max_output_tokens": 1.5},
        {"default_max_output_tokens": True},
        {"default_max_output_tokens": "4096"},
        {"response_text_blocks_pointer": "content"},
        {"response_text_blocks_pointer": 1},
    ],
)
def test_invalid_output_token_and_text_blocks_fields_are_rejected(make_loader, patch):
    data = _base()
    data.update(patch)

    with pytest.raises(ConfigError):
        _load(make_loader, data)
