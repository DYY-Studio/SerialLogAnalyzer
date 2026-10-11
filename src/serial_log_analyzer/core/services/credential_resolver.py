"""凭据解析：按 ``kind`` 读取 Profile 声明的那一个来源。

职责：
    实现 ``docs/protocols/credentials.md`` 的解析规则：只读取 Profile 中 ``kind`` 声明的来源，
    **不做跨来源回落**；取不到非空值时抛出 ``CredentialError``，并在消息中说明已尝试的来源与
    替代办法。本类不直接访问系统钥匙串或环境变量，两者都由构造函数注入，因此可在纯单元测试中
    覆盖。

参数：
    keyring: ``core/ports.py`` 的 ``KeyringStore`` 实现。
    environment: ``core/ports.py`` 的 ``EnvironmentReader`` 实现。

异常：
    ``CredentialError``：声明的来源未命中或读取失败。
"""

from __future__ import annotations

from serial_log_analyzer.core.errors import CredentialError
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.ports import EnvironmentReader, KeyringStore

__all__ = ["CredentialResolver"]

_HINTS = {
    CredentialKind.KEYRING: "可把该 Profile 的 credential.kind 改为 environment，或把密钥存入系统钥匙串",
    CredentialKind.ENVIRONMENT: "请设置该环境变量，或把该 Profile 的 credential.kind 改为 keyring",
}


class CredentialResolver:
    """凭据解析器（每次按声明读取，不缓存内容）。

    参数：
        keyring: 系统钥匙串适配器。
        environment: 环境变量读取器。
    """

    def __init__(self, keyring: KeyringStore, environment: EnvironmentReader) -> None:
        self._keyring = keyring
        self._environment = environment

    def resolve(self, credential: CredentialRef) -> str:
        """解析出可用的凭据内容。

        参数:
            credential: Profile 中声明的凭据引用。

        返回:
            凭据内容（已去除首尾空白）。

        异常:
            CredentialError: ``kind`` 声明的来源未命中或读取失败；错误信息中包含已尝试的
                来源与失败原因。
        """

        label = self._source_label(credential)
        attempts: list[str] = []
        try:
            value = self._read_declared(credential)
        except CredentialError as exc:
            attempts.append(f"{label}（{exc}）")
        else:
            text = (value or "").strip()
            if text:
                return text
            attempts.append(f"{label}（未命中）")

        raise CredentialError(self._failure(credential, attempts))

    def describe_sources(self, credential: CredentialRef) -> str:
        """返回中文来源描述，例如 ``系统钥匙串（demo）``。

        参数:
            credential: Profile 中声明的凭据引用。
        """

        return self._source_label(credential)

    def keyring_available(self) -> bool:
        """系统钥匙串是否可用；探测失败按不可用处理。"""
        try:
            return bool(self._keyring.available)
        except Exception:  # noqa: BLE001 - 探测失败等同于不可用
            return False

    def _source_label(self, credential: CredentialRef) -> str:
        """``kind`` 声明的来源在消息中的名称。"""
        if credential.kind is CredentialKind.KEYRING:
            suffix = "" if self.keyring_available() else "，不可用"
            return f"系统钥匙串（{credential.name or '未指定'}{suffix}）"
        return f"环境变量 {credential.env_var or '（未指定）'}"

    def _read_declared(self, credential: CredentialRef) -> str | None:
        """读取 ``kind`` 声明的来源；来源不可用时抛出 ``CredentialError``。"""
        if credential.kind is CredentialKind.KEYRING:
            if not self.keyring_available():
                raise CredentialError("系统钥匙串不可用")
            return self._keyring.read(credential.name)
        return self._environment.get(credential.env_var)

    def _failure(self, credential: CredentialRef, attempts: list[str]) -> str:
        """构造未命中错误：已尝试的来源 + 可操作的替代办法。"""
        detail = "、".join(attempts) if attempts else "未配置任何来源"
        return f"未找到可用凭据（{self._describe(credential)}）：已尝试 {detail}；{_HINTS[credential.kind]}"

    def _describe(self, credential: CredentialRef) -> str:
        """渲染凭据引用，用于错误信息。"""
        parts = [f"kind={credential.kind.value}"]
        if credential.name:
            parts.append(f"name={credential.name}")
        if credential.env_var:
            parts.append(f"env_var={credential.env_var}")
        return "，".join(parts)
