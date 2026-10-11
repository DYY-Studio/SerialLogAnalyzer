"""core 对外部能力的抽象接口（Ports）。

依赖倒置：``core`` 只依赖本模块中的 ``Protocol``，真实实现位于 ``io`` 层，
测试时使用 Fake 实现，因此绝大多数业务测试不需要 Qt。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.models.device import SerialConfig, SerialPortInfo
from serial_log_analyzer.core.models.provider import CredentialRef, HttpRequest

__all__ = [
    "BytesHandler",
    "CancellationToken",
    "CredentialProvider",
    "EnvironmentReader",
    "ErrorHandler",
    "HttpTransport",
    "KeyringStore",
    "ResourceLoader",
    "SerialTransport",
    "SettingsStore",
    "VoidHandler",
]

BytesHandler = Callable[[bytes], None]
VoidHandler = Callable[[], None]
ErrorHandler = Callable[[AppError], None]


class CancellationToken(Protocol):
    """用于取消进行中的异步请求。"""

    def cancel(self) -> None:
        """请求取消；已结束的请求调用应为空操作。"""


@runtime_checkable
class SerialTransport(Protocol):
    """串口字节流传输接口。

    实现要求：
    - 只处理字节流，不解释业务语义；
    - 不假设一次回调恰好对应一行数据；
    - 错误必须以 :class:`AppError` 子类通过 ``on_error`` 上报。
    """

    def set_handlers(self, on_bytes: BytesHandler, on_error: ErrorHandler) -> None:
        """注册数据与错误回调。"""

    def list_ports(self) -> list[SerialPortInfo]:
        """枚举当前系统可用串口。"""

    def open(self, config: SerialConfig) -> None:
        """按配置打开串口。

        异常:
            SerialConnectionError: 打开失败。
        """

    def close(self) -> None:
        """关闭串口；未打开时为空操作。"""

    def write(self, data: bytes) -> None:
        """写入原始字节。

        异常:
            SerialWriteError: 写入失败。
        """

    @property
    def is_open(self) -> bool:
        """串口当前是否已打开。"""


@runtime_checkable
class HttpTransport(Protocol):
    """HTTP 请求传输接口（单次请求 + 回调式流式读取）。"""

    def send(
        self,
        request: HttpRequest,
        on_chunk: BytesHandler,
        on_done: VoidHandler,
        on_error: ErrorHandler,
    ) -> CancellationToken:
        """发送请求并注册回调。

        参数:
            request: 与 Qt 无关的请求描述。
            on_chunk: 收到响应字节分块时调用（非流式请求也会分块到达）。
            on_done: 请求正常结束时调用一次。
            on_error: 请求失败（网络错误、超时、非 2xx）时调用一次。

        返回:
            可用于取消该请求的令牌。
        """


@runtime_checkable
class SettingsStore(Protocol):
    """简单键值设置存储（窗口布局、最近串口等）。"""

    def get(self, key: str, default: Any = None) -> Any:
        """读取键值；不存在时返回 ``default``。"""

    def set(self, key: str, value: Any) -> None:
        """写入键值并持久化。"""


@runtime_checkable
class KeyringStore(Protocol):
    """系统钥匙串适配接口。"""

    @property
    def available(self) -> bool:
        """系统钥匙串后端是否可用。"""

    def read(self, credential_id: str) -> str | None:
        """读取凭据；不存在时返回 ``None``。"""

    def save(self, credential_id: str, secret: str) -> None:
        """写入或覆盖凭据。"""

    def delete(self, credential_id: str) -> None:
        """删除凭据；不存在时为空操作。"""


@runtime_checkable
class EnvironmentReader(Protocol):
    """环境变量读取接口（便于测试替换）。"""

    def get(self, name: str) -> str | None:
        """读取环境变量；不存在时返回 ``None``。"""


@runtime_checkable
class ResourceLoader(Protocol):
    """声明式资源（Preset / Adapter / Prompt）读取接口。

    资源可来自仓库目录、用户配置目录或打包内置资源，具体优先级由实现决定。
    """

    def read_text(self, relative_path: str) -> str:
        """读取文本资源。

        参数:
            relative_path: 相对资源根的路径，例如 ``presets/logs/hi3861-default.yaml``。

        异常:
            ConfigError: 资源不存在或不可读。
        """

    def list_files(self, relative_dir: str, pattern: str) -> list[str]:
        """列出匹配的资源文件相对路径。

        参数:
            relative_dir: 相对资源根目录。
            pattern: 文件名匹配模式，例如 ``*.yaml``。
        """


class CredentialProvider(Protocol):
    """LLM 请求所需的凭据解析端口；由凭据服务实现。"""

    def resolve(self, credential: CredentialRef) -> str:
        """根据引用返回非空密钥；不可用时抛出 ``CredentialError``。"""

