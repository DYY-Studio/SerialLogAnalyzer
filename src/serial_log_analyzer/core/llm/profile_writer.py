"""Provider Profile 序列化：把内存中的 Profile 写回 YAML 声明。

与 :mod:`serial_log_analyzer.core.llm.profile_loader` 互为逆操作，键顺序固定，
便于用户在版本控制中查看差异。只做序列化与基本合法性校验，不落盘。
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.models.provider import CredentialKind, ProviderProfile

__all__ = ["dump_profile"]

_SCHEMA_VERSION = 1
_PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def dump_profile(profile: ProviderProfile) -> str:
    """把 Profile 序列化为 YAML 文本。

    参数:
        profile: 待序列化的 Profile。

    返回:
        UTF-8 YAML 文本（结尾带换行，中文不转义）。

    异常:
        ConfigError: ``profile_id`` / ``adapter_id`` 不满足命名规则，或 ``base_url`` 非法。
    """

    for field, value in (("profile_id", profile.profile_id), ("adapter_id", profile.adapter_id)):
        if not _PROFILE_ID_RE.match(value):
            raise ConfigError(f"非法 {field}：{value}")
    if not profile.base_url.startswith(("http://", "https://")) or profile.base_url.endswith("/"):
        raise ConfigError(f"非法 base_url：{profile.base_url}")
    if not profile.model.strip():
        raise ConfigError("model 不能为空")
    if profile.request_timeout_seconds <= 0:
        raise ConfigError("request_timeout_seconds 必须大于 0")

    data: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "profile_id": profile.profile_id,
        "adapter_id": profile.adapter_id,
        "base_url": profile.base_url,
        "model": profile.model,
        "stream": profile.stream,
        "request_timeout_seconds": _timeout_value(profile.request_timeout_seconds),
        "credential": _credential_value(profile),
        "extra_body": dict(profile.extra_body),
        "extra_headers": dict(profile.extra_headers),
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _timeout_value(seconds: float) -> float | int:
    """整数秒写成整数，避免出现 ``120.0`` 这种噪声差异。"""
    return int(seconds) if float(seconds).is_integer() else float(seconds)


def _credential_value(profile: ProviderProfile) -> dict[str, str]:
    """把凭据引用序列化为 ``credential`` 段：``kind`` 只写一个来源字段。"""

    credential = profile.credential
    if credential.kind is CredentialKind.KEYRING:
        if credential.env_var:
            raise ConfigError(f"Profile {profile.profile_id} 的 keyring 凭据不能声明 env_var")
        if not credential.name:
            raise ConfigError(f"Profile {profile.profile_id} 的 keyring 凭据缺少 name")
        return {"kind": credential.kind.value, "name": credential.name}
    if credential.name:
        raise ConfigError(f"Profile {profile.profile_id} 的 environment 凭据不能声明 name")
    if not credential.env_var:
        raise ConfigError(f"Profile {profile.profile_id} 的 environment 凭据缺少 env_var")
    return {"kind": credential.kind.value, "env_var": credential.env_var}
