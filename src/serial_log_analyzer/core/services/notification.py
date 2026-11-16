"""SMTP 告警通知服务（纯 Python，无 Qt / smtplib 依赖）。

职责：
- 消费 :class:`AlertEvent`，按启用状态、严重度门槛、单簇冷却与待发队列上限决定是否发信；
- 在调用方线程（Qt 主线程）通过 :class:`CredentialProvider` 解析凭据（免密中继跳过），
  绝不在错误或回执中回显密钥；
- 默认仅发送脱敏摘要与证据序号；仅当 ``include_evidence_lines=True`` 时才从
  ``LogPipeline`` 抽取最多 5 条渲染后的日志文本；
- 将同步校验/凭据失败与异步发送结果统一记录为 :class:`DeliveryReceipt`（覆盖 ``TC-25``）。
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from datetime import datetime

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.anomaly import AlertEvent
from serial_log_analyzer.core.models.notification import (
    DeliveryReceipt,
    SmtpConfig,
    validate_smtp_config,
)
from serial_log_analyzer.core.ports import CredentialProvider, EmailNotifier

__all__ = ["SmtpNotificationService"]

_MAX_EVIDENCE_LINES = 5
_DEFAULT_MAX_RECEIPTS = 50
_DEFAULT_MAX_PENDING = 10
_DEFAULT_COOLDOWN_SECONDS = 60.0


class SmtpNotificationService:
    """SMTP 邮件告警编排服务。

    参数:
        notifier: 异步邮件发送端口（由 ``io`` 提供）。
        credentials: 凭据解析器（与 LLM 共用，不跨来源回落）。
        config: 初始 SMTP 配置；缺省为停用状态。
        pipeline: 可选日志流水线（仅在 ``include_evidence_lines=True`` 时读取最多 5 条）。
        on_receipt: 每次产出投递回执（成功或失败）时的通知回调。
        cooldown_seconds: 同聚合组邮件告警最小冷却间隔（秒）。
        max_pending: 允许同时排队的未完成发送任务上限。
        max_receipts: 内存中保留的最近回执条数上限。
        clock: 可注入时钟函数（便于单测控制冷却时间）。
    """

    def __init__(
        self,
        notifier: EmailNotifier,
        credentials: CredentialProvider,
        *,
        config: SmtpConfig | None = None,
        pipeline: LogPipeline | None = None,
        on_receipt: Callable[[DeliveryReceipt], None] | None = None,
        cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS,
        max_pending: int = _DEFAULT_MAX_PENDING,
        max_receipts: int = _DEFAULT_MAX_RECEIPTS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._notifier = notifier
        self._credentials = credentials
        self._config = config or SmtpConfig()
        self._pipeline = pipeline
        self._on_receipt = on_receipt
        self._cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._max_pending = max(1, int(max_pending))
        self._receipts: deque[DeliveryReceipt] = deque(maxlen=max(1, int(max_receipts)))
        self._clock = clock or time.time
        self._last_sent_by_cluster: dict[str, float] = {}
        self._in_flight = 0
        self._next_receipt_num = 1

    @property
    def config(self) -> SmtpConfig:
        """当前生效的 SMTP 配置快照。"""

        return self._config

    def set_config(self, config: SmtpConfig) -> None:
        """更新 SMTP 配置（设置保存后即时生效）。"""

        self._config = config

    def set_pipeline(self, pipeline: LogPipeline | None) -> None:
        """同步替换关联日志流水线（切换日志 Preset 时调用）。"""

        self._pipeline = pipeline

    def set_receipt_handler(self, handler: Callable[[DeliveryReceipt], None] | None) -> None:
        """安装或替换回执通知回调。"""

        self._on_receipt = handler

    def receipts(self) -> list[DeliveryReceipt]:
        """返回最近投递回执列表（按时间倒序，最新在前）。"""

        return list(self._receipts)

    def clear_receipts(self) -> None:
        """清空历史投递回执缓存。"""

        self._receipts.clear()

    def handle_alert(self, alert: AlertEvent) -> DeliveryReceipt | None:
        """按策略处理一条本地告警；不满足发送条件或被冷却抑制时返回 ``None``。

        若触发发送但同步校验/凭据失败或待发队列已满，立即返回失败回执。
        """

        cfg = self._config
        if not cfg.enabled or alert.severity < cfg.min_severity:
            return None

        now = self._clock()
        if self._is_in_cooldown(alert.cluster_id, now):
            return None

        subject = f"[SerialLogAnalyzer][{alert.severity.name}] {alert.category} ({alert.cluster_id})"
        if self._in_flight >= self._max_pending:
            return self._record_receipt(
                alert_id=alert.alert_id,
                cluster_id=alert.cluster_id,
                recipients=cfg.recipients,
                subject=subject,
                created_at=now,
                ok=False,
                error="待发邮件队列已满，已跳过本次告警通知",
            )

        self._record_cooldown_stamp(alert.cluster_id, now)
        body = self._build_alert_body(alert, cfg)
        return self._dispatch(
            cfg,
            alert_id=alert.alert_id,
            cluster_id=alert.cluster_id,
            subject=subject,
            body=body,
            now=now,
        )

    def send_test_email(
        self,
        config: SmtpConfig,
        *,
        on_finished: Callable[[DeliveryReceipt], None] | None = None,
    ) -> DeliveryReceipt | None:
        """发送测试邮件（显式绕过 ``enabled`` 与冷却限制，供设置弹窗保存前验证）。"""

        now = self._clock()
        subject = "[SerialLogAnalyzer] SMTP 告警通道测试邮件"
        body = (
            "这是一封来自 SerialLogAnalyzer 的测试邮件。\n\n"
            f"发送时间：{datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"发件配置：{config.host}:{config.port} ({config.security.value})\n"
            f"最低告警级别：{config.min_severity.name}\n"
            f"附带原始日志：{'是（最多 5 条）' if config.include_evidence_lines else '否（仅摘要）'}\n"
        )
        return self._dispatch(
            config,
            alert_id="TEST",
            cluster_id="-",
            subject=subject,
            body=body,
            now=now,
            on_finished=on_finished,
        )

    # ------------------------------------------------------------------
    # 内部调度、隐私正文构造与脱敏回执
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        config: SmtpConfig,
        *,
        alert_id: str,
        cluster_id: str,
        subject: str,
        body: str,
        now: float,
        on_finished: Callable[[DeliveryReceipt], None] | None = None,
    ) -> DeliveryReceipt | None:
        try:
            validate_smtp_config(config, require_enabled_fields=True)
            password = (
                self._credentials.resolve(config.credential)
                if config.username.strip()
                else ""
            )
        except AppError as exc:
            receipt = self._record_receipt(
                alert_id=alert_id,
                cluster_id=cluster_id,
                recipients=config.recipients,
                subject=subject,
                created_at=now,
                ok=False,
                error=str(exc),
            )
            if on_finished is not None:
                on_finished(receipt)
            return receipt

        self._in_flight += 1
        settled = False

        def _finish(ok: bool, error: str | None = None) -> None:
            nonlocal settled
            if settled:
                return
            settled = True
            self._in_flight = max(0, self._in_flight - 1)
            receipt = self._record_receipt(
                alert_id=alert_id,
                cluster_id=cluster_id,
                recipients=config.recipients,
                subject=subject,
                created_at=self._clock(),
                ok=ok,
                error=error,
            )
            if on_finished is not None:
                on_finished(receipt)

        def _on_done() -> None:
            _finish(True)

        def _on_error(exc: AppError) -> None:
            _finish(False, _sanitize_error(exc, password))

        try:
            self._notifier.send(config, password, subject, body, _on_done, _on_error)
        except AppError as exc:
            _finish(False, _sanitize_error(exc, password))
        return None

    def _build_alert_body(self, alert: AlertEvent, config: SmtpConfig) -> str:
        seq_text = ", ".join(f"#{seq}" for seq in alert.evidence_sequences) or "（无）"
        lines = [
            "SerialLogAnalyzer 异常告警通知",
            "",
            f"告警级别 : {alert.severity.name}",
            f"异常分类 : {alert.category}",
            f"触发规则 : {alert.rule_id}",
            f"聚合组   : {alert.cluster_id}",
            f"异常摘要 : {alert.title}",
            f"触发原因 : {alert.reason}",
            f"累计命中 : {alert.occurrence_count} 次",
            f"触发时间 : {datetime.fromtimestamp(alert.triggered_at).strftime('%Y-%m-%d %H:%M:%S')}",
            f"证据序号 : {seq_text}",
        ]
        if not config.include_evidence_lines:
            lines.append("")
            lines.append("（按隐私设置默认隐藏原始日志正文；如需附带，请在设置中勾选「附带原始日志」。）")
            return "\n".join(lines) + "\n"

        evidence_lines = self._collect_evidence_lines(alert.evidence_sequences)
        lines.append("")
        if evidence_lines:
            lines.append(f"代表性原始日志（最多 {_MAX_EVIDENCE_LINES} 条）：")
            lines.extend(evidence_lines)
        else:
            lines.append("（关联原始日志已从内存缓冲淘汰，无法附带正文。）")
        return "\n".join(lines) + "\n"

    def _collect_evidence_lines(self, sequences: tuple[int, ...]) -> list[str]:
        if self._pipeline is None or not sequences:
            return []
        wanted = set(sequences[-_MAX_EVIDENCE_LINES:])
        matched = [entry for entry in self._pipeline.entries() if entry.sequence in wanted]
        if not matched:
            return []
        rendered = self._pipeline.render(matched)
        return [
            f"#{entry.sequence} {text}"
            for entry, text in zip(matched, rendered, strict=True)
        ]

    def _is_in_cooldown(self, cluster_id: str, now: float) -> bool:
        if self._cooldown_seconds <= 0:
            return False
        last = self._last_sent_by_cluster.get(cluster_id)
        return last is not None and (now - last) < self._cooldown_seconds

    def _record_cooldown_stamp(self, cluster_id: str, now: float) -> None:
        self._last_sent_by_cluster[cluster_id] = now
        if len(self._last_sent_by_cluster) > 500:
            cutoff = now - self._cooldown_seconds
            expired = [key for key, ts in self._last_sent_by_cluster.items() if ts <= cutoff]
            for key in expired:
                self._last_sent_by_cluster.pop(key, None)

    def _record_receipt(
        self,
        *,
        alert_id: str,
        cluster_id: str,
        recipients: tuple[str, ...],
        subject: str,
        created_at: float,
        ok: bool,
        error: str | None = None,
    ) -> DeliveryReceipt:
        receipt = DeliveryReceipt(
            receipt_id=f"R-{self._next_receipt_num:04d}",
            alert_id=alert_id,
            cluster_id=cluster_id,
            recipients=recipients,
            subject=subject,
            created_at=created_at,
            ok=ok,
            error=error,
        )
        self._next_receipt_num += 1
        self._receipts.appendleft(receipt)
        if self._on_receipt is not None:
            self._on_receipt(receipt)
        return receipt


def _sanitize_error(exc: Exception, password: str) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    if password:
        text = text.replace(password, "***")
    return text
