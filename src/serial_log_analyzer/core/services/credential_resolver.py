"""凭据解析：三个来源的优先级合并。

解析顺序（任一命中即停止）：
1. 运行时输入（用户本次会话临时输入，不落盘）；
2. 系统钥匙串（``KeyringStore``）；
3. 环境变量（``EnvironmentReader``）。

全部失败时抛出 :class:`CredentialError`，消息包含已尝试的来源，便于用户排查。
"""

from __future__ import annotations

from serial_log_analyzer.core.errors import CredentialError
from serial_log_analyzer.core.models.provider import CredentialRef
from serial_log_analyzer.core.ports import EnvironmentReader, KeyringStore

__all__ = ["CredentialResolver"]


class CredentialResolver:
    """按优先级解析 Profile 所需的 API Key。

    参数:
        keyring: 钥匙串适配器；不可用时自动跳过该来源。
        environment: 环境变量读取器。
    """

    def __init__(self, keyring: KeyringStore | None, environment: EnvironmentReader) -> None:
        self._keyring = keyring
        self._environment = environment
        self._runtime: dict[str, str] = {}

    def set_runtime_secret(self, credential_id: str, secret: str | None) -> None:
        """记录本次会话的临时密钥；``None`` 表示清除。

        运行时密钥仅保存在内存，进程退出即失效。
        """

        if not credential_id.strip():
            raise CredentialError("凭据标识不能为空")
        if secret is None:
            self._runtime.pop(credential_id, None)
        elif not secret.strip():
            raise CredentialError("运行时密钥不能为空")
        else:
            self._runtime[credential_id] = secret

    def resolve(self, credential: CredentialRef) -> str:
        """解析出密钥。

        参数:
            credential: Profile 中声明的凭据引用。

        返回:
            非空密钥字符串。

        异常:
            CredentialError: 三个来源均未取到密钥，或密钥为空字符串。
        """

        identifier = credential.name or credential.env_var or "runtime"
        runtime = self._runtime.get(identifier)
        if runtime is not None:
            return runtime
        if credential.name and self.keyring_available():
            secret = self._keyring.read(credential.name)
            if secret is not None and secret.strip():
                return secret
        if credential.env_var:
            secret = self._environment.get(credential.env_var)
            if secret is not None and secret.strip():
                return secret
        raise CredentialError("未找到非空 API 密钥；" + self.describe_sources(credential))

    def describe_sources(self, credential: CredentialRef) -> str:
        """返回人类可读的来源说明，用于错误提示与设置界面展示。"""

        sources = ["运行时输入"]
        if credential.name:
            sources.append("系统钥匙串" if self.keyring_available() else "系统钥匙串不可用")
        if credential.env_var:
            sources.append(f"环境变量或本地 .env（{credential.env_var}）")
        return "凭据来源：" + " → ".join(sources)

    def keyring_available(self) -> bool:
        """当前系统钥匙串是否可用（供 UI 置灰选项）。"""

        return self._keyring is not None and self._keyring.available
