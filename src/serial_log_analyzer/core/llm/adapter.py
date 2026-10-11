"""LLM Adapter：把 YAML 声明解释为请求模板与响应提取规则。

Adapter 描述“如何调用某一类模型接口”，与具体 ``base_url`` / ``model`` 解耦；
后者由 Provider Profile 提供。

支持：OpenAI 兼容、OpenAI Responses、Anthropic、Google Gemini。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from string import Template
from typing import Any

from serial_log_analyzer.core.errors import (
    ConfigError,
    PointerError,
    ProviderError,
    ResponseParseError,
)
from serial_log_analyzer.core.llm.pointer import resolve_pointer
from serial_log_analyzer.core.models.analysis import AnalysisMessage, TokenUsage
from serial_log_analyzer.core.models.provider import StreamEvent

__all__ = ["JSONAdapter", "StreamCondition", "StreamRule", "StreamingSpec", "UsageSpec", "build_usage"]


@dataclass(frozen=True)
class UsageSpec:
    """用量字段路径声明。

    参数:
        input / output / total: 各字段的候选指针，按序尝试、取第一个命中的值。
        cached: 缓存命中 token 的候选指针；只用于展示，不改变输入总量。
        extra_input: 这些指针上的值全部相加后计入输入总量，用于「``input`` 不含缓存部分」的
            Provider（如 Anthropic 的 ``cache_read`` + ``cache_creation``）。
    """

    input: tuple[str, ...] = ()
    output: tuple[str, ...] = ()
    total: tuple[str, ...] = ()
    cached: tuple[str, ...] = ()
    extra_input: tuple[str, ...] = ()


@dataclass(frozen=True)
class StreamCondition:
    """流式事件的匹配条件。

    参数:
        pointer: 条件取值所在路径。
        equals: 期望相等的值；``None`` 表示仅检查 ``exists``。
        exists: 仅判断路径是否存在。
    """

    pointer: str
    equals: Any = None
    exists: bool = False
    match_equals: bool = True


@dataclass(frozen=True)
class StreamRule:
    """从流式事件中提取增量文本的规则。

    参数:
        pointer: 增量文本所在路径。
        when: 可选匹配条件；不满足时跳过该规则。
    """

    pointer: str
    when: StreamCondition | None = None
    text_blocks: bool = False


@dataclass(frozen=True)
class StreamingSpec:
    """流式接口声明。

    参数:
        endpoint: 流式端点（可与非流式不同，例如 Gemini 的 ``:streamGenerateContent``）。
        request_body: 流式请求追加字段（与非流式 ``body`` 合并，冲突时报错）。
        content_events: 正文增量规则。
        reasoning_events: 思考正文增量规则；无则为空。
        terminal_sentinel: 终止哨兵（如 ``[DONE]``）；无则用 ``terminal_when``。
        terminal_when: 终止条件。
        error_events: 错误事件规则（条件 + 消息路径 + 可选状态码路径）。
        allow_clean_eof: 服务端未发终止事件即关闭连接时，是否视为正常结束。
    """

    endpoint: str
    content_events: tuple[StreamRule, ...]
    terminal_sentinel: str | None = None
    terminal_when: StreamCondition | None = None
    reasoning_events: tuple[StreamRule, ...] = ()
    request_body: dict[str, Any] = field(default_factory=dict)
    error_events: tuple[tuple[StreamCondition, str, str | None], ...] = ()
    allow_clean_eof: bool = False
    usage: UsageSpec = UsageSpec()


@dataclass(frozen=True)
class JSONAdapter:
    """一个模型接口的声明式适配器。

    参数:
        adapter_id: 唯一标识。
        endpoint: 非流式端点，可含 ``${model}`` 占位符。
        headers_template: 请求头模板，支持 ``${api_key}`` 等占位符。
        body_template: 请求体模板，字符串值可为 ``${model}`` / ``${messages}`` 等占位符。
        response_content_pointer: 非流式响应正文的扩展 JSON Pointer。
        messages_format: 消息转换格式：``openai`` / ``anthropic`` / ``gemini``。
        reasoning_pointers: 思考正文候选路径（按序尝试）。
        model_discovery: 模型列表接口声明（可选）。
        usage: 用量统计路径声明（input / output / total，另有可选的缓存命中与计入输入的额外项）。
        streaming: 流式声明；``None`` 表示不支持流式。
        schema_version: 声明文件版本，当前为 ``3``。
        source_path: 加载来源路径，用于错误提示。
    """

    adapter_id: str
    endpoint: str
    headers_template: dict[str, str]
    body_template: dict[str, Any]
    response_content_pointer: str
    messages_format: str = "openai"
    reasoning_pointers: tuple[str, ...] = ()
    model_discovery: dict[str, Any] | None = None
    usage: UsageSpec = UsageSpec()
    streaming: StreamingSpec | None = None
    schema_version: int = 3
    source_path: str = ""
    response_text_blocks_pointer: str | None = None
    default_max_output_tokens: int = 0

    @property
    def streaming_supported(self) -> bool:
        """该 Adapter 是否声明了流式能力。"""

        return self.streaming is not None

    def build_request(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[AnalysisMessage],
        temperature: float,
        max_output_tokens: int,
        stream: bool,
        extra_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """渲染请求头与请求体。

        参数:
            api_key: 已解析的密钥。
            model: 模型名。
            messages: 对话消息（含 system）。
            temperature: 采样温度。
            max_output_tokens: 最大输出 token 数；``0`` 时该字段从请求体移除。
            stream: 是否流式；为 ``True`` 时合并 ``streaming.request_body``。
            extra_body: Profile 追加字段；与模板字段冲突时报错。
            extra_headers: Profile 追加请求头；与模板头冲突时报错。

        返回:
            ``(headers, body)`` 二元组。

        异常:
            ConfigError: 占位符未知、字段冲突或未声明流式却请求流式。
        """

        if stream and self.streaming is None:
            raise ConfigError("此 Adapter 不支持流式请求")
        if self.messages_format not in {"openai", "anthropic", "gemini"}:
            raise ConfigError("不支持的消息格式")
        system = "\n\n".join(m.content for m in messages if m.role.value == "system")
        converted = []
        for message in messages:
            role = message.role.value
            if self.messages_format == "openai":
                converted.append({"role": role, "content": message.content})
            elif role != "system":
                if self.messages_format == "anthropic":
                    converted.append({"role": role, "content": message.content})
                else:
                    converted.append(
                        {
                            "role": "model" if role == "assistant" else role,
                            "parts": [{"text": message.content}],
                        }
                    )
        limit = max_output_tokens or self.default_max_output_tokens
        values = {
            "model": model,
            "system": system,
            "messages": converted,
            "temperature": temperature,
            "max_output_tokens": limit,
            "stream": stream,
        }
        body = _render_body(self.body_template, values)
        if stream:
            _merge(body, _render_body(self.streaming.request_body, values))
        _merge(body, deepcopy(extra_body or {}))
        headers = self.render_headers(api_key=api_key, model=model, extra_headers=extra_headers)
        return headers, body

    def render_headers(
        self,
        *,
        api_key: str,
        model: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """渲染请求头模板（模型列表等只读请求同样复用）。

        参数:
            api_key: 已解析的密钥。
            model: 模型名，用于 ``${model}`` 占位符。
            extra_headers: Profile 追加请求头；与模板头冲突时报错。

        返回:
            请求头字典。

        异常:
            ConfigError: 占位符未知或与模板头冲突。
        """

        headers: dict[str, str] = {}
        for name, value in self.headers_template.items():
            try:
                names = Template(value).get_identifiers()
                if any(n not in {"api_key", "model"} for n in names):
                    raise ConfigError("请求头包含未知占位符")
                headers[name] = Template(value).substitute(api_key=api_key, model=model)
            except (KeyError, ValueError) as exc:
                raise ConfigError("请求头模板非法") from exc
        for name, value in (extra_headers or {}).items():
            if name.lower() in {n.lower() for n in headers}:
                raise ConfigError(f"请求头冲突：{name}")
            headers[name] = value
        return headers

    def parse_response(self, payload: Any) -> tuple[str, str | None]:
        """从非流式响应中提取正文与思考正文。

        返回:
            ``(content, reasoning)``；``reasoning`` 缺失时为 ``None``。

        异常:
            ResponseParseError: 路径缺失或类型不是字符串。
        """

        if isinstance(payload, dict) and payload.get("error"):
            raise ProviderError("模型服务返回错误响应")
        try:
            if self.response_text_blocks_pointer is not None:
                blocks = resolve_pointer(payload, self.response_text_blocks_pointer)
                texts = _text_blocks(blocks)
                if not texts:
                    raise ResponseParseError("响应缺少有效文本内容块")
                content = "".join(texts)
            else:
                content = resolve_pointer(payload, self.response_content_pointer)
            if not isinstance(content, str):
                raise ResponseParseError("响应正文必须是字符串")
        except PointerError as exc:
            raise ResponseParseError("响应正文路径不存在") from exc
        reasoning = None
        for pointer in self.reasoning_pointers:
            value = _optional(payload, pointer)
            if value is not None:
                if not isinstance(value, str):
                    raise ResponseParseError("响应 reasoning 必须是字符串")
                reasoning = value
                break
        return content, reasoning

    def extract_usage(self, payload: Any) -> TokenUsage | None:
        """提取并归一化用量；未声明或路径缺失时返回 ``None``。"""

        spec = self.usage
        return build_usage(
            _first_optional(payload, spec.input),
            _first_optional(payload, spec.output),
            _first_optional(payload, spec.total),
            cached_tokens=_first_optional(payload, spec.cached),
            extra_input_tokens=_all_optional(payload, spec.extra_input),
        )

    def stream_content_deltas(self, event: StreamEvent) -> list[str]:
        """从流式事件中提取正文增量。

        异常:
            ProviderError: 未声明流式规则。
        """

        if self.streaming is None:
            raise ProviderError("Adapter 未声明流式规则")
        return self._deltas(event, self.streaming.content_events)

    def stream_reasoning_deltas(self, event: StreamEvent) -> list[str]:
        """从流式事件中提取思考正文增量。"""

        if self.streaming is None:
            raise ProviderError("Adapter 未声明流式规则")
        return self._deltas(event, self.streaming.reasoning_events)

    def is_terminal(self, event: StreamEvent) -> bool:
        """判断事件是否表示流结束（哨兵或终止条件）。"""

        if self.streaming is None:
            raise ProviderError("Adapter 未声明流式规则")
        if self.streaming.terminal_sentinel == event.data:
            return True
        return self.streaming.terminal_when is not None and _matches(
            _payload(event), self.streaming.terminal_when
        )

    def stream_error(self, event: StreamEvent) -> str | None:
        """若事件表示服务端错误，返回用户可读错误信息。"""

        if self.streaming is None:
            raise ProviderError("Adapter 未声明流式规则")
        if self.streaming.terminal_sentinel == event.data:
            return None
        payload = _payload(event)
        if isinstance(payload, dict) and (payload.get("error") or payload.get("object") == "error"):
            return "模型服务返回流式错误"
        for condition, _message_pointer, _status_pointer in self.streaming.error_events:
            if _matches(payload, condition):
                # 不回显不受信任的远端错误正文，防止回显请求中的凭据。
                return "模型服务返回流式错误"
        return None

    def _deltas(self, event: StreamEvent, rules: tuple[StreamRule, ...]) -> list[str]:
        if self.streaming and self.streaming.terminal_sentinel == event.data:
            return []
        payload = _payload(event)
        result = []
        for rule in rules:
            if rule.when is not None and not _matches(payload, rule.when):
                continue
            value = _optional(payload, rule.pointer)
            if value is None:
                continue
            if rule.text_blocks:
                result.extend(_text_blocks(value))
                continue
            if not isinstance(value, str):
                raise ResponseParseError("流式增量必须是字符串")
            if value:
                result.append(value)
        return result


def _optional(payload: Any, pointer: str) -> Any:
    try:
        return resolve_pointer(payload, pointer)
    except PointerError:
        return None


def _payload(event: StreamEvent) -> Any:
    import json

    try:
        payload = json.loads(event.data)
        if not isinstance(payload, dict):
            raise ResponseParseError("流式 JSON 必须是对象")
        return payload
    except (ValueError, TypeError) as exc:
        raise ResponseParseError("流式事件不是合法 JSON") from exc


def _matches(payload: Any, condition: StreamCondition) -> bool:
    try:
        value = resolve_pointer(payload, condition.pointer)
    except PointerError:
        return False
    return condition.exists or (
        condition.match_equals
        and type(value) is type(condition.equals)
        and value == condition.equals
    )


def _merge(target: dict, extra: dict) -> None:
    overlap = target.keys() & extra.keys()
    if overlap:
        raise ConfigError("请求字段冲突：" + ", ".join(sorted(overlap)))
    target.update(extra)


def _render_body(node: Any, values: dict) -> Any:
    if isinstance(node, dict):
        return {
            key: _render_body(value, values)
            for key, value in node.items()
            if not (value == "${max_output_tokens}" and not values["max_output_tokens"])
        }
    if isinstance(node, list):
        return [_render_body(value, values) for value in node]
    if isinstance(node, str) and "$" in node:
        match = re.fullmatch(r"\$\{([a-z_]+)\}", node)
        if not match or match[1] not in values:
            raise ConfigError("请求体包含非法占位符")
        return deepcopy(values[match[1]])
    return deepcopy(node)


def _first_optional(payload: Any, pointers: Sequence[str]) -> Any:
    """按序尝试指针，返回第一个取到的值；都没有时返回 ``None``。"""

    for pointer in pointers:
        value = _optional(payload, pointer)
        if value is not None:
            return value
    return None


def _all_optional(payload: Any, pointers: Sequence[str]) -> list[Any]:
    """取每个指针的值（缺失为 ``None``），供求和类字段使用。"""

    return [_optional(payload, pointer) for pointer in pointers]


def build_usage(
    input_tokens: Any,
    output_tokens: Any,
    total_tokens: Any,
    *,
    cached_tokens: Any = None,
    extra_input_tokens: Sequence[Any] = (),
) -> TokenUsage | None:
    """把 Provider 的原始用量归一化为 :class:`TokenUsage`。

    参数:
        input_tokens / output_tokens / total_tokens: 原始值（可能为 ``None``）。
        cached_tokens: 其中命中提示缓存的输入 token 数，只用于展示。
        extra_input_tokens: 会一并计入输入总量的值（全部相加），例如 Anthropic 的
            ``cache_read_input_tokens`` + ``cache_creation_input_tokens``。

    返回:
        归一化后的用量；所有取值都为 ``None`` 时返回 ``None``。

    异常:
        ResponseParseError: 出现了非「非负整数」的取值。
    """

    numbers = (input_tokens, output_tokens, total_tokens, cached_tokens, *extra_input_tokens)
    if all(value is None for value in numbers):
        return None
    if any(value is not None and (type(value) is not int or value < 0) for value in numbers):
        raise ResponseParseError("用量必须是非负整数")
    extra = sum(value for value in extra_input_tokens if value is not None)
    input_total = (input_tokens or 0) + extra
    output = output_tokens or 0
    return TokenUsage(
        input_tokens=input_total,
        output_tokens=output,
        total_tokens=total_tokens if total_tokens is not None else input_total + output,
        cached_tokens=cached_tokens or 0,
    )


def _text_blocks(blocks: Any) -> list[str]:
    if not isinstance(blocks, list):
        raise ResponseParseError("响应内容块必须是数组")
    result = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ResponseParseError("响应内容块必须是对象")
        if block.get("type") == "message":
            result.extend(_text_blocks(block.get("content")))
        elif not block.get("thought", False) and (
            block.get("type") in {"text", "output_text"}
            or ("type" not in block and "text" in block)
        ):
            text = block.get("text")
            if not isinstance(text, str):
                raise ResponseParseError("内容块正文必须是字符串")
            result.append(text)
    return result
