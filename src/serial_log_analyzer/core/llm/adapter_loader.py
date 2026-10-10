"""加载并严格校验 schema 3 Adapter 声明。"""

from __future__ import annotations

from string import Template
from typing import Any

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm import config as c
from serial_log_analyzer.core.llm.adapter import (
    JSONAdapter,
    StreamCondition,
    StreamingSpec,
    StreamRule,
    _render_body,
)
from serial_log_analyzer.core.ports import ResourceLoader


def load_adapter(loader: ResourceLoader, adapter_id: str) -> JSONAdapter:
    """通过资源接口加载指定 ID；文件或字段非法时抛出 ConfigError。"""
    path = f"providers/adapters/{c.identifier(adapter_id)}.yaml"
    try:
        result = _validate_adapter(c.document(loader.read_text(path)), path)
        if result.adapter_id != adapter_id:
            raise ConfigError("Adapter ID 与文件名不符")
        return result
    except ConfigError as exc:
        raise ConfigError(f"Adapter 配置非法：{path}；{exc}") from exc


def load_adapters(loader: ResourceLoader) -> list[JSONAdapter]:
    """加载全部 Adapter；同名覆盖由资源接口实现，非法配置抛出 ConfigError。"""
    return [
        load_adapter(loader, path.rsplit("/", 1)[-1].removesuffix(".yaml"))
        for path in sorted(set(loader.list_files("providers/adapters", "*.yaml")))
    ]


def _condition(value: Any) -> StreamCondition:
    raw = c.mapping(value, {"pointer", "equals", "exists"}, {"pointer"})
    if ("equals" in raw) == ("exists" in raw):
        raise ConfigError("条件必须指定 equals 或 exists 之一")
    if "exists" in raw and c.boolean(raw["exists"]) is not True:
        raise ConfigError("exists 仅支持 true")
    return StreamCondition(
        c.pointer(raw["pointer"]), raw.get("equals"), raw.get("exists", False), "equals" in raw
    )


def _rules(value: Any) -> tuple[StreamRule, ...]:
    if not isinstance(value, list):
        raise ConfigError("流式规则必须为数组")
    result = []
    for item in value:
        item = c.mapping(item, {"pointer", "when", "text_blocks"}, {"pointer"})
        result.append(
            StreamRule(
                c.pointer(item["pointer"]),
                _condition(item["when"]) if "when" in item else None,
                c.boolean(item.get("text_blocks", False)),
            )
        )
    return tuple(result)


def _validate_streaming(value: Any) -> StreamingSpec:
    raw = c.mapping(
        value,
        {
            "transport",
            "endpoint",
            "request_body",
            "content_events",
            "reasoning_events",
            "terminal",
            "allow_clean_eof",
            "error_events",
            "usage",
        },
        {"transport", "endpoint", "content_events", "terminal"},
    )
    if raw["transport"] != "sse":
        raise ConfigError("只支持 SSE 流式协议")
    terminal = c.mapping(raw["terminal"], {"sentinel", "when"})
    if len(terminal) != 1:
        raise ConfigError("终止条件必须指定 sentinel 或 when")
    errors = raw.get("error_events", [])
    if not isinstance(errors, list):
        raise ConfigError("错误规则必须是数组")
    parsed_errors = []
    for error in errors:
        error = c.mapping(
            error, {"when", "message_pointer", "status_pointer"}, {"when", "message_pointer"}
        )
        parsed_errors.append(
            (
                _condition(error["when"]),
                c.pointer(error["message_pointer"]),
                c.pointer(error["status_pointer"]) if "status_pointer" in error else None,
            )
        )
    usage = c.mapping(
        raw.get("usage", {}),
        {"input_tokens_pointers", "output_tokens_pointers", "total_tokens_pointers"},
    )
    pointers = []
    for name in ("input", "output", "total"):
        candidates = usage.get(f"{name}_tokens_pointers", [])
        if not isinstance(candidates, list):
            raise ConfigError("用量候选路径必须是数组")
        pointers.append(tuple(c.pointer(p) for p in candidates))
    body = raw.get("request_body", {})
    if not isinstance(body, dict):
        raise ConfigError("流式请求体必须是映射")
    return StreamingSpec(
        endpoint=c.endpoint(raw["endpoint"]),
        content_events=_rules(raw["content_events"]),
        reasoning_events=_rules(raw.get("reasoning_events", [])),
        terminal_sentinel=c.text(terminal["sentinel"]) if "sentinel" in terminal else None,
        terminal_when=_condition(terminal["when"]) if "when" in terminal else None,
        error_events=tuple(parsed_errors),
        request_body=body,
        allow_clean_eof=c.boolean(raw.get("allow_clean_eof", False)),
        usage_pointers=tuple(pointers),
    )


def _validate_adapter(data: dict[str, Any], source_path: str) -> JSONAdapter:
    raw = c.mapping(
        data,
        {
            "schema_version",
            "adapter_id",
            "endpoint",
            "headers",
            "body",
            "messages_format",
            "response_content_pointer",
            "response_reasoning_content_pointers",
            "models",
            "usage",
            "streaming",
            "response_text_blocks_pointer",
            "default_max_output_tokens",
        },
        {"schema_version", "adapter_id", "endpoint", "headers", "body", "response_content_pointer"},
    )
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 3:
        raise ConfigError("Adapter schema_version 必须是 3")
    headers, body = raw["headers"], raw["body"]
    if not isinstance(headers, dict) or not isinstance(body, dict):
        raise ConfigError("headers 和 body 必须为映射")
    for key, value in headers.items():
        c.text(key)
        _render_placeholders(c.text(value), {"api_key": "test", "model": "test"})
    values = {
        "model": "test",
        "messages": [],
        "system": "test",
        "temperature": 0.2,
        "max_output_tokens": 1,
        "stream": True,
    }
    _render_body(body, values)
    reasoning = raw.get("response_reasoning_content_pointers", [])
    if not isinstance(reasoning, list):
        raise ConfigError("reasoning 路径必须为数组")
    usage = c.mapping(
        raw.get("usage", {}), {f"{name}_tokens_pointer" for name in ("input", "output", "total")}
    )
    models = raw.get("models")
    if models is not None:
        models = c.mapping(
            models,
            {
                "endpoint",
                "response_models_pointer",
                "response_model_id",
                "response_model_display",
                "response_model_strip_prefix",
            },
            {"endpoint", "response_models_pointer", "response_model_id"},
        )
        c.endpoint(models["endpoint"])
        c.pointer(models["response_models_pointer"])
        for key in models.keys() - {"endpoint", "response_models_pointer"}:
            c.text(models[key])
    fmt = raw.get("messages_format", "openai")
    if not isinstance(fmt, str) or fmt not in {"openai", "anthropic", "gemini"}:
        raise ConfigError("未知消息格式")
    limit = raw.get("default_max_output_tokens", 0)
    if type(limit) is not int or limit < 0:
        raise ConfigError("默认输出上限必须为非负整数")
    streaming = _validate_streaming(raw["streaming"]) if "streaming" in raw else None
    if streaming:
        _render_body(streaming.request_body, values)
        if body.keys() & streaming.request_body.keys():
            raise ConfigError("流式请求体与基础请求体冲突")
    return JSONAdapter(
        adapter_id=c.identifier(raw["adapter_id"]),
        endpoint=c.endpoint(raw["endpoint"]),
        headers_template=headers,
        body_template=body,
        messages_format=fmt,
        response_content_pointer=c.pointer(raw["response_content_pointer"]),
        reasoning_pointers=tuple(c.pointer(p) for p in reasoning),
        model_discovery=models,
        usage_pointers=tuple(
            c.pointer(usage[f"{n}_tokens_pointer"]) if f"{n}_tokens_pointer" in usage else None
            for n in ("input", "output", "total")
        ),
        streaming=streaming,
        source_path=source_path,
        response_text_blocks_pointer=c.pointer(raw["response_text_blocks_pointer"])
        if "response_text_blocks_pointer" in raw
        else None,
        default_max_output_tokens=limit,
    )


def _render_placeholders(template: str, values: dict[str, Any]) -> str:
    try:
        return Template(template).substitute(values)
    except (KeyError, ValueError) as exc:
        raise ConfigError("占位符未知或语法非法") from exc
