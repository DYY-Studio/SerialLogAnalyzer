"""凭据解析：运行时输入优先，其次只读 Profile 声明的那个来源。

职责：
    实现 ``docs/protocols/credentials.md`` 的解析规则：先看本次会话的运行时输入，
    未命中时只读取 Profile 中 ``kind`` 声明的来源，**不做跨来源回落**；两者都没取到
    非空值时抛出 ``CredentialError``，并在消息中说明已尝试的来源与替代办法。
    本类不直接访问系统钥匙串或环境变量，两者都由构造函数注入，因此可在纯单元测试中覆盖。

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
    CredentialKind.KEYRING: "可把该 Profile 的 credential.kind 改为 environment 或 runtime，或把密钥存入系统钥匙串",
    CredentialKind.ENVIRONMENT: "请设置该环境变量，或把该 Profile 的 credential.kind 改为 keyring 或 runtime",
    CredentialKind.RUNTIME: "请在界面输入本次会话密钥",
}


class CredentialResolver:
    """凭据解析器（不缓存持久来源，运行时输入仅存内存）。

    参数：
        keyring: 系统钥匙串适配器。
        environment: 环境变量读取器。
    """

    def __init__(self, keyring: KeyringStore, environment: EnvironmentReader) -> None:
        self._keyring = keyring
        self._environment = environment
        self._runtime: dict[str, str] = {}

    def set_runtime_secret(self, credential_id: str, secret: str | None) -> None:
        """登记或清除“仅本次会话有效”的凭据。

        运行时输入只保存在内存中，不会写入系统钥匙串。

        参数：
            credential_id: 凭据名称，取 ``CredentialRef.name``（缺省为 ``profile_id``）。
            secret: 凭据内容；``None`` 或空串表示清除。
        """
        identifier = str(credential_id).strip()
        if not identifier:
            return
        text = (secret or "").strip()
        if text:
            self._runtime[identifier] = text
        else:
            self._runtime.pop(identifier, None)

    def resolve(self, credential: CredentialRef) -> str:
        """解析出可用的凭据内容。

        参数：
            credential: Profile 中声明的凭据引用。

        返回：
            凭据内容（已去除首尾空白）。

        异常：
            CredentialError: 运行时输入与 ``kind`` 声明的来源都未命中；错误信息中包含
                已尝试的来源与失败原因。
        """
        attempts: list[str] = []
        identifier = self._runtime_id(credential)
        if identifier:
            secret = self._runtime.get(identifier)
            if secret:
                return secret
            attempts.append(f"本次会话输入（{identifier}，未命中）")

        if credential.kind is not CredentialKind.RUNTIME:
            label = self._source_label(credential)
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
        """返回中文来源描述，例如 ``本次会话输入（demo） → 系统钥匙串（demo）``。

        参数：
            credential: Profile 中声明的凭据引用。
        """
        labels: list[str] = []
        identifier = self._runtime_id(credential)
        if identifier:
            labels.append(f"本次会话输入（{identifier}）")
        if credential.kind is not CredentialKind.RUNTIME:
            labels.append(self._source_label(credential))
        return " → ".join(labels) if labels else "未配置任何来源"

    def keyring_available(self) -> bool:
        """系统钥匙串是否可用；探测失败按不可用处理。"""
        try:
            return bool(self._keyring.available)
        except Exception:  # noqa: BLE001 - 探测失败等同于不可用
            return False

    def has_runtime_secret(self, credential_id: str) -> bool:
        """本次会话是否已登记某个凭据（不读取内容本身）。"""
        return str(credential_id).strip() in self._runtime

    def _runtime_id(self, credential: CredentialRef) -> str:
        """运行时输入的键：``name``（加载器保证 keyring / runtime 有值），否则 ``env_var``。"""
        return (credential.name or credential.env_var).strip()

    def _source_label(self, credential: CredentialRef) -> str:
        """``kind`` 声明的来源在消息中的名称。"""
        if credential.kind is CredentialKind.KEYRING:
            suffix = "" if self.keyring_available() else "，不可用"
            return f"系统钥匙串（{credential.name}{suffix}）"
        return f"环境变量 {credential.env_var}"

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
