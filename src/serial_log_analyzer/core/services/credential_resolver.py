"""凭据解析：按优先级从多个来源取得 API Key。

职责：
    实现 ``docs/protocols/credentials.md`` 的解析规则：先看本次会话的运行时输入，
    再按 Profile 声明的 ``kind`` 取首选来源，最后回退到另一个来源；任一来源命中即停止。
    本类不直接访问系统钥匙串或环境变量，两者都由构造函数注入，因此可在纯单元测试中覆盖。

参数：
    keyring: ``core/ports.py`` 的 ``KeyringStore`` 实现。
    environment: ``core/ports.py`` 的 ``EnvironmentReader`` 实现。

异常：
    ``CredentialError``：所有来源均未命中，或来源读取失败且无可用回退。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from serial_log_analyzer.core.errors import CredentialError
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.ports import EnvironmentReader, KeyringStore

__all__ = ["CredentialResolver"]


@dataclass(frozen=True)
class _Source:
    """一个候选来源：中文标签 + 惰性读取函数。"""

    label: str
    read: Callable[[], str | None]


class CredentialResolver:
    """凭据解析器（无状态缓存，运行时输入仅存内存）。

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
            credential_id: 凭据名称，通常来自用户选择或 Profile 的 ``name``。
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
            CredentialError: 所有来源都未命中；错误信息中包含已尝试的来源与失败原因。
        """
        attempts: list[str] = []
        for source in self._sources(credential):
            try:
                value = source.read()
            except CredentialError as exc:
                attempts.append(f"{source.label}（{exc}）")
                continue
            text = (value or "").strip()
            if text:
                return text
            attempts.append(f"{source.label}（未命中）")
        detail = "、".join(attempts) if attempts else "未配置任何来源"
        raise CredentialError(f"未找到可用凭据（{self._describe(credential)}）：已尝试 {detail}")

    def describe_sources(self, credential: CredentialRef) -> str:
        """返回中文来源链描述，例如 ``本次会话输入 → 系统钥匙串（demo）→ 环境变量 DEMO_KEY``。

        参数：
            credential: Profile 中声明的凭据引用。
        """
        labels = [source.label for source in self._sources(credential)]
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

    def _describe(self, credential: CredentialRef) -> str:
        """渲染凭据引用，用于错误信息。"""
        parts = [f"kind={credential.kind.value}"]
        if credential.name:
            parts.append(f"name={credential.name}")
        if credential.env_var:
            parts.append(f"env_var={credential.env_var}")
        return "，".join(parts)

    def _sources(self, credential: CredentialRef) -> list[_Source]:
        """按优先级展开候选来源列表。"""
        sources: list[_Source] = []
        for identifier in self._runtime_ids(credential):
            runtime_id = identifier
            sources.append(
                _Source(
                    label=f"本次会话输入（{runtime_id}）",
                    read=lambda runtime_id=runtime_id: self._runtime.get(runtime_id),
                )
            )
        keyring_source, env_source = self._keyring_source(credential), self._env_source(credential)
        preferred = [keyring_source, env_source]
        if credential.kind is CredentialKind.ENVIRONMENT:
            preferred.reverse()
        sources.extend(source for source in preferred if source is not None)
        return sources

    def _runtime_ids(self, credential: CredentialRef) -> list[str]:
        """运行时输入可能使用的键：``name`` 与 ``env_var``。"""
        candidates = [credential.name, credential.env_var]
        result: list[str] = []
        for item in candidates:
            identifier = (item or "").strip()
            if identifier and identifier not in result:
                result.append(identifier)
        return result

    def _keyring_source(self, credential: CredentialRef) -> _Source | None:
        """构造钥匙串来源；account 名称为空或后端不可用时返回 ``None``。"""
        account = (credential.name or credential.env_var or "").strip()
        if not account:
            return None
        if not self.keyring_available():
            return _Source(
                label=f"系统钥匙串（{account}，不可用）",
                read=lambda: None,
            )
        return _Source(
            label=f"系统钥匙串（{account}）",
            read=lambda account=account: self._keyring.read(account),
        )

    def _env_source(self, credential: CredentialRef) -> _Source | None:
        """构造环境变量来源；未声明环境变量名时返回 ``None``。"""
        env_var = (credential.env_var or "").strip()
        if not env_var:
            return None
        return _Source(
            label=f"环境变量 {env_var}",
            read=lambda env_var=env_var: self._environment.get(env_var),
        )
