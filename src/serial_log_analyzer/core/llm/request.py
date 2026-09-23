"""请求组装：把 Profile、Adapter、上下文与对话历史拼装为 :class:`HttpRequest`。

职责边界：
- 计算最终 URL（``base_url`` + Adapter endpoint，支持 ``${model}`` 替换）；
- 解析凭据（通过 :class:`CredentialResolver`）；
- 调用 Adapter 渲染 headers 与 body；
- 产出与 Qt 无关的 :class:`HttpRequest`。
"""

from __future__ import annotations

from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.models.analysis import AnalysisMessage, AnalysisRequest
from serial_log_analyzer.core.models.provider import HttpRequest, ProviderProfile
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver

__all__ = ["RequestBuilder", "join_url"]


def join_url(base_url: str, endpoint: str, model: str = "") -> str:
    """拼接基地址与端点，并替换 ``${model}`` 占位符。

    参数:
        base_url: 形如 ``https://api.openai.com/v1`` 的基地址。
        endpoint: 形如 ``/chat/completions`` 或 ``/models/${model}:generateContent`` 的端点。
        model: 用于替换 ``${model}`` 的模型名。

    返回:
        完整请求 URL。

    异常:
        ConfigError: 基地址不是合法 HTTP(S) URL。
    """

    raise NotImplementedError


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
        credentials: CredentialResolver,
    ) -> None:
        raise NotImplementedError

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

        raise NotImplementedError
