"""LLM Provider 领域模型：HTTP 请求描述、凭据引用与流式事件。

这些类型是 ``core`` 与 ``io`` 之间的传输契约：``core`` 产出
:class:`HttpRequest`，``io`` 负责把它转换为 ``QNetworkRequest`` 并发送；
``io`` 再把网络分块与结束事件回传给 ``core`` 的解析器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "CredentialKind",
    "CredentialRef",
    "HttpRequest",
    "ProviderProfile",
    "StreamEvent",
]


class CredentialKind(Enum):
    """凭据来源类型。"""

    KEYRING = "keyring"
    ENVIRONMENT = "environment"
    RUNTIME = "runtime"


@dataclass(frozen=True)
class CredentialRef:
    """Profile 中声明的凭据引用（不含 secret 本身）。

    参数:
        kind: 凭据来源类型。
        name: keyring 账号名（``kind=KEYRING`` 时使用）。
        env_var: 环境变量名（``kind=ENVIRONMENT`` 时使用）。
    """

    kind: CredentialKind
    name: str = ""
    env_var: str = ""


@dataclass(frozen=True)
class HttpRequest:
    """与 Qt 无关的 HTTP 请求描述。

    参数:
        method: HTTP 方法，首版固定为 ``POST``。
        url: 完整请求 URL（已由 ``base_url`` 与 Adapter ``endpoint`` 拼接）。
        headers: 请求头，值已完成占位符替换。
        body: 请求体对象，由 ``io`` 序列化为 JSON 字节。
        timeout_seconds: 超时时间。
        stream: 是否为流式请求（影响读取方式与空行刷新策略）。
    """

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, object] = field(default_factory=dict)
    timeout_seconds: float = 120.0
    stream: bool = False


@dataclass(frozen=True)
class StreamEvent:
    """SSE 解析后的单个事件载荷。

    参数:
        data: ``data:`` 行的原始载荷（可能为 ``[DONE]`` 哨兵或 JSON 文本）。
        event: 可选的事件名（``event:`` 行）。
        raw: 原始事件文本，便于诊断。
    """

    data: str
    event: str | None = None
    raw: str = ""


@dataclass(frozen=True)
class ProviderProfile:
    """一个可用的模型服务配置档。

    参数:
        profile_id: 唯一标识。
        adapter_id: 引用的 Adapter 标识。
        base_url: 服务基地址，如 ``https://api.openai.com/v1``。
        model: 模型名。
        credential: 凭据引用。
        stream: 是否启用流式。
        request_timeout_seconds: 请求超时。
        extra_body: 追加到请求体的字段（与 Adapter 声明冲突时报错）。
        extra_headers: 追加请求头。
    """

    profile_id: str
    adapter_id: str
    base_url: str
    model: str
    credential: CredentialRef = field(default_factory=lambda: CredentialRef(CredentialKind.RUNTIME))
    stream: bool = True
    request_timeout_seconds: float = 120.0
    extra_body: dict[str, object] = field(default_factory=dict)
    extra_headers: dict[str, str] = field(default_factory=dict)
