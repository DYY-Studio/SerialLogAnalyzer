"""通过资源端口加载 Provider Profile，不接触凭据明文。"""

from __future__ import annotations

from typing import Any

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm import config as c
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef, ProviderProfile
from serial_log_analyzer.core.ports import ResourceLoader


def load_profile(loader: ResourceLoader, profile_id: str) -> ProviderProfile:
    """加载指定 Profile；配置非法时抛出包含来源的 ConfigError。"""
    path = f"providers/profiles/{c.identifier(profile_id)}.yaml"
    try:
        raw = c.mapping(
            c.document(loader.read_text(path)),
            {
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
            },
            {"schema_version", "profile_id", "adapter_id", "base_url", "model", "credential"},
        )
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            raise ConfigError("Profile schema_version 必须是 1")
        if c.identifier(raw["profile_id"]) != profile_id:
            raise ConfigError("Profile ID 与文件名不符")
        body, headers = raw.get("extra_body", {}), raw.get("extra_headers", {})
        if not isinstance(body, dict) or not isinstance(headers, dict):
            raise ConfigError("额外字段必须为映射")
        for key, value in headers.items():
            c.text(key)
            c.text(value)
        return ProviderProfile(
            profile_id=profile_id,
            adapter_id=c.identifier(raw["adapter_id"]),
            base_url=c.base_url(raw["base_url"]),
            model=c.text(raw["model"]),
            credential=_parse_credential(raw["credential"]),
            stream=c.boolean(raw.get("stream", True)),
            request_timeout_seconds=c.timeout(raw.get("request_timeout_seconds", 120)),
            extra_body=body,
            extra_headers=headers,
        )
    except ConfigError as exc:
        raise ConfigError(f"Profile 配置非法：{path}；{exc}") from exc


def load_profiles(loader: ResourceLoader) -> list[ProviderProfile]:
    """加载全部 Profile；覆盖由资源接口处理，配置非法时抛出 ConfigError。"""
    return [
        load_profile(loader, path.rsplit("/", 1)[-1].removesuffix(".yaml"))
        for path in sorted(set(loader.list_files("providers/profiles", "*.yaml")))
    ]


def _parse_credential(raw: Any) -> CredentialRef:
    value = c.mapping(raw, {"kind", "name", "env_var"}, {"kind"})
    try:
        kind = CredentialKind(value["kind"])
    except (ValueError, TypeError) as exc:
        raise ConfigError("未知凭据来源") from exc
    if kind is CredentialKind.KEYRING:
        c.text(value.get("name"))
    if kind is CredentialKind.ENVIRONMENT:
        c.text(value.get("env_var"))
    for field in value.keys() - {"kind"}:
        c.text(value[field])
    return CredentialRef(kind, value.get("name", ""), value.get("env_var", ""))
