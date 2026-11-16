"""SMTP 告警通知领域模型与设置读写契约（纯 Python）。

``SMTP_SETTINGS_KEYS`` 作为单一真源定义在这里，由 ``io/settings/qt_settings_store.py``
引用聚合，避免 ``core`` 反向依赖 ``io``。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.models.anomaly import AnomalySeverity
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef

__all__ = [
    "DEFAULT_SMTP_KEYRING_NAME",
    "SMTP_SETTINGS_KEYS",
    "DeliveryReceipt",
    "SmtpConfig",
    "SmtpSecurity",
    "load_smtp_config",
    "parse_recipients",
    "save_smtp_config",
    "validate_smtp_config",
]

DEFAULT_SMTP_KEYRING_NAME = "smtp-alert"
_DEFAULT_PORT = 587
_DEFAULT_TIMEOUT_SECONDS = 15.0
_MAX_TIMEOUT_SECONDS = 300.0
_RECIPIENT_SPLIT_RE = re.compile(r"[,;\r\n]+")


class SMTP_SETTINGS_KEYS:
    """SMTP 非密钥配置的设置键名（12 项，集中定义于 core 供 io 聚合）。"""

    ENABLED = "alert/smtp_enabled"
    HOST = "alert/smtp_host"
    PORT = "alert/smtp_port"
    SECURITY = "alert/smtp_security"
    USERNAME = "alert/smtp_username"
    SENDER = "alert/smtp_sender"
    RECIPIENTS = "alert/smtp_recipients"
    CREDENTIAL_KIND = "alert/smtp_credential_kind"
    CREDENTIAL_TARGET = "alert/smtp_credential_target"
    MIN_SEVERITY = "alert/smtp_min_severity"
    INCLUDE_EVIDENCE = "alert/smtp_include_evidence"
    TIMEOUT_SECONDS = "alert/smtp_timeout_seconds"


class SmtpSecurity(Enum):
    """SMTP 传输安全模式。"""

    NONE = "none"
    STARTTLS = "starttls"
    SSL = "ssl"


@dataclass(frozen=True)
class SmtpConfig:
    """SMTP 邮件告警非密钥配置（密码通过 ``credential`` 按需解析）。

    参数:
        enabled: 是否启用告警自动发送邮件。
        host: SMTP 服务器主机名或 IP。
        port: SMTP 端口（1–65535，默认 587）。
        security: 传输安全模式（``NONE`` / ``STARTTLS`` / ``SSL``）。
        username: 认证用户名；留空表示免密中继（跳过凭据解析与 ``login()``）。
        sender: 发件人邮箱地址。
        recipients: 收件人邮箱列表。
        credential: 凭据引用（默认系统钥匙串 ``smtp-alert``）。
        timeout_seconds: 单次发送超时秒数。
        min_severity: 触发邮件告警的最低严重度门槛。
        include_evidence_lines: 邮件正文是否附带最多 5 条原始日志原文（默认关闭保护隐私）。
    """

    enabled: bool = False
    host: str = ""
    port: int = _DEFAULT_PORT
    security: SmtpSecurity = SmtpSecurity.STARTTLS
    username: str = ""
    sender: str = ""
    recipients: tuple[str, ...] = ()
    credential: CredentialRef = field(
        default_factory=lambda: CredentialRef(CredentialKind.KEYRING, name=DEFAULT_SMTP_KEYRING_NAME)
    )
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    min_severity: AnomalySeverity = AnomalySeverity.HIGH
    include_evidence_lines: bool = False


@dataclass(frozen=True)
class DeliveryReceipt:
    """单次邮件投递回执（含成功与 ``TC-25`` 失败原因）。"""

    receipt_id: str
    alert_id: str
    cluster_id: str
    recipients: tuple[str, ...]
    subject: str
    created_at: float
    ok: bool
    error: str | None = None


def parse_recipients(raw: object) -> tuple[str, ...]:
    """把逗号/分号/换行分隔的收件人文本或序列规范化为去重元组。"""

    if raw is None:
        return ()
    if isinstance(raw, str):
        tokens = _RECIPIENT_SPLIT_RE.split(raw)
    elif isinstance(raw, (list, tuple, set)):
        tokens = [str(item) for item in raw]
    else:
        raise ConfigError("收件人配置必须是字符串或列表")

    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        addr = token.strip()
        if addr and addr not in seen:
            seen.add(addr)
            result.append(addr)
    return tuple(result)


def validate_smtp_config(config: SmtpConfig, *, require_enabled_fields: bool = True) -> None:
    """校验 SMTP 配置合法性，非法时抛出 :class:`ConfigError`。"""

    if isinstance(config.port, bool) or not isinstance(config.port, int) or not 1 <= config.port <= 65535:
        raise ConfigError(f"SMTP 端口必须是 1-65535 的整数：{config.port}")
    if (
        isinstance(config.timeout_seconds, bool)
        or not isinstance(config.timeout_seconds, (int, float))
        or not math.isfinite(config.timeout_seconds)
        or config.timeout_seconds <= 0
        or config.timeout_seconds > _MAX_TIMEOUT_SECONDS
    ):
        raise ConfigError(f"SMTP 超时必须是 (0, {int(_MAX_TIMEOUT_SECONDS)}] 秒内的数字")

    for label, text in (("SMTP 主机", config.host), ("SMTP 用户名", config.username), ("发件人", config.sender)):
        if any(ch in text for ch in ("\r", "\n", "\x00")):
            raise ConfigError(f"{label}包含非法控制字符")

    for addr in config.recipients:
        if any(ch in addr for ch in ("\r", "\n", "\x00")):
            raise ConfigError("收件人地址包含非法控制字符")

    if not require_enabled_fields:
        return

    host = config.host.strip()
    if not host or any(ch.isspace() for ch in host):
        raise ConfigError("SMTP 主机不能为空且不能包含空白字符")
    sender = config.sender.strip()
    if not sender or "@" not in sender:
        raise ConfigError("发件人邮箱地址不能为空且需包含 @")
    if not config.recipients:
        raise ConfigError("至少需要填写一个收件人邮箱")
    for addr in config.recipients:
        if "@" not in addr or any(ch.isspace() for ch in addr):
            raise ConfigError(f"收件人邮箱格式非法：{addr}")

    if config.username.strip():
        if config.credential.kind is CredentialKind.KEYRING and not config.credential.name.strip():
            raise ConfigError("SMTP 凭据为钥匙串时账号名不能为空")
        if config.credential.kind is CredentialKind.ENVIRONMENT and not config.credential.env_var.strip():
            raise ConfigError("SMTP 凭据为环境变量时变量名不能为空")


def load_smtp_config(settings: Any) -> SmtpConfig:
    """从 :class:`SettingsStore` 读取并解析 :class:`SmtpConfig`。

    兼容 ``QSettings`` IniFormat 把布尔/数字写为字符串的形态。
    """

    enabled = _as_bool(settings.get(SMTP_SETTINGS_KEYS.ENABLED), default=False, key=SMTP_SETTINGS_KEYS.ENABLED)
    host = _as_str(settings.get(SMTP_SETTINGS_KEYS.HOST))
    port = _as_int(settings.get(SMTP_SETTINGS_KEYS.PORT), default=_DEFAULT_PORT, key=SMTP_SETTINGS_KEYS.PORT)
    security = _as_security(settings.get(SMTP_SETTINGS_KEYS.SECURITY))
    username = _as_str(settings.get(SMTP_SETTINGS_KEYS.USERNAME))
    sender = _as_str(settings.get(SMTP_SETTINGS_KEYS.SENDER))
    recipients = parse_recipients(settings.get(SMTP_SETTINGS_KEYS.RECIPIENTS))
    credential = _as_credential(
        settings.get(SMTP_SETTINGS_KEYS.CREDENTIAL_KIND),
        settings.get(SMTP_SETTINGS_KEYS.CREDENTIAL_TARGET),
    )
    min_severity = _as_severity(settings.get(SMTP_SETTINGS_KEYS.MIN_SEVERITY))
    include_evidence = _as_bool(
        settings.get(SMTP_SETTINGS_KEYS.INCLUDE_EVIDENCE),
        default=False,
        key=SMTP_SETTINGS_KEYS.INCLUDE_EVIDENCE,
    )
    timeout_seconds = _as_float(
        settings.get(SMTP_SETTINGS_KEYS.TIMEOUT_SECONDS),
        default=_DEFAULT_TIMEOUT_SECONDS,
        key=SMTP_SETTINGS_KEYS.TIMEOUT_SECONDS,
    )
    config = SmtpConfig(
        enabled=enabled,
        host=host,
        port=port,
        security=security,
        username=username,
        sender=sender,
        recipients=recipients,
        credential=credential,
        timeout_seconds=timeout_seconds,
        min_severity=min_severity,
        include_evidence_lines=include_evidence,
    )
    validate_smtp_config(config, require_enabled_fields=False)
    return config


def save_smtp_config(settings: Any, config: SmtpConfig) -> None:
    """校验并把 :class:`SmtpConfig` 写入 :class:`SettingsStore`（不含密钥）。"""

    validate_smtp_config(config, require_enabled_fields=config.enabled)
    target = (
        config.credential.name.strip() or DEFAULT_SMTP_KEYRING_NAME
        if config.credential.kind is CredentialKind.KEYRING
        else config.credential.env_var.strip()
    )
    settings.set(SMTP_SETTINGS_KEYS.ENABLED, bool(config.enabled))
    settings.set(SMTP_SETTINGS_KEYS.HOST, config.host.strip())
    settings.set(SMTP_SETTINGS_KEYS.PORT, int(config.port))
    settings.set(SMTP_SETTINGS_KEYS.SECURITY, config.security.value)
    settings.set(SMTP_SETTINGS_KEYS.USERNAME, config.username.strip())
    settings.set(SMTP_SETTINGS_KEYS.SENDER, config.sender.strip())
    settings.set(SMTP_SETTINGS_KEYS.RECIPIENTS, ", ".join(config.recipients))
    settings.set(SMTP_SETTINGS_KEYS.CREDENTIAL_KIND, config.credential.kind.value)
    settings.set(SMTP_SETTINGS_KEYS.CREDENTIAL_TARGET, target)
    settings.set(SMTP_SETTINGS_KEYS.MIN_SEVERITY, config.min_severity.name)
    settings.set(SMTP_SETTINGS_KEYS.INCLUDE_EVIDENCE, bool(config.include_evidence_lines))
    settings.set(SMTP_SETTINGS_KEYS.TIMEOUT_SECONDS, float(config.timeout_seconds))


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_bool(value: Any, *, default: bool, key: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ConfigError(f"设置项 {key} 不是合法布尔值：{value}")
    text = str(value).strip().lower()
    if text == "":
        return default
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"设置项 {key} 不是合法布尔值：{value}")


def _as_int(value: Any, *, default: int, key: str) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise ConfigError(f"设置项 {key} 必须是整数：{value}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"设置项 {key} 必须是整数：{value}") from exc


def _as_float(value: Any, *, default: float, key: str) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise ConfigError(f"设置项 {key} 必须是数字：{value}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"设置项 {key} 必须是数字：{value}") from exc


def _as_security(value: Any) -> SmtpSecurity:
    text = _as_str(value).lower()
    if not text:
        return SmtpSecurity.STARTTLS
    try:
        return SmtpSecurity(text)
    except ValueError as exc:
        raise ConfigError(f"未知 SMTP 安全模式：{value}") from exc


def _as_severity(value: Any) -> AnomalySeverity:
    text = _as_str(value).upper()
    if not text:
        return AnomalySeverity.HIGH
    try:
        return AnomalySeverity[text]
    except KeyError as exc:
        raise ConfigError(f"未知最低告警级别：{value}") from exc


def _as_credential(raw_kind: Any, raw_target: Any) -> CredentialRef:
    kind_text = _as_str(raw_kind).lower() or CredentialKind.KEYRING.value
    try:
        kind = CredentialKind(kind_text)
    except ValueError as exc:
        raise ConfigError(f"未知 SMTP 凭据来源：{raw_kind}") from exc
    target = _as_str(raw_target)
    if kind is CredentialKind.KEYRING:
        return CredentialRef(kind=kind, name=target or DEFAULT_SMTP_KEYRING_NAME)
    return CredentialRef(kind=kind, env_var=target)
