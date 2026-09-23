"""基于 ``keyring`` 的系统钥匙串实现。

实现 :class:`serial_log_analyzer.core.ports.KeyringStore`：

- ``service`` 固定为 ``SerialLogAnalyzer``，``account`` 即凭据名；
- 后端不可用（例如 headless Linux 无 SecretService）时 :attr:`available` 返回
  ``False``，上层自动回退环境变量 / 运行时输入；
- ``keyring`` 的异常统一翻译为 :class:`CredentialError`。

详见 ``docs/protocols/credentials.md``。
"""

from __future__ import annotations

__all__ = ["SERVICE_NAME", "KeyringStoreAdapter"]

SERVICE_NAME = "SerialLogAnalyzer"


class KeyringStoreAdapter:
    """``KeyringStore`` 的 keyring 实现。"""

    def __init__(self, service: str = SERVICE_NAME) -> None:
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """系统钥匙串后端是否可用（探测失败不抛异常，只返回 ``False``）。"""

        raise NotImplementedError

    def read(self, credential_id: str) -> str | None:
        """读取凭据；不存在时返回 ``None``。

        异常:
            CredentialError: 钥匙串读取失败。
        """

        raise NotImplementedError

    def save(self, credential_id: str, secret: str) -> None:
        """写入或覆盖凭据。

        异常:
            CredentialError: 凭据名为空、secret 为空或写入失败。
        """

        raise NotImplementedError

    def delete(self, credential_id: str) -> None:
        """删除凭据；不存在时为空操作。

        异常:
            CredentialError: 删除失败。
        """

        raise NotImplementedError
