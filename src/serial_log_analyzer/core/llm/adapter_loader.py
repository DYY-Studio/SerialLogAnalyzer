"""LLM Adapter 加载与校验。

读取 ``providers/adapters/*.yaml``，校验字段完整性与类型，编译扩展 JSON Pointer，
构造 :class:`JSONAdapter`。

校验原则：未知字段报错（避免拼写错误被静默忽略），占位符白名单限制在
``${model} ${system} ${messages} ${temperature} ${max_output_tokens} ${stream} ${api_key}``。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.adapter import (
    JSONAdapter,
    StreamCondition,
    StreamingSpec,
    StreamRule,
    UsageSpec,
)
from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["load_adapter", "load_adapters"]

_ADAPTER_DIR = "providers/adapters"
_SCHEMA_VERSION = 3

_ADAPTER_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "adapter_id",
    "endpoint",
    "messages_format",
    "headers",
    "body",
    "response_content_pointer",
    "response_reasoning_content_pointers",
    "response_text_blocks_pointer",
    "default_max_output_tokens",
    "models",
    "usage",
    "streaming",
}
_MODEL_FIELDS = {
    "endpoint",
    "response_models_pointer",
    "response_model_id",
    "response_model_display",
    "response_model_strip_prefix",
}
_MODEL_REQUIRED_FIELDS = ("endpoint", "response_models_pointer")
_USAGE_FIELDS = ("input_tokens_pointer", "output_tokens_pointer", "total_tokens_pointer")
_USAGE_LIST_FIELDS = ("input_cached_tokens_pointers", "input_extra_tokens_pointers")
_STREAMING_FIELDS = {
    "transport",
    "endpoint",
    "request_body",
    "content_events",
    "reasoning_events",
    "terminal",
    "allow_clean_eof",
    "error_events",
    "usage",
}
_STREAM_USAGE_FIELDS = (
    "input_tokens_pointers",
    "output_tokens_pointers",
    "total_tokens_pointers",
)
_STREAM_RULE_FIELDS = {"pointer", "when", "text_blocks"}
_TERMINAL_FIELDS = {"sentinel", "when"}
_CONDITION_FIELDS = {"pointer", "equals", "exists"}
_ERROR_EVENT_FIELDS = {"when", "message_pointer", "status_pointer"}

_ALLOWED_PLACEHOLDERS = (
    "model",
    "system",
    "messages",
    "temperature",
    "max_output_tokens",
    "stream",
    "api_key",
)
_MESSAGES_FORMATS = ("openai", "anthropic", "gemini")


def _where(source_path: str) -> str:
    """把来源路径渲染成错误信息后缀。"""
    return f"（{source_path}）" if source_path else ""


def load_adapter(loader: ResourceLoader, adapter_id: str) -> JSONAdapter:
    """按 ID 加载单个 Adapter。

    参数:
        loader: 资源加载器。
        adapter_id: Adapter 标识，需满足 ``[a-z][a-z0-9-]*``。

    返回:
        校验完成的 :class:`JSONAdapter`。

    异常:
        ConfigError: 文件缺失、YAML 非法、未知字段、缺少必填字段或类型错误。
    """

    if not _ADAPTER_ID_RE.match(adapter_id):
        raise ConfigError(f"非法 adapter_id：{adapter_id}")

    path = f"{_ADAPTER_DIR}/{adapter_id}.yaml"
    try:
        text = loader.read_text(path)
    except ConfigError as exc:
        raise ConfigError(f"未找到 Adapter：{adapter_id}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Adapter YAML 非法：{adapter_id}{_where(path)}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Adapter 顶层必须是对象：{adapter_id}{_where(path)}")

    return _validate_adapter(data, path)


def load_adapters(loader: ResourceLoader) -> list[JSONAdapter]:
    """加载全部 Adapter，用户目录覆盖同 ID 的内置 Adapter。

    返回:
        已校验的 Adapter 列表，按 ``adapter_id`` 升序排列。
    """

    paths = loader.list_files(_ADAPTER_DIR, "*.yaml")
    ids: dict[str, str] = {}
    for path in paths:
        ids.setdefault(Path(path).stem, path)

    adapters = [load_adapter(loader, adapter_id) for adapter_id in ids]
    adapters.sort(key=lambda adapter: adapter.adapter_id)
    return adapters


def _validate_adapter(data: dict[str, Any], source_path: str) -> JSONAdapter:
    """校验 Adapter 声明并构造对象。

    异常:
        ConfigError: 校验失败。
    """

    unknown = set(data) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ConfigError(f"未知字段：{sorted(unknown)}{_where(source_path)}")
    if data.get("schema_version") != _SCHEMA_VERSION:
        raise ConfigError(f"schema_version 必须为 {_SCHEMA_VERSION}{_where(source_path)}")

    adapter_id = _require_str(data, "adapter_id", source_path)
    if not _ADAPTER_ID_RE.match(adapter_id):
        raise ConfigError(f"非法 adapter_id：{adapter_id}{_where(source_path)}")
    stem = Path(source_path).stem
    if adapter_id != stem:
        raise ConfigError(f"adapter_id（{adapter_id}）必须与文件名（{stem}）一致")

    endpoint = _require_str(data, "endpoint", source_path)
    _require_relative_endpoint(endpoint, "endpoint", source_path)
    _validate_placeholder_names(endpoint, "endpoint", source_path)

    messages_format = data.get("messages_format", "openai")
    if messages_format not in _MESSAGES_FORMATS:
        raise ConfigError(
            f"messages_format 必须是 {list(_MESSAGES_FORMATS)} 之一{_where(source_path)}"
        )

    headers = _parse_headers(data.get("headers"), source_path)
    body = _parse_body(data.get("body"), source_path)
    content_pointer = _validate_pointer(
        _require_str(data, "response_content_pointer", source_path),
        "response_content_pointer",
        source_path,
    )
    reasoning_pointers = _pointer_tuple(
        data.get("response_reasoning_content_pointers"),
        "response_reasoning_content_pointers",
        source_path,
    )
    text_blocks_pointer: str | None = None
    if data.get("response_text_blocks_pointer") is not None:
        text_blocks_pointer = _validate_pointer(
            _require_str(data, "response_text_blocks_pointer", source_path),
            "response_text_blocks_pointer",
            source_path,
        )
    default_max_output_tokens = _non_negative_int(
        data.get("default_max_output_tokens"),
        "default_max_output_tokens",
        source_path,
    )
    models = _parse_models(data.get("models"), source_path)
    usage = _parse_usage(data.get("usage"), source_path)

    streaming: StreamingSpec | None = None
    if data.get("streaming") is not None:
        try:
            streaming = _validate_streaming(data["streaming"])
        except ConfigError as exc:
            raise ConfigError(f"{exc}{_where(source_path)}") from exc

    return JSONAdapter(
        adapter_id=adapter_id,
        endpoint=endpoint,
        headers_template=headers,
        body_template=body,
        response_content_pointer=content_pointer,
        messages_format=str(messages_format),
        reasoning_pointers=reasoning_pointers,
        model_discovery=models,
        usage=usage,
        streaming=streaming,
        schema_version=_SCHEMA_VERSION,
        source_path=source_path,
        response_text_blocks_pointer=text_blocks_pointer,
        default_max_output_tokens=default_max_output_tokens,
    )


def _validate_streaming(value: Any) -> StreamingSpec:
    """校验 ``streaming`` 段并构造 :class:`StreamingSpec`。

    异常:
        ConfigError: 缺少 ``content_events`` / ``terminal``，或条件字段非法。
    """

    if not isinstance(value, dict):
        raise ConfigError("streaming 必须是对象")
    unknown = set(value) - _STREAMING_FIELDS
    if unknown:
        raise ConfigError(f"streaming 未知字段：{sorted(unknown)}")

    if value.get("transport") != "sse":
        raise ConfigError("streaming.transport 必须为 sse")
    endpoint = value.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ConfigError("streaming.endpoint 必须是非空字符串")
    endpoint = endpoint.strip()
    _require_relative_endpoint(endpoint, "streaming.endpoint", "")
    _validate_placeholder_names(endpoint, "streaming.endpoint", "")

    request_body = _require_mapping(value.get("request_body"), "streaming.request_body")
    content_events = _parse_stream_rules(value.get("content_events"), "streaming.content_events")
    if not content_events:
        raise ConfigError("streaming.content_events 不能为空")
    reasoning_events = _parse_stream_rules(value.get("reasoning_events"), "streaming.reasoning_events")

    sentinel, terminal_when = _parse_terminal(value.get("terminal"))

    allow_clean_eof = value.get("allow_clean_eof", False)
    if not isinstance(allow_clean_eof, bool):
        raise ConfigError("streaming.allow_clean_eof 必须是布尔值")
    error_events = _parse_error_events(value.get("error_events"))
    usage = _parse_stream_usage(value.get("usage"))

    return StreamingSpec(
        endpoint=endpoint,
        content_events=content_events,
        terminal_sentinel=sentinel,
        terminal_when=terminal_when,
        reasoning_events=reasoning_events,
        request_body=request_body,
        error_events=error_events,
        allow_clean_eof=allow_clean_eof,
        usage=usage,
    )


def _render_placeholders(template: str, values: dict[str, Any]) -> str:
    """替换模板字符串中的 ``${name}`` 占位符。

    异常:
        ConfigError: 出现白名单外的占位符，或缺少对应取值。
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in _ALLOWED_PLACEHOLDERS:
            raise ConfigError(f"未知占位符：${{{name}}}")
        if name not in values:
            raise ConfigError(f"占位符 ${{{name}}} 缺少取值")
        return str(values[name])

    return _PLACEHOLDER_RE.sub(replace, template)


def _non_negative_int(value: Any, field: str, source_path: str = "") -> int:
    """校验可选的非负整数字段；``None`` 返回 ``0``（布尔值非法）。"""
    if value is None:
        return 0
    if type(value) is not int or value < 0:
        raise ConfigError(f"{field} 必须是非负整数{_where(source_path)}")
    return value


def _require_str(data: dict[str, Any], field: str, source_path: str) -> str:
    """取出必填的非空字符串字段。"""
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} 必须是非空字符串{_where(source_path)}")
    return value.strip()


def _require_relative_endpoint(value: str, field: str, source_path: str) -> None:
    """校验 endpoint 是相对路径（不含协议与主机）。"""
    if "://" in value or value.startswith("//"):
        raise ConfigError(f"{field} 必须是相对路径：{value}{_where(source_path)}")


def _require_mapping(value: Any, field: str, source_path: str = "") -> dict[str, Any]:
    """把可选字段规范化为映射；``None`` 视为空映射。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{field} 必须是对象{_where(source_path)}")
    for key in value:
        if not isinstance(key, str):
            raise ConfigError(f"{field} 的键必须是字符串{_where(source_path)}")
    return value


def _parse_headers(value: Any, source_path: str) -> dict[str, str]:
    """校验请求头模板：值必须是字符串，可含白名单占位符。"""
    mapping = _require_mapping(value, "headers", source_path)
    headers: dict[str, str] = {}
    for key, raw in mapping.items():
        if not isinstance(raw, str):
            raise ConfigError(f"headers.{key} 必须是字符串{_where(source_path)}")
        _validate_placeholder_names(raw, f"headers.{key}", source_path)
        headers[key] = raw
    return headers


def _parse_body(value: Any, source_path: str) -> dict[str, Any]:
    """校验请求体模板，并检查占位符是否独占整个字符串。"""
    mapping = _require_mapping(value, "body", source_path)
    _check_body_strings(mapping, "body", source_path)
    return mapping


def _check_body_strings(value: Any, field: str, source_path: str) -> None:
    """递归检查请求体中的字符串：含占位符时必须独占整个字符串。"""
    if isinstance(value, str):
        if "${" not in value:
            return
        names = _validate_placeholder_names(value, field, source_path)
        if not _PLACEHOLDER_RE.fullmatch(value) or len(names) != 1:
            raise ConfigError(f"{field} 的占位符必须独占整个字符串：{value}{_where(source_path)}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _check_body_strings(item, f"{field}.{key}", source_path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_body_strings(item, f"{field}[{index}]", source_path)


def _validate_placeholder_names(text: str, field: str, source_path: str) -> list[str]:
    """校验文本中的占位符都在白名单内，返回占位符名列表。"""
    names = _PLACEHOLDER_RE.findall(text)
    for name in names:
        if name not in _ALLOWED_PLACEHOLDERS:
            raise ConfigError(f"{field} 含未知占位符：${{{name}}}{_where(source_path)}")
    return names


def _validate_pointer(pointer: str, field: str, source_path: str = "") -> str:
    """校验扩展 JSON Pointer 的语法（RFC6901 + 负索引）。

    这里只做语法校验，不做求值：求值由 ``core.llm.pointer`` 负责。
    空串表示根，合法。
    """
    if pointer == "":
        return pointer
    if not pointer.startswith("/"):
        raise ConfigError(f"{field} 必须是 JSON Pointer（以 / 开头）：{pointer}{_where(source_path)}")
    for token in pointer.split("/")[1:]:
        for index, char in enumerate(token):
            if char == "~" and (index + 1 >= len(token) or token[index + 1] not in "01"):
                raise ConfigError(f"{field} 含非法转义：{pointer}{_where(source_path)}")
        unescaped = token.replace("~1", "/").replace("~0", "~")
        if unescaped.startswith("-"):
            digits = unescaped[1:]
            if not digits.isdigit() or digits.startswith("0"):
                raise ConfigError(f"{field} 含非法数组索引：{pointer}{_where(source_path)}")
    return pointer


def _pointer_tuple(value: Any, field: str, source_path: str) -> tuple[str, ...]:
    """校验一个可选字符串数组字段（如 ``response_reasoning_content_pointers``）。"""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} 必须是数组{_where(source_path)}")
    pointers: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ConfigError(f"{field}[{index}] 必须是字符串{_where(source_path)}")
        pointers.append(_validate_pointer(item, f"{field}[{index}]", source_path))
    return tuple(pointers)


def _parse_models(value: Any, source_path: str) -> dict[str, Any] | None:
    """校验模型发现（``models``）段；未声明时返回 ``None``。

    约定（见 ``docs/protocols/provider.md``）：``response_models_pointer`` 是扩展 JSON Pointer，
    指向模型数组；``response_model_id`` / ``response_model_display`` 是数组元素内的相对键名；
    ``response_model_strip_prefix`` 是需要从模型名中剥掉的字面前缀。
    """
    if value is None:
        return None
    mapping = _require_mapping(value, "models", source_path)
    unknown = set(mapping) - _MODEL_FIELDS
    if unknown:
        raise ConfigError(f"models 未知字段：{sorted(unknown)}{_where(source_path)}")
    result: dict[str, Any] = {}
    for key, raw in mapping.items():
        if not isinstance(raw, str) or not raw.strip():
            raise ConfigError(f"models.{key} 必须是非空字符串{_where(source_path)}")
        result[key] = raw.strip()
    for required in _MODEL_REQUIRED_FIELDS:
        if required not in result:
            raise ConfigError(f"models 缺少必填字段：{required}{_where(source_path)}")
    _require_relative_endpoint(str(result["endpoint"]), "models.endpoint", source_path)
    result["response_models_pointer"] = _validate_pointer(
        str(result["response_models_pointer"]), "models.response_models_pointer", source_path
    )
    return result


def _parse_usage(value: Any, source_path: str) -> UsageSpec:
    """校验非流式 ``usage`` 段并返回 :class:`UsageSpec`（前三个字段是单指针）。"""
    if value is None:
        return UsageSpec()
    mapping = _require_mapping(value, "usage", source_path)
    unknown = set(mapping) - set(_USAGE_FIELDS) - set(_USAGE_LIST_FIELDS)
    if unknown:
        raise ConfigError(f"usage 未知字段：{sorted(unknown)}{_where(source_path)}")
    pointers: dict[str, tuple[str, ...]] = {}
    for key in _USAGE_FIELDS:
        raw = mapping.get(key)
        if raw is None:
            pointers[key] = ()
            continue
        if not isinstance(raw, str) or not raw.strip():
            raise ConfigError(f"usage.{key} 必须是非空字符串{_where(source_path)}")
        pointers[key] = (_validate_pointer(raw.strip(), f"usage.{key}", source_path),)
    cached = _pointer_tuple(mapping.get(_USAGE_LIST_FIELDS[0]), f"usage.{_USAGE_LIST_FIELDS[0]}", source_path)
    extra = _pointer_tuple(mapping.get(_USAGE_LIST_FIELDS[1]), f"usage.{_USAGE_LIST_FIELDS[1]}", source_path)
    if not any((*pointers.values(), cached, extra)):
        raise ConfigError(f"usage 至少需要声明一个指针{_where(source_path)}")
    return UsageSpec(
        input=pointers[_USAGE_FIELDS[0]],
        output=pointers[_USAGE_FIELDS[1]],
        total=pointers[_USAGE_FIELDS[2]],
        cached=cached,
        extra_input=extra,
    )


def _parse_terminal(value: Any) -> tuple[str | None, StreamCondition | None]:
    """校验 ``streaming.terminal``：``sentinel`` 与 ``when`` 二选一且必须声明一个。"""
    field = "streaming.terminal"
    if value is None:
        raise ConfigError("streaming.terminal 必须声明 sentinel 或 when 之一")
    if not isinstance(value, dict):
        raise ConfigError(f"{field} 必须是对象")
    unknown = set(value) - _TERMINAL_FIELDS
    if unknown:
        raise ConfigError(f"{field} 未知字段：{sorted(unknown)}")
    sentinel: str | None = None
    condition: StreamCondition | None = None
    if "sentinel" in value:
        raw = value["sentinel"]
        if not isinstance(raw, str) or not raw:
            raise ConfigError(f"{field}.sentinel 必须是非空字符串")
        sentinel = raw
    if value.get("when") is not None:
        condition = _parse_condition(value["when"], f"{field}.when")
    if sentinel is None and condition is None:
        raise ConfigError(f"{field} 必须声明 sentinel 或 when 之一")
    if sentinel is not None and condition is not None:
        raise ConfigError(f"{field} 只能声明 sentinel 或 when 之一")
    return sentinel, condition


def _parse_condition(value: Any, field: str) -> StreamCondition:
    """校验流式事件的匹配条件。"""
    if not isinstance(value, dict):
        raise ConfigError(f"{field} 必须是对象")
    unknown = set(value) - _CONDITION_FIELDS
    if unknown:
        raise ConfigError(f"{field} 未知字段：{sorted(unknown)}")
    pointer_raw = value.get("pointer")
    if not isinstance(pointer_raw, str):
        raise ConfigError(f"{field}.pointer 必须是字符串")
    pointer = _validate_pointer(pointer_raw, f"{field}.pointer")

    has_equals = "equals" in value
    has_exists = "exists" in value
    if has_equals and has_exists:
        raise ConfigError(f"{field} 只能声明 equals 或 exists 之一")
    if not has_equals and not has_exists:
        raise ConfigError(f"{field} 必须声明 equals 或 exists")
    if has_exists:
        exists = value["exists"]
        if not isinstance(exists, bool):
            raise ConfigError(f"{field}.exists 必须是布尔值")
        if not exists:
            raise ConfigError(f"{field}.exists 只能为 true（用于判断路径存在）")
        return StreamCondition(pointer=pointer, exists=True)
    return StreamCondition(pointer=pointer, equals=value["equals"])


def _parse_stream_rules(value: Any, field: str) -> tuple[StreamRule, ...]:
    """校验 ``content_events`` / ``reasoning_events`` 规则数组。"""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} 必须是数组")
    rules: list[StreamRule] = []
    for index, item in enumerate(value):
        name = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{name} 必须是对象")
        unknown = set(item) - _STREAM_RULE_FIELDS
        if unknown:
            raise ConfigError(f"{name} 未知字段：{sorted(unknown)}")
        pointer_raw = item.get("pointer")
        if not isinstance(pointer_raw, str):
            raise ConfigError(f"{name}.pointer 必须是字符串")
        pointer = _validate_pointer(pointer_raw, f"{name}.pointer")
        condition = None
        if item.get("when") is not None:
            condition = _parse_condition(item["when"], f"{name}.when")
        text_blocks = item.get("text_blocks", False)
        if not isinstance(text_blocks, bool):
            raise ConfigError(f"{name}.text_blocks 必须是布尔值")
        rules.append(StreamRule(pointer=pointer, when=condition, text_blocks=text_blocks))
    return tuple(rules)


def _parse_error_events(value: Any) -> tuple[tuple[StreamCondition, str, str | None], ...]:
    """校验 ``streaming.error_events``。"""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("streaming.error_events 必须是数组")
    events: list[tuple[StreamCondition, str, str | None]] = []
    for index, item in enumerate(value):
        name = f"streaming.error_events[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{name} 必须是对象")
        unknown = set(item) - _ERROR_EVENT_FIELDS
        if unknown:
            raise ConfigError(f"{name} 未知字段：{sorted(unknown)}")
        if item.get("when") is None:
            raise ConfigError(f"{name} 缺少 when")
        condition = _parse_condition(item["when"], f"{name}.when")
        message_raw = item.get("message_pointer")
        if not isinstance(message_raw, str):
            raise ConfigError(f"{name}.message_pointer 必须是字符串")
        message_pointer = _validate_pointer(message_raw, f"{name}.message_pointer")
        status_pointer: str | None = None
        if item.get("status_pointer") is not None:
            status_raw = item["status_pointer"]
            if not isinstance(status_raw, str):
                raise ConfigError(f"{name}.status_pointer 必须是字符串")
            status_pointer = _validate_pointer(status_raw, f"{name}.status_pointer")
        events.append((condition, message_pointer, status_pointer))
    return tuple(events)


def _parse_stream_usage(
    value: Any,
) -> UsageSpec:
    """校验 ``streaming.usage`` 并返回 :class:`UsageSpec`。"""
    if value is None:
        return UsageSpec()
    mapping = _require_mapping(value, "streaming.usage")
    unknown = set(mapping) - set(_STREAM_USAGE_FIELDS) - set(_USAGE_LIST_FIELDS)
    if unknown:
        raise ConfigError(f"streaming.usage 未知字段：{sorted(unknown)}")
    groups: list[tuple[str, ...]] = []
    for key in _STREAM_USAGE_FIELDS:
        groups.append(_pointer_tuple(mapping.get(key), f"streaming.usage.{key}", ""))
    cached = _pointer_tuple(
        mapping.get(_USAGE_LIST_FIELDS[0]), f"streaming.usage.{_USAGE_LIST_FIELDS[0]}", ""
    )
    extra = _pointer_tuple(
        mapping.get(_USAGE_LIST_FIELDS[1]), f"streaming.usage.{_USAGE_LIST_FIELDS[1]}", ""
    )
    if all(not group for group in (*groups, cached, extra)):
        raise ConfigError("streaming.usage 至少需要声明一个指针")
    return UsageSpec(
        input=groups[0],
        output=groups[1],
        total=groups[2],
        cached=cached,
        extra_input=extra,
    )
