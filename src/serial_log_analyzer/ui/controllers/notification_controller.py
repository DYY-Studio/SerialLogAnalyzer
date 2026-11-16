"""邮件通知控制器：衔接 ``SmtpNotificationService``、设置重载与界面回执状态。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.anomaly import AlertEvent, AnomalyCluster
from serial_log_analyzer.core.models.notification import (
    DeliveryReceipt,
    SmtpConfig,
    load_smtp_config,
)
from serial_log_analyzer.core.ports import SettingsStore
from serial_log_analyzer.core.services.notification import SmtpNotificationService

__all__ = ["NotificationController"]


class NotificationController(QObject):
    """SMTP 告警通知控制器。

    参数:
        service: SMTP 邮件告警编排服务。
        settings: 设置存储（用于在设置保存后热重载 SMTP 配置）。
        parent: 可选父对象。

    信号:
        receipts_changed(list): 投递回执列表更新时发出最新只读回执列表（最新在前）。
        delivery_failed(object): 后台告警邮件投递失败时发出失败的 :class:`DeliveryReceipt`。
        test_email_finished(object): 测试邮件（含同步校验/凭据失败或异步结果）结束时发出回执。
        error_occurred(str): 重载设置失败等配置错误通知。
    """

    receipts_changed = Signal(list)
    delivery_failed = Signal(object)
    test_email_finished = Signal(object)
    error_occurred = Signal(str)

    def __init__(
        self,
        service: SmtpNotificationService,
        settings: SettingsStore,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._settings = settings
        self._service.set_receipt_handler(self._on_receipt_recorded)

    def notify_alert(
        self, alert: AlertEvent, cluster: AnomalyCluster | None = None
    ) -> None:
        """响应异常告警事件并在满足门槛与冷却条件时异步发信。

        参数:
            alert: 异常服务产生的本地告警事件。
            cluster: 可选关联异常簇快照（预留上下文）。
        """

        _ = cluster
        self._service.handle_alert(alert)

    def send_test_email(self, config: SmtpConfig) -> None:
        """按界面表单配置发送测试邮件（绕过启用开关与冷却限制）。"""

        self._service.send_test_email(config, on_finished=self.test_email_finished.emit)

    def reload_config(self) -> SmtpConfig | None:
        """从设置存储重新加载 SMTP 配置并即时应用到通知服务。"""

        try:
            config = load_smtp_config(self._settings)
        except AppError as exc:
            self.error_occurred.emit(str(exc))
            return None
        self._service.set_config(config)
        return config

    def set_pipeline(self, pipeline: LogPipeline | None) -> None:
        """切换日志 Preset 后同步更新关联的日志流水线。"""

        self._service.set_pipeline(pipeline)

    def receipts(self) -> list[DeliveryReceipt]:
        """返回最近投递回执列表（最新在前）。"""

        return self._service.receipts()

    def _on_receipt_recorded(self, receipt: DeliveryReceipt) -> None:
        self.receipts_changed.emit(self._service.receipts())
        if not receipt.ok and receipt.alert_id != "TEST":
            self.delivery_failed.emit(receipt)
