"""Provider Profile 加载与校验。

Profile 描述“调用哪一个模型服务”：``base_url``、``model``、凭据引用与流式开关；
Adapter 描述“如何调用这类接口”。两者通过 ``adapter_id`` 关联。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.adapter_loader import load_adapter
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef, ProviderProfile
from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["load_profile", "load_profiles"]

_PROFILE_DIR = "providers/profiles"
_SCHEMA_VERSION = 1
_DEFAULT_TIMEOUT_SECONDS = 120.0
_PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "profile_id",
    "adapter_id",
    "base_url",
    "model",
    "credential",
    "stream",
    "request_timeout_seconds",
    "extra_body",
    "extra_headers",
}
_CREDENTIAL_FIELDS = {"kind", "name", "env_var"}


def load_profile(loader: ResourceLoader, profile_id: str) -> ProviderProfile:
    """按 ID 加载单个 Profile。

    参数:
        loader: 资源加载器。
        profile_id: Profile 标识，需满足 ``[a-z][a-z0-9-]*``。

    返回:
        校验完成的 :class:`ProviderProfile`。

    异常:
        ConfigError: 文件缺失、YAML 非法、未知字段、缺少必填字段、``base_url``
            非法或凭据段不合法。
    """

    if not _PROFILE_ID_RE.match(profile_id):
        raise ConfigError(f"非法 profile_id：{profile_id}")

    path = f"{_PROFILE_DIR}/{profile_id}.yaml"
    try:
        text = loader.read_text(path)
    except ConfigError as exc:
        raise ConfigError(f"未找到 Profile：{profile_id}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Profile YAML 非法：{profile_id}（{path}）") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Profile 顶层必须是对象：{profile_id}（{path}）")

    return _validate_profile(loader, data, path)


def load_profiles(loader: ResourceLoader) -> list[ProviderProfile]:
    """加载全部 Profile，用户目录覆盖同 ID 的内置 Profile。

    返回:
        已校验的 Profile 列表，按 ``profile_id`` 升序排列。
    """

    paths = loader.list_files(_PROFILE_DIR, "*.yaml")
    ids: dict[str, str] = {}
    for path in paths:
        ids.setdefault(Path(path).stem, path)

    profiles = [load_profile(loader, profile_id) for profile_id in ids]
    profiles.sort(key=lambda profile: profile.profile_id)
    return profiles


def _validate_profile(
    loader: ResourceLoader, data: dict[str, Any], source_path: str
) -> ProviderProfile:
    """校验 Profile 声明并构造对象。

    异常:
        ConfigError: 校验失败，或引用的 Adapter 不存在 / 不支持所声明的流式开关。
    """

    unknown = set(data) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ConfigError(f"Profile 未知字段：{sorted(unknown)}（{source_path}）")
    if data.get("schema_version") != _SCHEMA_VERSION:
        raise ConfigError(f"schema_version 必须为 {_SCHEMA_VERSION}（{source_path}）")

    profile_id = _require_str(data, "profile_id", source_path)
    if not _PROFILE_ID_RE.match(profile_id):
        raise ConfigError(f"非法 profile_id：{profile_id}（{source_path}）")
    stem = Path(source_path).stem
    if profile_id != stem:
        raise ConfigError(f"profile_id（{profile_id}）必须与文件名（{stem}）一致")

    adapter_id = _require_str(data, "adapter_id", source_path)
    if not _PROFILE_ID_RE.match(adapter_id):
        raise ConfigError(f"非法 adapter_id：{adapter_id}（{source_path}）")

    base_url = _require_str(data, "base_url", source_path)
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"base_url 必须以 http:// 或 https:// 开头：{base_url}（{source_path}）")
    if base_url.endswith("/"):
        raise ConfigError(f"base_url 不得以 / 结尾：{base_url}（{source_path}）")

    model = _require_str(data, "model", source_path)
    credential = _parse_credential(data.get("credential"), profile_id)

    stream = data.get("stream", True)
    if not isinstance(stream, bool):
        raise ConfigError(f"stream 必须是布尔值（{source_path}）")

    timeout = _parse_timeout(data.get("request_timeout_seconds"), source_path)
    extra_body = _optional_mapping(data.get("extra_body"), "extra_body", source_path)
    extra_headers = _optional_str_mapping(data.get("extra_headers"), "extra_headers", source_path)

    try:
        adapter = load_adapter(loader, adapter_id)
    except ConfigError as exc:
        raise ConfigError(f"Profile {profile_id} 引用的 Adapter 无法加载：{exc}") from exc
    if stream and not adapter.streaming_supported:
        raise ConfigError(f"Adapter {adapter_id} 未声明流式能力，Profile {profile_id} 不能启用 stream")

    return ProviderProfile(
        profile_id=profile_id,
        adapter_id=adapter_id,
        base_url=base_url,
        model=model,
        credential=credential,
        stream=stream,
        request_timeout_seconds=timeout,
        extra_body=extra_body,
        extra_headers=extra_headers,
    )


def _parse_credential(raw: Any, profile_id: str = "") -> CredentialRef:
    """解析 ``credential`` 段。

    支持的两种形态::

        {kind: keyring, name: <account>}
        {kind: environment, env_var: <VAR>}

    只允许声明属于该 ``kind`` 的来源字段，**不做跨来源回落**：``read`` 只读这一个来源。
    ``kind`` 缺省为 ``keyring``；未声明 ``name`` 时用 ``profile_id`` 作为账号名
    （见 ``docs/protocols/credentials.md``）。

    参数:
        raw: ``credential`` 段的原始值；``None`` 时按 ``{kind: keyring}`` 处理。
        profile_id: 所属 Profile 标识，用作缺省账号名。

    异常:
        ConfigError: ``kind`` 未知、字段未知、声明了不属于该 ``kind`` 的字段，或缺少必填字段。
    """

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("credential 必须是对象")
    unknown = set(raw) - _CREDENTIAL_FIELDS
    if unknown:
        raise ConfigError(f"credential 未知字段：{sorted(unknown)}")

    kind_raw = raw.get("kind", CredentialKind.KEYRING.value)
    if not isinstance(kind_raw, str):
        raise ConfigError("credential.kind 必须是字符串")
    try:
        kind = CredentialKind(kind_raw.strip().lower())
    except ValueError as exc:
        raise ConfigError(f"credential.kind 未知：{kind_raw}") from exc

    name = _optional_str(raw.get("name"), "credential.name")
    env_var = _optional_str(raw.get("env_var"), "credential.env_var")

    if kind is CredentialKind.KEYRING:
        if env_var:
            raise ConfigError("credential.kind=keyring 只能声明 name，不能声明 env_var")
        account = name or profile_id
        if not account:
            raise ConfigError("credential.kind=keyring 时必须声明 name（或由 Profile 提供默认 account）")
        return CredentialRef(kind=kind, name=account)
    if name:
        raise ConfigError("credential.kind=environment 只能声明 env_var，不能声明 name")
    if not env_var:
        raise ConfigError("credential.kind=environment 时必须声明 env_var")
    return CredentialRef(kind=kind, env_var=env_var)


def _require_str(data: dict[str, Any], field: str, source_path: str) -> str:
    """取出必填的非空字符串字段。"""
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} 必须是非空字符串（{source_path}）")
    return value.strip()


def _optional_str(value: Any, field: str) -> str:
    """把可选字段规范化为字符串；``None`` 返回空串。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{field} 必须是字符串")
    return value.strip()


def _parse_timeout(value: Any, source_path: str) -> float:
    """校验请求超时：正数秒，缺省 120。"""
    if value is None:
        return _DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"request_timeout_seconds 必须是数字（{source_path}）")
    if value <= 0:
        raise ConfigError(f"request_timeout_seconds 必须大于 0（{source_path}）")
    return float(value)


def _optional_mapping(value: Any, field: str, source_path: str) -> dict[str, Any]:
    """把可选对象字段规范化为映射；``None`` 返回空字典。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{field} 必须是对象（{source_path}）")
    for key in value:
        if not isinstance(key, str):
            raise ConfigError(f"{field} 的键必须是字符串（{source_path}）")
    return value


def _optional_str_mapping(value: Any, field: str, source_path: str) -> dict[str, str]:
    """把可选对象字段规范化为「字符串 → 字符串」映射。"""
    mapping = _optional_mapping(value, field, source_path)
    result: dict[str, str] = {}
    for key, item in mapping.items():
        if not isinstance(item, str):
            raise ConfigError(f"{field}.{key} 必须是字符串（{source_path}）")
        result[key] = item
    return result
