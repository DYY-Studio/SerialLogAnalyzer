"""请求组装：把 Profile、Adapter、上下文与对话历史拼装为 :class:`HttpRequest`。

职责边界：
- 计算最终 URL（``base_url`` + Adapter endpoint，支持 ``${model}`` 替换）；
- 解析凭据（通过 :class:`CredentialResolver`）；
- 调用 Adapter 渲染 headers 与 body；
- 产出与 Qt 无关的 :class:`HttpRequest`。
"""

from __future__ import annotations

import math
from urllib.parse import quote

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.models.analysis import AnalysisMessage, AnalysisRequest
from serial_log_analyzer.core.models.provider import HttpRequest, ProviderProfile
from serial_log_analyzer.core.ports import CredentialProvider

__all__ = ["RequestBuilder", "join_url"]


def join_url(base_url: str, endpoint: str, model: str = "") -> str:
    """拼接基地址与端点，并替换 ``${model}`` 占位符。

    参数:
        base_url: 形如 ``https://api.openai.com/v1`` 的基地址。
        endpoint: 形如 ``/chat/completions`` 或 ``/models/${model}:generateContent`` 的端点。
        model: 用于替换 ``${model}`` 的模型名。

    返回:
        完整请求 URL。
    """

    base = base_url.rstrip("/")
    path = endpoint.replace("${model}", quote(model, safe=""))
    return base + "/" + path.lstrip("/")


class RequestBuilder:
    """把分析请求组装为可发送的 HTTP 请求。

    参数:
        adapter: 目标 Adapter。
        profile: 目标 Profile。
        credentials: 凭据解析器。
    """

    def __init__(
        self,
        adapter: JSONAdapter,
        profile: ProviderProfile,
        credentials: CredentialProvider,
    ) -> None:
        if adapter.adapter_id != profile.adapter_id:
            raise ConfigError("Profile 与 Adapter 不匹配")
        if profile.stream and not adapter.streaming_supported:
            raise ConfigError("当前 Adapter 不支持流式")
        self._adapter = adapter
        self._profile = profile
        self._credentials = credentials

    def build_model_list(self) -> HttpRequest:
        """组装模型列表请求（``GET``，非流式）。

        返回:
            :class:`HttpRequest`；URL 由 ``base_url`` 与 Adapter 的 ``models.endpoint`` 拼接，
            请求头复用 Adapter 模板（含凭据解析）。

        异常:
            ConfigError: Adapter 未声明 ``models`` 段。
            CredentialError: 未取到密钥。
        """

        spec = self._adapter.model_discovery
        if spec is None:
            raise ConfigError(
                f"Adapter {self._adapter.adapter_id} 未声明 models 段，无法拉取模型列表"
            )
        profile = self._profile
        headers = self._adapter.render_headers(
            api_key=self._credentials.resolve(profile.credential),
            model=profile.model,
            extra_headers=profile.extra_headers,
        )
        # GET 无请求体，去掉模板里的 Content-Type。
        headers = {name: value for name, value in headers.items() if name.lower() != "content-type"}
        return HttpRequest(
            "GET",
            join_url(profile.base_url, str(spec["endpoint"]), profile.model),
            headers,
            {},
            profile.request_timeout_seconds,
            False,
        )

    def build(
        self,
        messages: list[AnalysisMessage],
        request: AnalysisRequest,
    ) -> HttpRequest:
        """组装请求。

        参数:
            messages: 完整对话消息列表（system + 历史 + 本轮 user）。
            request: 分析请求（提供 temperature 与 max_output_tokens）。

        返回:
            :class:`HttpRequest`，交由 ``io`` 层发送。

        异常:
            CredentialError: 三个来源均未取到密钥。
            ConfigError: 占位符或字段冲突。
        """

        if (
            type(request.temperature) not in (int, float)
            or not math.isfinite(request.temperature)
            or request.temperature < 0
        ):
            raise ConfigError("temperature 必须是有限非负数")
        if type(request.max_output_tokens) is not int or request.max_output_tokens < 0:
            raise ConfigError("输出 token 上限必须为非负整数")
        profile = self._profile
        adapter = self._adapter
        headers, body = adapter.build_request(
            api_key=self._credentials.resolve(profile.credential),
            model=profile.model,
            messages=messages,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            stream=profile.stream,
            extra_body=profile.extra_body,
            extra_headers=profile.extra_headers,
        )
        endpoint = adapter.streaming.endpoint if profile.stream else adapter.endpoint
        return HttpRequest(
            "POST",
            join_url(profile.base_url, endpoint, profile.model),
            headers,
            body,
            profile.request_timeout_seconds,
            profile.stream,
        )
