"""凭据解析：三个来源的优先级合并。

解析顺序（任一命中即停止）：
1. 运行时输入（用户本次会话临时输入，不落盘）；
2. 系统钥匙串（``KeyringStore``）；
3. 环境变量（``EnvironmentReader``）。

全部失败时抛出 :class:`CredentialError`，消息包含已尝试的来源，便于用户排查。
"""

from __future__ import annotations

from serial_log_analyzer.core.models.provider import CredentialRef
from serial_log_analyzer.core.ports import EnvironmentReader, KeyringStore

__all__ = ["CredentialResolver"]


class CredentialResolver:
    """按优先级解析 Profile 所需的 API Key。

    参数:
        keyring: 钥匙串适配器；不可用时自动跳过该来源。
        environment: 环境变量读取器。
    """

    def __init__(self, keyring: KeyringStore, environment: EnvironmentReader) -> None:
        raise NotImplementedError

    def set_runtime_secret(self, credential_id: str, secret: str | None) -> None:
        """记录本次会话的临时密钥；``None`` 表示清除。

        运行时密钥仅保存在内存，进程退出即失效。
        """

        raise NotImplementedError

    def resolve(self, credential: CredentialRef) -> str:
        """解析出密钥。

        参数:
            credential: Profile 中声明的凭据引用。

        返回:
            非空密钥字符串。

        异常:
            CredentialError: 三个来源均未取到密钥，或密钥为空字符串。
        """

        raise NotImplementedError

    def describe_sources(self, credential: CredentialRef) -> str:
        """返回人类可读的来源说明，用于错误提示与设置界面展示。"""

        raise NotImplementedError

    def keyring_available(self) -> bool:
        """当前系统钥匙串是否可用（供 UI 置灰选项）。"""

        raise NotImplementedError
