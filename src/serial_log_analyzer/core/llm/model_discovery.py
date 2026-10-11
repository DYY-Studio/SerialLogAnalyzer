"""模型发现：按 Adapter 声明的 ``models`` 段拉取并解析服务端模型列表。

职责边界：组装请求（``RequestBuilder``）、累积响应体、按指针解析；网络由 ``io`` 提供。
响应是普通 JSON（非 SSE），因此整包累积后再解析。
"""

from __future__ import annotations

import json
from collections.abc import Callable

from serial_log_analyzer.core.errors import (
    AppError,
    ConfigError,
    PointerError,
    ResponseParseError,
)
from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.llm.pointer import resolve_pointer
from serial_log_analyzer.core.llm.request import RequestBuilder
from serial_log_analyzer.core.models.provider import ModelOption, ProviderProfile
from serial_log_analyzer.core.ports import CredentialProvider, HttpTransport

__all__ = ["ModelDiscoveryService", "parse_model_list"]

# 模型列表远小于此；超过即视为异常响应，避免无上限累积。
_MAX_BODY_BYTES = 1 << 20


class ModelDiscoveryService:
    """拉取服务端模型列表。

    参数:
        transport: HTTP 传输实现（由 ``io`` 提供）。
        credentials: 凭据解析器。
    """

    def __init__(self, transport: HttpTransport, credentials: CredentialProvider) -> None:
        self._transport = transport
        self._credentials = credentials

    def fetch(
        self,
        adapter: JSONAdapter,
        profile: ProviderProfile,
        on_done: Callable[[list[ModelOption]], None],
        on_error: Callable[[AppError], None],
    ) -> None:
        """异步拉取模型列表；成功与失败回调合计只执行一次。

        参数:
            adapter: 目标 Adapter（需声明 ``models`` 段）。
            profile: 目标 Profile（提供 base_url 与凭据引用）。
            on_done: 成功回调，携带模型列表。
            on_error: 失败回调（网络、状态码、解析错误）。

        异常:
            ConfigError: 本地组装失败（未声明 ``models`` 段、请求头冲突等），同步抛出。
            CredentialError: 未取到密钥，同步抛出。
        """

        request = RequestBuilder(adapter, profile, self._credentials).build_model_list()
        buffer = bytearray()

        def _chunk(data: bytes) -> None:
            buffer.extend(data)
            if len(buffer) > _MAX_BODY_BYTES:
                raise ResponseParseError("模型列表响应过大")

        def _done() -> None:
            try:
                payload = json.loads(bytes(buffer).decode("utf-8"))
                options = parse_model_list(adapter, payload)
            except AppError as exc:
                on_error(exc)
            except (ValueError, UnicodeDecodeError) as exc:
                on_error(ResponseParseError(f"模型列表响应不是合法 JSON：{exc}"))
            else:
                on_done(options)

        self._transport.send(request, _chunk, _done, on_error)


def parse_model_list(adapter: JSONAdapter, payload: object) -> list[ModelOption]:
    """按 Adapter 的 ``models`` 声明从响应正文取出模型列表。

    参数:
        adapter: 提供 ``models`` 段（指针、id 键名、可选展示名与前缀）。
        payload: 已解析的 JSON 响应正文。

    返回:
        模型列表；``model_id`` 已按 ``response_model_strip_prefix`` 处理。

    异常:
        ConfigError: Adapter 未声明 ``models`` 段。
        ResponseParseError: 路径缺失、类型不符或结果为空。
    """

    spec = adapter.model_discovery
    if spec is None:
        raise ConfigError(f"Adapter {adapter.adapter_id} 未声明 models 段，无法拉取模型列表")
    raw = _resolve(payload, str(spec["response_models_pointer"]))
    if not isinstance(raw, list):
        raise ResponseParseError("模型列表路径指向的不是数组")
    id_key = str(spec.get("response_model_id", "id"))
    display_key = str(spec.get("response_model_display", "") or "")
    strip = str(spec.get("response_model_strip_prefix", "") or "")
    options: list[ModelOption] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ResponseParseError(f"模型列表第 {index} 项不是对象")
        model_id = item.get(id_key)
        if not isinstance(model_id, str) or not model_id:
            raise ResponseParseError(f"模型列表第 {index} 项缺少字段 {id_key}")
        if strip and model_id.startswith(strip):
            model_id = model_id[len(strip) :]
        display = item.get(display_key) if display_key else None
        options.append(
            ModelOption(model_id, display if isinstance(display, str) and display else model_id)
        )
    if not options:
        raise ResponseParseError("服务端未返回任何模型")
    return options


def _resolve(payload: object, pointer: str) -> object:
    """按指针取值，把指针错误统一为 :class:`ResponseParseError`。"""

    try:
        return resolve_pointer(payload, pointer)
    except PointerError as exc:
        raise ResponseParseError(f"模型列表路径不存在：{pointer}") from exc
