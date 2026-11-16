"""异常面板、异常控制器与异常聚类分析触发测试（使用 pytest-qt，离屏运行）。"""

from __future__ import annotations

import json

from PySide6.QtWidgets import QPushButton

from serial_log_analyzer.core.llm.adapter_loader import load_adapter
from serial_log_analyzer.core.llm.profile_loader import load_profile
from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.logs.preset_loader import load_preset
from serial_log_analyzer.core.models.analysis import AnalysisState
from serial_log_analyzer.core.models.anomaly import (
    AlertEvent,
    AnomalyCluster,
    AnomalyRule,
    AnomalySeverity,
    ClusterStatus,
)
from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.core.prompts.loader import PromptLibrary
from serial_log_analyzer.core.services.analysis import AnalysisContextBuilder, AnalysisService
from serial_log_analyzer.core.services.anomaly import AnomalyService
from serial_log_analyzer.io.paths import repo_root
from serial_log_analyzer.io.resources import CompositeResourceLoader
from serial_log_analyzer.ui.controllers.analysis_controller import AnalysisController
from serial_log_analyzer.ui.controllers.anomaly_controller import AnomalyController
from serial_log_analyzer.ui.widgets.anomaly_panel import AnomalyPanel


class _StubToken:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _CapturingTransport:
    def __init__(self, *, finish_immediately: bool = True) -> None:
        self.requests: list[object] = []
        self._finish = finish_immediately

    def send(self, request, on_chunk, on_done, on_error):
        self.requests.append(request)
        token = _StubToken()
        if self._finish:
            on_chunk(json.dumps({"choices": [{"message": {"content": "根因定位结论"}}]}).encode("utf-8"))
            on_done()
        return token


class _StubCredentials:
    def resolve(self, _credential) -> str:
        return "sk-test-token"


def _row_button(panel: AnomalyPanel, row: int, text: str) -> QPushButton:
    cell = panel.table.cellWidget(row, 6)
    assert cell is not None
    button = next(btn for btn in cell.findChildren(QPushButton) if btn.text() == text)
    return button


def test_anomaly_controller_and_panel_lifecycle(qtbot) -> None:
    """增量摄入、告警横幅、状态过滤、行内确认/解决与证据定位全流程。"""

    pipeline = LogPipeline(LogParser(load_preset(CompositeResourceLoader.from_environment(repo_root()), "hi3861-default")))
    service = AnomalyService(
        [
            AnomalyRule(
                rule_id="mem-oom",
                category="内存故障",
                severity=AnomalySeverity.CRITICAL,
                keywords=("malloc failed",),
                min_level=LogLevel.ERROR,
                immediate_alert=True,
                cooldown_seconds=60.0,
            ),
            AnomalyRule(
                rule_id="uart-drop",
                category="串口溢流",
                severity=AnomalySeverity.MEDIUM,
                keywords=("rx overflow",),
                min_level=LogLevel.WARN,
                min_occurrences=1,
            ),
        ]
    )
    controller = AnomalyController(service)
    panel = AnomalyPanel()
    qtbot.addWidget(panel)

    controller.clusters_changed.connect(panel.set_clusters)
    controller.alert_triggered.connect(panel.push_alert)
    panel.acknowledge_requested.connect(controller.acknowledge)
    panel.resolve_requested.connect(controller.resolve)

    located: list[int] = []
    analyzed: list[AnomalyCluster] = []
    alerts: list[AlertEvent] = []
    errors: list[str] = []
    panel.locate_requested.connect(located.append)
    panel.analyze_requested.connect(analyzed.append)
    controller.alert_triggered.connect(alerts.append)
    controller.error_occurred.connect(errors.append)

    assert panel.table.isVisible() is False
    assert panel.view_stack.count() == 2

    u1 = pipeline.feed("[E] [mem] malloc failed size=64", 100.0)
    u2 = pipeline.feed("[W] [uart] rx overflow cnt=3", 101.0)
    controller.ingest_update(u1)
    controller.ingest_update(u2)

    assert len(alerts) == 2
    assert len(panel.clusters()) == 2
    assert panel.alert_banner.isHidden() is False
    assert "rx overflow" in panel._banner_text.text() or "串口溢流" in panel._banner_text.text()
    assert panel.table.rowCount() == 2

    # 双击第 0 行与点定位按钮都应发出最新证据序号
    panel._on_row_double_clicked(0, 3)
    _row_button(panel, 0, "定位").click()
    assert located == [1, 1]

    # 点 LLM 按钮发出对应异常簇对象
    _row_button(panel, 1, "LLM").click()
    assert [c.rule_id for c in analyzed] == ["mem-oom"]

    # 确认第 0 行后，状态切为已确认并禁用「确认」按钮；筛选「已确认」只剩 1 行
    _row_button(panel, 0, "确认").click()
    assert panel.clusters()[0].status is ClusterStatus.ACKNOWLEDGED
    assert _row_button(panel, 0, "确认").isEnabled() is False
    panel.set_status_filter(ClusterStatus.ACKNOWLEDGED)
    assert panel.table.rowCount() == 1

    # 解决后切回全部，再清空全部状态
    _row_button(panel, 0, "解决").click()
    panel.set_status_filter(None)
    assert any(item.status is ClusterStatus.RESOLVED for item in panel.clusters())

    # 未知 cluster_id 走 error_occurred，不静默忽略
    controller.acknowledge("C-9999")
    assert len(errors) == 1

    panel.banner_dismiss_btn.click()
    assert panel.alert_banner.isHidden() is True

    controller.reset()
    assert panel.table.rowCount() == 0
    assert panel.summary_label.text() == "0 簇 · 0 活动"


def test_analysis_controller_analyze_cluster_uses_aggregate_goal_and_fails_loudly(qtbot) -> None:
    """一键分析异常簇应命中 aggregate-anomalies 模板，流式占线或证据缺失时报错。"""

    resources = CompositeResourceLoader.from_environment(repo_root())
    preset = load_preset(resources, "hi3861-default")
    pipeline = LogPipeline(LogParser(preset))
    pipeline.feed("[I] [wifi] sta init", 10.0)
    pipeline.feed("[E] [wifi] link down reason=4", 11.0)

    profile = load_profile(resources, "deepseek")
    non_stream_profile = type(profile)(
        **{
            **profile.__dict__,
            "stream": False,
        }
    )
    adapter = load_adapter(resources, non_stream_profile.adapter_id)
    transport = _CapturingTransport(finish_immediately=True)
    service = AnalysisService(
        adapter,
        transport,
        PromptLibrary(resources),
        _StubCredentials(),
        profile=non_stream_profile,
    )
    controller = AnalysisController(service, AnalysisContextBuilder(pipeline))
    errors: list[str] = []
    states: list[AnalysisState] = []
    controller.error_occurred.connect(errors.append)
    controller.state_changed.connect(states.append)

    cluster = AnomalyCluster(
        cluster_id="C-0001",
        rule_id="comm-link-failed",
        category="通信链路断开",
        severity=AnomalySeverity.HIGH,
        normalized_message="link down reason=<NUM>",
        modules=("wifi",),
        first_seen=11.0,
        last_seen=11.0,
        occurrence_count=1,
        evidence_sequences=(1,),
        status=ClusterStatus.ACTIVE,
    )

    assert controller.analyze_cluster(cluster) is True
    assert len(transport.requests) == 1
    body_text = json.dumps(transport.requests[0].body, ensure_ascii=False)
    assert "link down reason=4" in body_text
    assert "sta init" in body_text
    assert "异常聚合" in body_text or "根因" in body_text
    assert states[-1] is AnalysisState.DONE

    # 无证据序号时显式失败并通知 error_occurred
    empty_cluster = AnomalyCluster(
        cluster_id="C-0002",
        rule_id="comm-link-failed",
        category="通信链路断开",
        severity=AnomalySeverity.HIGH,
        normalized_message="link down reason=<NUM>",
        modules=("wifi",),
        first_seen=11.0,
        last_seen=11.0,
        occurrence_count=1,
        evidence_sequences=(),
        status=ClusterStatus.ACTIVE,
    )
    assert controller.analyze_cluster(empty_cluster) is False
    assert errors and "没有可用于分析的日志证据" in errors[-1]


def test_anomaly_panel_receipts_page_failure_banner_and_sanitization(qtbot) -> None:
    """邮件回执分页、失败红点角标、TC-25 非阻塞横幅脱敏与跳转查看。"""

    from PySide6.QtCore import QSettings

    from serial_log_analyzer.core.errors import NotificationError
    from serial_log_analyzer.core.models.anomaly import AlertEvent
    from serial_log_analyzer.core.models.notification import SmtpConfig, SmtpSecurity
    from serial_log_analyzer.core.services.notification import SmtpNotificationService
    from serial_log_analyzer.io.settings.qt_settings_store import QtSettingsStore
    from serial_log_analyzer.ui.controllers.notification_controller import NotificationController

    class _ModeNotifier:
        def __init__(self) -> None:
            self.fail_next = True

        def send(self, config, password, subject, body, on_done, on_error):
            if self.fail_next:
                on_error(NotificationError(f"SMTP AUTH 失败: {password} invalid"))
                return
            on_done()

    class _SecretCredentials:
        def resolve(self, _ref) -> str:
            return "TOP_SECRET_PASSWORD"

    notifier = _ModeNotifier()
    cfg = SmtpConfig(
        enabled=True,
        host="smtp.example.com",
        port=587,
        security=SmtpSecurity.STARTTLS,
        username="ops@example.com",
        sender="ops@example.com",
        recipients=("oncall@example.com",),
        min_severity=AnomalySeverity.HIGH,
    )
    service = SmtpNotificationService(
        notifier,
        _SecretCredentials(),
        config=cfg,
        cooldown_seconds=0.0,
    )
    store = QtSettingsStore(settings=QSettings())
    notif_ctrl = NotificationController(service, store)

    panel = AnomalyPanel()
    qtbot.addWidget(panel)
    notif_ctrl.receipts_changed.connect(panel.set_receipts)
    notif_ctrl.delivery_failed.connect(panel.push_failed_receipt)

    settings_opened: list[bool] = []
    panel.smtp_settings_requested.connect(lambda: settings_opened.append(True))
    panel.smtp_settings_btn.click()
    assert settings_opened == [True]

    # 触发一次失败告警通知（TC-25）：顶部横幅显示脱敏原因，且绝不含明文密码
    alert1 = AlertEvent(
        alert_id="A-0001",
        cluster_id="C-0001",
        rule_id="mem-oom",
        severity=AnomalySeverity.CRITICAL,
        category="内存故障",
        title="malloc failed",
        reason="60 秒内命中 1 次",
        occurrence_count=1,
        triggered_at=1700000000.0,
        evidence_sequences=(1,),
    )
    notif_ctrl.notify_alert(alert1)
    assert panel.receipts_tab_btn.text() == "邮件回执 (1)"
    assert panel.receipt_alert_banner.isHidden() is False
    banner_text = panel._receipt_banner_text.text()
    assert "SMTP AUTH 失败" in banner_text
    assert "TOP_SECRET_PASSWORD" not in banner_text

    # 再发送一次成功通知
    notifier.fail_next = False
    alert2 = AlertEvent(
        alert_id="A-0002",
        cluster_id="C-0002",
        rule_id="comm-link-failed",
        severity=AnomalySeverity.HIGH,
        category="通信异常",
        title="link down",
        reason="60 秒内命中 1 次",
        occurrence_count=1,
        triggered_at=1700000005.0,
        evidence_sequences=(2,),
    )
    notif_ctrl.notify_alert(alert2)

    # 一键查看回执：切到 Page 1，收起横幅，表格包含最新在前的 2 条记录且无明文密码
    panel.banner_view_receipts_btn.click()
    assert panel.view_stack.currentIndex() == 1
    assert panel.receipt_alert_banner.isHidden() is True
    assert panel.receipts_table.rowCount() == 2
    assert panel.receipts_table.item(1, 4).text().find("TOP_SECRET_PASSWORD") == -1
    assert "邮件告警投递失败" not in panel.receipts_table.item(0, 4).text()
    assert panel.receipts_table.item(0, 4).text() == "投递成功"
