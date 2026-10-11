"""系统钥匙串适配：读写 API Key，把 ``keyring`` 的异常统一翻译为 ``CredentialError``。

职责：
    实现 ``core/ports.py`` 的 ``KeyringStore`` 协议。``keyring`` 采用延迟导入，
    这样未安装该可选依赖或后端不可用时，应用仍能启动并回退到环境变量。

参数：
    service: 钥匙串条目的 service 名，按 ``docs/protocols/credentials.md`` 固定为
        ``SerialLogAnalyzer``；account 即凭据的 ``name``。
    backend: 可选后端注入点（需提供 ``get_password`` / ``set_password`` /
        ``delete_password``），测试用假后端替代真实系统钥匙串。

异常：
    ``CredentialError``：依赖缺失、后端不可用或读写失败。
"""

from __future__ import annotations

from typing import Any, Protocol

from serial_log_analyzer.core.errors import CredentialError

__all__ = ["SERVICE_NAME", "KeyringBackend", "KeyringStoreAdapter"]

SERVICE_NAME = "SerialLogAnalyzer"


class KeyringBackend(Protocol):
    """``keyring`` 模块中被使用到的三个函数（测试可注入假实现）。"""

    def get_password(self, service_name: str, username: str) -> str | None:
        """读取密码；不存在时返回 ``None``。"""

    def set_password(self, service_name: str, username: str, password: str) -> None:
        """写入或覆盖密码。"""

    def delete_password(self, service_name: str, username: str) -> None:
        """删除密码；不存在时应抛后端自身异常。"""


def _normalize_credential_id(credential_id: str) -> str:
    """校验并规范化凭据 id（即钥匙串 account）。"""
    identifier = str(credential_id).strip()
    if not identifier:
        raise CredentialError("凭据名称不能为空")
    return identifier


class KeyringStoreAdapter:
    """基于系统钥匙串的凭据存储。

    参数：
        service: 钥匙串 service 名，默认 ``SerialLogAnalyzer``。
        backend: 可选后端实现；为 ``None`` 时使用 ``keyring`` 模块本身。
    """

    def __init__(self, service: str = SERVICE_NAME, *, backend: KeyringBackend | None = None) -> None:
        self._service = service
        self._backend = backend
        self._module: Any | None = None

    @property
    def service(self) -> str:
        """当前使用的钥匙串 service 名。"""
        return self._service

    def _load_module(self) -> Any:
        """延迟导入 ``keyring``；缺失时抛 ``CredentialError``。"""
        if self._module is None:
            try:
                import keyring
            except ImportError as exc:  # pragma: no cover - 依赖声明缺失时的兜底
                raise CredentialError("未安装 keyring 依赖，无法读写系统钥匙串") from exc
            self._module = keyring
        return self._module

    def _require_backend(self) -> KeyringBackend:
        """返回可用后端；不可用时抛 ``CredentialError``。"""
        if self._backend is not None:
            return self._backend
        return self._load_module()

    @property
    def available(self) -> bool:
        """系统钥匙串是否可用（界面据此置灰“保存到系统钥匙串”）。"""
        if self._backend is not None:
            return True
        try:
            backend = self._load_module().get_keyring()
        except CredentialError:
            return False
        except Exception:  # noqa: BLE001 - 后端探测失败等同于不可用
            return False
        name = f"{type(backend).__module__}.{type(backend).__name__}".lower()
        return not ("fail" in name or "null" in name)

    def read(self, credential_id: str) -> str | None:
        """读取凭据内容。

        参数：
            credential_id: 凭据名称（钥匙串 account），通常是 Profile 声明的 ``name``。

        返回：
            凭据内容；未保存时返回 ``None``。

        异常：
            CredentialError: 后端不可用或读取失败。
        """
        identifier = _normalize_credential_id(credential_id)
        backend = self._require_backend()
        try:
            value = backend.get_password(self._service, identifier)
        except Exception as exc:  # noqa: BLE001 - 统一翻译为领域异常
            raise CredentialError(f"读取系统钥匙串失败（{identifier}）：{exc}") from exc
        if value is None:
            return None
        return value

    def save(self, credential_id: str, secret: str) -> None:
        """写入或覆盖凭据。

        参数：
            credential_id: 凭据名称（钥匙串 account）。
            secret: 凭据内容，不能为空。

        异常：
            CredentialError: 内容为空、后端不可用或写入失败。
        """
        identifier = _normalize_credential_id(credential_id)
        if not secret:
            raise CredentialError("凭据内容不能为空")
        backend = self._require_backend()
        try:
            backend.set_password(self._service, identifier, secret)
        except Exception as exc:  # noqa: BLE001 - 统一翻译为领域异常
            raise CredentialError(f"写入系统钥匙串失败（{identifier}）：{exc}") from exc

    def delete(self, credential_id: str) -> bool:
        """删除凭据。

        参数：
            credential_id: 凭据名称（钥匙串 account）。

        返回：
            ``True`` 表示确实删除了一条已存在的凭据，``False`` 表示本来就不存在。

        异常：
            CredentialError: 后端不可用或删除失败。
        """
        identifier = _normalize_credential_id(credential_id)
        backend = self._require_backend()
        try:
            if backend.get_password(self._service, identifier) is None:
                return False
            backend.delete_password(self._service, identifier)
        except Exception as exc:  # noqa: BLE001 - 统一翻译为领域异常
            raise CredentialError(f"删除系统钥匙串条目失败（{identifier}）：{exc}") from exc
        return True

    def describe(self) -> str:
        """返回一句中文描述，用于诊断报告与状态提示。"""
        state = "可用" if self.available else "不可用"
        return f"系统钥匙串（service={self._service}，{state}）"
