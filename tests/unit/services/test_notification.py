"""SMTP 通知服务与配置读写单元测试（不启动 Qt、不触碰网络或系统钥匙串）。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import ConfigError, NotificationError
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.anomaly import AlertEvent, AnomalySeverity
from serial_log_analyzer.core.models.notification import (
    DeliveryReceipt,
    SmtpConfig,
    SmtpSecurity,
    load_smtp_config,
    save_smtp_config,
)
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver
from serial_log_analyzer.core.services.notification import SmtpNotificationService


class FakeSettings:
    """模拟 QSettings 字符串化行为的内存键值存储。"""

    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self.values = dict(initial or {})

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def set(self, key: str, value: object) -> None:
        if isinstance(value, bool):
            self.values[key] = "true" if value else "false"
        elif isinstance(value, (int, float)):
            self.values[key] = str(value)
        else:
            self.values[key] = value


class FakeKeyring:
    def __init__(self, values: dict[str, str] | None = None, *, available: bool = True) -> None:
        self.values = dict(values or {})
        self.available = available
        self.calls: list[str] = []

    def read(self, credential_id: str) -> str | None:
        self.calls.append(credential_id)
        return self.values.get(credential_id)

    def save(self, credential_id: str, secret: str) -> None:
        self.values[credential_id] = secret

    def delete(self, credential_id: str) -> None:
        self.values.pop(credential_id, None)


class FakeEnv:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})
        self.calls: list[str] = []

    def get(self, name: str) -> str | None:
        self.calls.append(name)
        return self.values.get(name)


class FakeEmailNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[SmtpConfig, str, str, str, object, object]] = []

    def send(self, config, password, subject, body, on_done, on_error) -> None:
        self.sent.append((config, password, subject, body, on_done, on_error))

    def finish_last(self) -> None:
        self.sent[-1][4]()

    def fail_last(self, error: Exception) -> None:
        self.sent[-1][5](error)


def _alert(
    alert_id: str = "A-0001",
    cluster_id: str = "C-0001",
    severity: AnomalySeverity = AnomalySeverity.CRITICAL,
    sequences: tuple[int, ...] = (0, 1),
) -> AlertEvent:
    return AlertEvent(
        alert_id=alert_id,
        cluster_id=cluster_id,
        rule_id="memory-alloc-failed",
        severity=severity,
        category="内存分配失败",
        title="[内存分配失败] malloc failed size=<NUM>",
        reason="规则 memory-alloc-failed 立即触发",
        occurrence_count=len(sequences),
        triggered_at=1_700_000_010.0,
        evidence_sequences=sequences,
    )


def _config(**overrides) -> SmtpConfig:
    base = SmtpConfig(
        enabled=True,
        host="smtp.example.com",
        port=587,
        security=SmtpSecurity.STARTTLS,
        username="alert@example.com",
        sender="alert@example.com",
        recipients=("ops@example.com",),
        credential=CredentialRef(CredentialKind.KEYRING, name="smtp-alert"),
        timeout_seconds=15.0,
        min_severity=AnomalySeverity.HIGH,
        include_evidence_lines=False,
    )
    for k, v in overrides.items():
        base = type(base)(**{**base.__dict__, k: v})
    return base


def test_settings_roundtrip_handles_ini_strings_and_validation() -> None:
    store = FakeSettings()
    assert load_smtp_config(store).enabled is False

    # 未启用时允许保存草稿
    draft = SmtpConfig(enabled=False, host="draft.local", port=2525, security=SmtpSecurity.NONE)
    save_smtp_config(store, draft)
    loaded_draft = load_smtp_config(store)
    assert loaded_draft.enabled is False and loaded_draft.port == 2525

    # 启用时校验必填字段
    with pytest.raises(ConfigError):
        save_smtp_config(store, SmtpConfig(enabled=True, host=""))

    cfg = _config(recipients=("a@example.com", "b@example.com"), include_evidence_lines=True)
    save_smtp_config(store, cfg)
    loaded = load_smtp_config(store)
    assert loaded == cfg


def test_privacy_default_hides_raw_logs_and_opt_in_caps_five_lines(parser) -> None:
    pipeline = LogPipeline(parser)
    for idx in range(7):
        pipeline.feed(f"[E] [memory] malloc failed raw_secret_line={idx}", 100.0 + idx)

    notifier = FakeEmailNotifier()
    resolver = CredentialResolver(FakeKeyring({"smtp-alert": "pw-123"}), FakeEnv())
    svc = SmtpNotificationService(
        notifier,
        resolver,
        config=_config(include_evidence_lines=False),
        pipeline=pipeline,
        clock=lambda: 200.0,
    )

    alert = _alert(sequences=(0, 1, 2, 3, 4, 5, 6))
    svc.handle_alert(alert)
    notifier.finish_last()
    _, _, subject, body_default, _, _ = notifier.sent[-1]
    assert "[CRITICAL]" in subject and "C-0001" in subject
    assert "raw_secret_line=" not in body_default
    assert "#0, #1" in body_default

    # 开启附带原始日志后，最多附带 5 条渲染原文
    svc.set_config(_config(include_evidence_lines=True))
    svc.handle_alert(_alert(alert_id="A-0002", cluster_id="C-0002", sequences=(0, 1, 2, 3, 4, 5, 6)))
    notifier.finish_last()
    _, _, _, body_with_lines, _, _ = notifier.sent[-1]
    assert "raw_secret_line=6" in body_with_lines
    assert "raw_secret_line=0" not in body_with_lines
    assert "raw_secret_line=1" not in body_with_lines


def test_passwordless_relay_skips_credential_resolution() -> None:
    notifier = FakeEmailNotifier()
    keyring = FakeKeyring()
    env = FakeEnv()
    resolver = CredentialResolver(keyring, env)
    svc = SmtpNotificationService(
        notifier,
        resolver,
        config=_config(username="", credential=CredentialRef(CredentialKind.KEYRING, name="smtp-alert")),
        clock=lambda: 100.0,
    )

    svc.handle_alert(_alert())
    assert len(notifier.sent) == 1
    assert notifier.sent[0][1] == ""
    assert keyring.calls == [] and env.calls == []


def test_credential_error_does_not_fallback_and_records_tc25_receipt() -> None:
    notifier = FakeEmailNotifier()
    # 即使环境变量存在，kind=keyring 也不得跨来源回落。
    resolver = CredentialResolver(
        FakeKeyring({}), FakeEnv({"SLA_SMTP_PASSWORD": "env-only-secret"})
    )
    receipts: list[DeliveryReceipt] = []
    svc = SmtpNotificationService(
        notifier,
        resolver,
        config=_config(),
        on_receipt=receipts.append,
        clock=lambda: 100.0,
    )

    result = svc.handle_alert(_alert())

    assert result is not None and result.ok is False
    assert "系统钥匙串" in (result.error or "")
    assert "env-only-secret" not in (result.error or "")
    assert notifier.sent == []
    assert receipts == [result]


def test_async_failure_records_sanitized_tc25_receipt_and_respects_cooldown() -> None:
    notifier = FakeEmailNotifier()
    resolver = CredentialResolver(FakeKeyring({"smtp-alert": "top-secret-pw"}), FakeEnv())
    now = [100.0]
    receipts: list[DeliveryReceipt] = []
    svc = SmtpNotificationService(
        notifier,
        resolver,
        config=_config(),
        on_receipt=receipts.append,
        cooldown_seconds=60.0,
        clock=lambda: now[0],
    )

    # 低级别或关闭开关不发信
    assert svc.handle_alert(_alert(severity=AnomalySeverity.MEDIUM)) is None

    # 触发异步发送并模拟服务端错误（即使底层消息意外带密码也必须脱敏）
    assert svc.handle_alert(_alert()) is None
    notifier.fail_last(NotificationError("auth rejected for top-secret-pw"))
    assert len(receipts) == 1
    assert receipts[0].ok is False
    assert "top-secret-pw" not in (receipts[0].error or "")
    assert "***" in (receipts[0].error or "")

    # 冷却期内抑制同一簇
    now[0] = 120.0
    assert svc.handle_alert(_alert(alert_id="A-0002")) is None
    assert len(notifier.sent) == 1

    # 过冷却期后可再次发送
    now[0] = 165.0
    svc.handle_alert(_alert(alert_id="A-0003"))
    notifier.finish_last()
    assert svc.receipts()[0].ok is True and len(svc.receipts()) == 2


def test_send_test_email_bypasses_enabled_and_cooldown() -> None:
    notifier = FakeEmailNotifier()
    resolver = CredentialResolver(FakeKeyring({"smtp-alert": "pw"}), FakeEnv())
    svc = SmtpNotificationService(
        notifier,
        resolver,
        config=SmtpConfig(enabled=False),
        cooldown_seconds=60.0,
        clock=lambda: 100.0,
    )
    finished: list[DeliveryReceipt] = []
    test_cfg = _config(enabled=False)

    svc.send_test_email(test_cfg, on_finished=finished.append)
    notifier.finish_last()

    assert len(finished) == 1 and finished[0].ok is True and finished[0].alert_id == "TEST"
    # 连续两次测试邮件不受冷却抑制
    svc.send_test_email(test_cfg, on_finished=finished.append)
    notifier.finish_last()
    assert len(finished) == 2
