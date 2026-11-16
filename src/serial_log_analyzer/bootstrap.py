"""组合根（Composition Root）：唯一组装依赖的地方。

职责：
1. 创建 ``QApplication`` 并设置应用元数据；
2. 创建唯一的 ``QNetworkAccessManager``；
3. 构造 ``io`` 适配器（串口 / 网络 / 设置 / 钥匙串 / 资源）；
4. 加载声明式资源（Preset / Adapter / Profile / Prompt）；
5. 构造 ``core`` 服务（``LogPipeline`` / ``DeviceSession`` / 分析上下文构造器）；
6. 构造 ``ui``（控制器 / 窗口 / 组件）并显式注入依赖；
7. 显示主窗口并进入事件循环。

全部依赖通过构造函数显式传入，不引入 DI 框架。``ui`` 层仍在实现中：
:func:`build_window` 是唯一尚未接通的一步，在此之前 :func:`build_application` 会直接失败。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import QApplication

from serial_log_analyzer.core.anomalies.rule_loader import load_rule_set
from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.llm.adapter_loader import load_adapter
from serial_log_analyzer.core.llm.profile_loader import load_profile, load_profiles
from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline, PipelineUpdate
from serial_log_analyzer.core.logs.preset_loader import load_preset, load_presets
from serial_log_analyzer.core.models.analysis import AnalysisState
from serial_log_analyzer.core.models.anomaly import (
    AlertEvent,
    AnomalyCluster,
    AnomalySeverity,
    ClusterStatus,
)
from serial_log_analyzer.core.models.device import DeviceConnectionState
from serial_log_analyzer.core.models.notification import DeliveryReceipt, load_smtp_config
from serial_log_analyzer.core.prompts.loader import PromptLibrary
from serial_log_analyzer.core.services.analysis import AnalysisContextBuilder, AnalysisService
from serial_log_analyzer.core.services.anomaly import AnomalyService
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver
from serial_log_analyzer.core.services.device_session import DeviceSession
from serial_log_analyzer.core.services.notification import SmtpNotificationService
from serial_log_analyzer.core.services.report import build_diagnostic_report
from serial_log_analyzer.diagnostics.app_logging import (
    configure_logging,
    current_log_file,
    get_logger,
    log_file_path,
    read_tail,
)
from serial_log_analyzer.io.credentials.keyring_store import KeyringStoreAdapter
from serial_log_analyzer.io.environment import DotEnvEnvironmentReader
from serial_log_analyzer.io.llm.qt_http_transport import QtHttpTransport
from serial_log_analyzer.io.notifications.qt_smtp_sender import QtSmtpNotifier
from serial_log_analyzer.io.paths import default_export_dir, repo_root, user_config_dir
from serial_log_analyzer.io.resources import CompositeResourceLoader
from serial_log_analyzer.io.serial.qt_serial_transport import QtSerialTransport
from serial_log_analyzer.io.settings.qt_settings_store import (
    SETTINGS_KEYS,
    QtSettingsStore,
    parse_bool,
)
from serial_log_analyzer.io.storage.report_file_store import ReportFileStore, ReportFormat
from serial_log_analyzer.ui.controllers.analysis_controller import AnalysisController
from serial_log_analyzer.ui.controllers.anomaly_controller import AnomalyController
from serial_log_analyzer.ui.controllers.device_controller import DeviceController, coalesce_updates
from serial_log_analyzer.ui.controllers.main_controller import MainController
from serial_log_analyzer.ui.controllers.notification_controller import NotificationController
from serial_log_analyzer.ui.main_window import MainWindow
from serial_log_analyzer.ui.models.log_table_model import LogTableModel
from serial_log_analyzer.ui.theme import ThemeManager
from serial_log_analyzer.ui.widgets.analysis_panel import AnalysisPanel
from serial_log_analyzer.ui.widgets.anomaly_panel import AnomalyPanel
from serial_log_analyzer.ui.widgets.app_log_panel import AppLogPanel
from serial_log_analyzer.ui.widgets.chart_panel import ChartPanel
from serial_log_analyzer.ui.widgets.command_panel import CommandPanel
from serial_log_analyzer.ui.widgets.log_view import LogView
from serial_log_analyzer.ui.widgets.serial_toolbar import SerialToolBar

__all__ = [
    "ApplicationContext",
    "build_application",
    "export_logs",
    "export_report",
    "import_logs",
    "main",
]

_APP_NAME = "SerialLogAnalyzer"
_APP_VERSION = "0.1.0"
_DEFAULT_CAPACITY = 100000


@dataclass
class ApplicationContext:
    """组装结果：Qt 应用对象与各层依赖，供窗口组装与退出清理使用。

    参数:
        app: ``QApplication``。
        resources: 资源加载器。
        settings: 设置存储。
        keyring: 钥匙串适配器。
        credentials: 凭据解析器。
        manager: 唯一的 ``QNetworkAccessManager``。
        http_transport: LLM HTTP 传输。
        serial_transport: 串口传输。
        preset: 当前日志 Preset。
        pipeline: 日志流水线。
        session: 设备会话（回调由 ``ui`` 控制器安装）。
        profile: 当前 LLM Profile。
        adapter: 当前 Adapter。
        prompts: Prompt 模板库。
        context_builder: 分析上下文构造器。
        theme_manager: 界面主题管理器。
        window: 主窗口，由 :func:`build_window` 填充。
        anomaly_service: 异常规则检测与聚合服务。
        report_file_store: 诊断报告默认文件写出器。
        analysis_service: 当前窗口绑定的 LLM 分析服务（用于报告快照）。
        anomaly_controller: 当前窗口绑定的异常控制器。
        smtp_notifier: 异步 SMTP 邮件发送器。
        notification_service: SMTP 告警通知编排服务。
        notification_controller: 当前窗口绑定的邮件通知控制器。
    """

    app: Any
    resources: Any
    settings: Any
    keyring: Any
    credentials: Any
    manager: Any
    http_transport: Any
    serial_transport: Any
    preset: Any
    pipeline: Any
    session: Any
    profile: Any
    adapter: Any
    prompts: Any
    context_builder: Any
    theme_manager: Any = None
    window: Any = None
    anomaly_service: Any = None
    report_file_store: Any = None
    analysis_service: Any = None
    anomaly_controller: Any = None
    smtp_notifier: Any = None
    notification_service: Any = None
    notification_controller: Any = None


def build_application(argv: list[str] | None = None) -> ApplicationContext:
    """组装并返回可运行的应用对象。

    参数:
        argv: 命令行参数；``None`` 时使用 ``sys.argv``。

    返回:
        持有全部对象引用的 :class:`ApplicationContext`。

    异常:
        ConfigError: 内置资源缺失或声明文件非法。
        NotImplementedError: ``ui`` 层尚未实现（见 :func:`build_window`）。
    """

    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(_APP_NAME)
    app.setOrganizationName(_APP_NAME)
    app.setApplicationVersion(_APP_VERSION)
    _use_system_tls_backend()
    theme_manager = ThemeManager(app)
    theme_manager.apply()

    settings = QtSettingsStore()
    configure_logging(
        level=str(settings.get(SETTINGS_KEYS.LOG_LEVEL, "INFO")),
        log_file=log_file_path(),
        reset=True,  # 每次启动一份干净的日志
    )

    root = repo_root()
    resources = CompositeResourceLoader.from_environment(root)
    keyring = KeyringStoreAdapter()
    credentials = CredentialResolver(
        keyring, DotEnvEnvironmentReader((root or user_config_dir()) / ".env")
    )

    preset = _current_preset(resources, settings)
    pipeline = LogPipeline(LogParser(preset), capacity=_capacity(settings))
    serial_transport = QtSerialTransport()
    session = DeviceSession(serial_transport, pipeline)

    profile = _current_profile(resources, settings)
    anomaly_service = AnomalyService(load_rule_set(resources, "default"))
    report_file_store = ReportFileStore(default_export_dir())
    smtp_notifier = QtSmtpNotifier()
    notification_service = SmtpNotificationService(
        smtp_notifier,
        credentials,
        config=load_smtp_config(settings),
        pipeline=pipeline,
    )
    manager = QNetworkAccessManager()
    context = ApplicationContext(
        app=app,
        resources=resources,
        settings=settings,
        keyring=keyring,
        credentials=credentials,
        manager=manager,
        http_transport=QtHttpTransport(manager),
        serial_transport=serial_transport,
        preset=preset,
        pipeline=pipeline,
        session=session,
        profile=profile,
        adapter=load_adapter(resources, profile.adapter_id),
        prompts=PromptLibrary(resources),
        context_builder=AnalysisContextBuilder(pipeline),
        theme_manager=theme_manager,
        anomaly_service=anomaly_service,
        report_file_store=report_file_store,
        smtp_notifier=smtp_notifier,
        notification_service=notification_service,
    )
    # 让「视图 → 应用日志」一开始就有内容，也便于 issue 报告看清本次运行的配置。
    get_logger("bootstrap").info(
        "应用启动：preset=%s profile=%s 日志=%s",
        preset.preset_id,
        profile.profile_id,
        current_log_file(),
    )
    return context


def _use_system_tls_backend() -> None:
    """Windows 上固定用系统 TLS（Schannel），避免两套 OpenSSL 混用导致进程崩溃。

    进程里迟早会加载 Python 的 ``ssl``（``keyring`` 经 ``jaraco.context`` 间接导入），
    它自带一份 ``libssl``/``libcrypto``；而 Qt 的 OpenSSL 插件默认绑定系统里的同名 DLL，
    两者混用后**任何 HTTPS 请求都会以访问冲突（0xC0000005）直接结束进程**。
    改用系统 Schannel 后 Qt 不再加载 OpenSSL，与 Python 的 ``ssl`` 互不干扰。

    异常:
        ConfigError: Windows 上 Schannel 后端不可用（Qt tls 插件不完整）；此时继续运行
            只会在第一次 HTTPS 请求时崩溃，因此直接失败并说明原因。
    """

    if sys.platform != "win32":
        return
    from PySide6.QtNetwork import QSslSocket

    if not QSslSocket.setActiveBackend("schannel"):
        raise ConfigError("无法启用系统 TLS 后端（Schannel），请检查 Qt 的 tls 插件是否完整")


def build_window(context: ApplicationContext) -> MainWindow:
    """组装 ``ui`` 层（控制器 / 窗口 / 组件）并接通信号。

    参数:
        context: :func:`build_application` 的组装结果。

    返回:
        已接线的 :class:`MainWindow`。
    """

    settings = context.settings
    table_model = LogTableModel()
    log_view = LogView(table_model)
    panel = AnalysisPanel()
    panel.set_goals(context.prompts.goals())
    toolbar = SerialToolBar()
    command_panel = CommandPanel()
    command_panel.set_commands(context.preset.commands)
    app_log_panel = AppLogPanel(
        read_lines=lambda: read_tail(200),
        log_path=str(current_log_file() or log_file_path()),
    )
    anomaly_panel = AnomalyPanel()
    chart_panel = ChartPanel(preset_fields=tuple(context.preset.line.fields))

    if context.anomaly_service is None:
        context.anomaly_service = AnomalyService(load_rule_set(context.resources, "default"))
    if context.report_file_store is None:
        context.report_file_store = ReportFileStore(default_export_dir())
    if context.smtp_notifier is None:
        context.smtp_notifier = QtSmtpNotifier()
    if context.notification_service is None:
        context.notification_service = SmtpNotificationService(
            context.smtp_notifier,
            context.credentials,
            config=load_smtp_config(settings),
            pipeline=context.pipeline,
        )
    else:
        context.notification_service.set_pipeline(context.pipeline)

    device = DeviceController(context.session)
    anomaly = AnomalyController(context.anomaly_service)
    context.anomaly_controller = anomaly
    notification = NotificationController(context.notification_service, settings)
    context.notification_controller = notification
    service = _analysis_service(context)
    context.analysis_service = service
    analysis = AnalysisController(service, context.context_builder)
    service.set_history_rounds(_history_rounds(settings))
    panel.set_board_prompt(context.preset.display_name, context.preset.prompt)
    include_board = parse_bool(settings.get(SETTINGS_KEYS.INCLUDE_BOARD_PROMPT, True), True)
    panel.set_include_board_prompt(include_board)
    analysis.set_include_board_prompt(include_board)
    main = MainController(
        device,
        analysis,
        settings,
        on_shutdown=lambda: context.smtp_notifier.shutdown(wait_ms=1000),
    )
    window = MainWindow(
        log_view,
        panel,
        toolbar,
        command_panel,
        app_log_panel,
        anomaly_panel,
        chart_panel,
        on_close=lambda: _shutdown(main, window, settings),
    )
    panel.set_profiles(load_profiles(context.resources), context.profile.profile_id)

    toolbar.refresh_requested.connect(device.refresh_ports)
    toolbar.connect_requested.connect(device.connect)
    toolbar.disconnect_requested.connect(device.disconnect)
    command_panel.command_submitted.connect(device.send_command)
    device.ports_refreshed.connect(toolbar.set_ports)

    def _on_connection(state: object, message: str) -> None:
        connected = state is DeviceConnectionState.CONNECTED
        toolbar.set_connected(connected)
        window.set_connection_status(connected, toolbar.active_endpoint_label() if connected else "")
        window.show_status(message)

    device.connection_changed.connect(_on_connection)
    device.log_update.connect(log_view.append_update)
    device.log_update.connect(anomaly.ingest_update)
    device.log_update.connect(chart_panel.append_update)
    device.error_occurred.connect(window.show_status)
    device.command_reply.connect(command_panel.append_reply)

    def _on_clusters_changed(clusters: list[AnomalyCluster]) -> None:
        anomaly_panel.set_clusters(clusters)
        active = [item for item in clusters if item.status is ClusterStatus.ACTIVE]
        severe = any(item.severity >= AnomalySeverity.HIGH for item in active)
        window.set_alert_count(len(active), severe=severe)

    def _on_alert_triggered(alert: AlertEvent) -> None:
        anomaly_panel.push_alert(alert)
        window.show_status(f"新告警 [{alert.severity.name}] {alert.title}：{alert.reason}")

    def _locate_sequence(sequence: int) -> None:
        if window.log_view.scroll_to_sequence(sequence):
            window.show_status(f"已定位到日志序号 #{sequence}")
            return
        if table_model.row_for_sequence(sequence) is not None:
            window.show_status(
                f"日志序号 #{sequence} 当前被过滤条件隐藏，请调整过滤条件后重试"
            )
            return
        window.show_status(f"日志序号 #{sequence} 已超出日志缓冲容量并被淘汰，无法定位")

    def _analyze_cluster(cluster: AnomalyCluster) -> None:
        if analysis.analyze_cluster(cluster):
            window.focus_analysis_dock()

    def _on_delivery_failed(receipt: DeliveryReceipt) -> None:
        anomaly_panel.push_failed_receipt(receipt)
        window.show_status(f"邮件告警投递失败：{receipt.error or '未知错误'}")

    anomaly.clusters_changed.connect(_on_clusters_changed)
    anomaly.alert_triggered.connect(_on_alert_triggered)
    anomaly.alert_triggered.connect(notification.notify_alert)
    anomaly.error_occurred.connect(window.show_status)
    notification.receipts_changed.connect(anomaly_panel.set_receipts)
    notification.delivery_failed.connect(_on_delivery_failed)
    notification.error_occurred.connect(window.show_status)
    anomaly_panel.locate_requested.connect(_locate_sequence)
    anomaly_panel.analyze_requested.connect(_analyze_cluster)
    anomaly_panel.acknowledge_requested.connect(anomaly.acknowledge)
    anomaly_panel.resolve_requested.connect(anomaly.resolve)
    anomaly_panel.smtp_settings_requested.connect(
        lambda: _open_settings(window, context, service, initial_tab=1)
    )
    _on_clusters_changed(anomaly.clusters())
    anomaly_panel.set_receipts(notification.receipts())

    def _on_command_timeout(command: str) -> None:
        command_panel.append_timeout(command)
        window.show_status(f"命令超时未响应：{command}")

    device.command_timed_out.connect(_on_command_timeout)
    table_model.row_count_changed.connect(window.set_log_count)

    theme_manager = context.theme_manager
    if theme_manager is not None:
        table_model.set_tokens(theme_manager.tokens)
        window.set_theme_tokens(theme_manager.tokens)
        theme_manager.theme_changed.connect(table_model.set_tokens)
        theme_manager.theme_changed.connect(window.set_theme_tokens)
    window.set_preset_name(context.preset.preset_id)

    log_view.selection_changed.connect(analysis.selected_sequences)
    log_view.autoscroll_toggled.connect(
        lambda enabled: settings.set(SETTINGS_KEYS.AUTOSCROLL, bool(enabled))
    )

    window.clear_requested.connect(device.clear_logs)
    window.clear_requested.connect(log_view.clear)
    window.clear_requested.connect(anomaly.reset)
    window.clear_requested.connect(anomaly_panel.clear_alert_banner)
    window.clear_requested.connect(chart_panel.clear)
    window.export_requested.connect(lambda: _export_logs(window, context))
    window.export_report_requested.connect(lambda: _export_report(window, context))
    panel.export_report_requested.connect(lambda: _export_report(window, context))
    window.import_requested.connect(lambda: _import_logs(window, context))
    toolbar.serial_settings_requested.connect(lambda: _open_serial_settings(window, toolbar))
    toolbar.error_occurred.connect(window.show_status)
    panel.profile_changed.connect(lambda profile_id: _switch_profile(window, context, service, profile_id))

    panel.analyze_requested.connect(lambda payload: analysis.start_analysis(*payload))
    panel.follow_up_requested.connect(analysis.follow_up)
    panel.cancel_requested.connect(analysis.cancel)
    panel.reset_requested.connect(analysis.reset)
    panel.reset_requested.connect(window.clear_usage_summary)
    panel.board_prompt_toggled.connect(analysis.set_include_board_prompt)
    panel.board_prompt_toggled.connect(
        lambda enabled: settings.set(SETTINGS_KEYS.INCLUDE_BOARD_PROMPT, bool(enabled))
    )
    analysis.result_updated.connect(panel.set_result)
    analysis.state_changed.connect(panel.set_state)
    analysis.usage_updated.connect(window.set_usage_summary)
    analysis.usage_cleared.connect(window.clear_usage_summary)
    analysis.error_occurred.connect(window.show_status)

    window.settings_requested.connect(lambda: _open_settings(window, context, service))
    window.provider_requested.connect(lambda: _open_provider(window, context, service))
    window.preset_requested.connect(lambda: _choose_preset(window, context))

    _restore_view(window, toolbar, log_view, settings)
    device.refresh_ports()
    window.show_status("就绪")
    return window


def _analysis_service(context: ApplicationContext) -> AnalysisService:
    """按组装结果构造分析服务（``build_window`` 与测试共用的唯一入口）。"""

    return AnalysisService(
        context.adapter,
        context.http_transport,
        context.prompts,
        context.credentials,
        profile=context.profile,
        board_prompt=context.preset.prompt,
    )


def _open_settings(
    window: MainWindow,
    context: ApplicationContext,
    service: AnalysisService,
    *,
    initial_tab: int = 0,
) -> None:
    """打开设置对话框；临时接线 SMTP 测试回调并在保存后刷新配置与流水线。"""

    from PySide6.QtWidgets import QDialog

    from serial_log_analyzer.ui.dialogs.settings_dialog import SettingsDialog

    notif = context.notification_controller
    dialog = SettingsDialog(
        context.settings,
        window,
        keyring=context.keyring,
        on_test_smtp=(notif.send_test_email if notif is not None else None),
        initial_tab=initial_tab,
    )
    if notif is not None:
        notif.test_email_finished.connect(dialog.show_smtp_test_result)
    try:
        accepted = dialog.exec() == int(QDialog.DialogCode.Accepted)
    finally:
        if notif is not None:
            with suppress(RuntimeError, TypeError):
                notif.test_email_finished.disconnect(dialog.show_smtp_test_result)
    if accepted:
        _apply_settings(window, context, service)
        if notif is not None:
            notif.reload_config()


def _open_serial_settings(window: MainWindow, toolbar: SerialToolBar) -> None:
    """打开串口高级设置并把结果写回工具栏。"""

    from serial_log_analyzer.ui.dialogs.serial_settings_dialog import SerialSettingsDialog

    dialog = SerialSettingsDialog(window, toolbar.serial_values())
    if dialog.exec():
        toolbar.apply_serial_settings(dialog.values())


def _apply_settings(
    window: MainWindow, context: ApplicationContext, service: AnalysisService
) -> None:
    """把设置里可即时生效的项应用出来：自动滚动、容量、日志级别、折叠、携带历史。"""

    settings = context.settings
    window.log_view.set_autoscroll(
        parse_bool(settings.get(SETTINGS_KEYS.AUTOSCROLL, True), True)
    )
    window.analysis_panel.set_details_expanded(
        parse_bool(settings.get(SETTINGS_KEYS.CHAT_DETAILS_EXPANDED, False), False)
    )
    service.set_history_rounds(_history_rounds(settings))
    context.pipeline.capacity = _capacity(settings)
    dropped = context.pipeline.enforce_capacity()
    if dropped:
        drop_update = PipelineUpdate(dropped_sequences=dropped)
        window.log_view.append_update(drop_update)
        window.chart_panel.append_update(drop_update)
        if context.anomaly_controller is not None:
            context.anomaly_controller.ingest_update(drop_update)
    configure_logging(
        level=str(settings.get(SETTINGS_KEYS.LOG_LEVEL, "INFO")), log_file=log_file_path()
    )


def _log_store(context: ApplicationContext) -> Any:
    """按设置构造日志导入导出存储。"""

    from serial_log_analyzer.io.storage.log_file_store import LogFileStore

    chosen = str(context.settings.get(SETTINGS_KEYS.EXPORT_DIR, "") or "").strip()
    return LogFileStore(Path(chosen) if chosen else default_export_dir())


def export_logs(context: ApplicationContext, path: Path, fmt: object = None) -> int:
    """把内存中的日志导出到 ``path``，返回写出的行数。

    参数:
        context: 组装结果（提供流水线条目与导出目录设置）。
        path: 目标文件路径。
        fmt: :class:`ExportFormat`；``None`` 时按路径后缀推断，未知后缀按文本导出。
    """

    from serial_log_analyzer.io.storage.log_file_store import ExportFormat

    if fmt is None:
        suffix = path.suffix
        fmt = next((item for item in ExportFormat if item.suffix == suffix), ExportFormat.TEXT)
    return _log_store(context).export_entries(context.pipeline.entries(), path, fmt=fmt)


def import_logs(
    context: ApplicationContext, path: Path, on_update: Callable[[PipelineUpdate], None]
) -> int:
    """把 ``path`` 逐行导入既有解析流水线，返回导入行数。

    参数:
        context: 组装结果（提供流水线）。
        path: 源文件路径。
        on_update: 每行产生的 :class:`PipelineUpdate`，由调用方刷入界面。
    """

    def _feed(text: str, moment: float) -> None:
        on_update(context.pipeline.feed(text, moment))

    return _log_store(context).import_entries(path, _feed)


def _export_logs(window: MainWindow, context: ApplicationContext) -> None:
    """导出对话框：按后缀选择 TEXT / CSV / JSONL。"""

    from PySide6.QtWidgets import QFileDialog

    from serial_log_analyzer.core.errors import AppError
    from serial_log_analyzer.io.storage.log_file_store import ExportFormat

    store = _log_store(context)
    formats = ";;".join(f"{fmt.display_name} (*{fmt.suffix})" for fmt in ExportFormat)
    path_text, selected = QFileDialog.getSaveFileName(
        window, "导出日志", str(store.suggested_path(fmt=ExportFormat.TEXT)), formats
    )
    if not path_text:
        return
    target = Path(path_text)
    if not target.suffix:
        target = target.with_suffix(_suffix_of(selected) or ExportFormat.TEXT.suffix)
    try:
        lines = export_logs(context, target)
    except AppError as exc:
        window.show_status(f"导出失败：{exc}")
        return
    window.show_status(f"已导出 {len(context.pipeline.entries())} 条到 {target}（{lines} 行）")


def _report_store(context: ApplicationContext) -> ReportFileStore:
    """按设置构造诊断报告存储。"""

    chosen = str(context.settings.get(SETTINGS_KEYS.EXPORT_DIR, "") or "").strip()
    if chosen:
        return ReportFileStore(Path(chosen))
    if context.report_file_store is not None:
        return context.report_file_store
    return ReportFileStore(default_export_dir())


def export_report(
    context: ApplicationContext,
    path: Path,
    fmt: object = None,
    *,
    generated_at: float | None = None,
) -> Path:
    """生成当前会话的结构化诊断报告并写入 ``path``，返回实际文件路径。

    参数:
        context: 组装结果（提供流水线、异常服务与当前分析结果）。
        path: 目标文件路径。
        fmt: :class:`ReportFormat`；``None`` 时按路径后缀推断。
        generated_at: 可选生成时间戳。
    """

    if context.anomaly_service is None:
        raise ConfigError("异常检测服务尚未初始化，无法生成诊断报告")
    analysis_result = (
        context.analysis_service.latest_result
        if context.analysis_service is not None
        else None
    )
    profile = context.profile
    profile_label = f"{profile.profile_id} · {profile.model}" if profile is not None else None
    report = build_diagnostic_report(
        context.pipeline,
        context.anomaly_service,
        preset_id=context.preset.preset_id,
        analysis_result=analysis_result,
        profile_label=profile_label,
        generated_at=generated_at,
    )
    return _report_store(context).export_report(report, path, fmt=fmt)


def _export_report(window: MainWindow, context: ApplicationContext) -> None:
    """诊断报告导出对话框：按后缀选择 Markdown (.md) / JSON (.json)。"""

    from PySide6.QtWidgets import QFileDialog

    store = _report_store(context)
    formats = ";;".join(f"{fmt.display_name} (*{fmt.suffix})" for fmt in ReportFormat)
    path_text, selected = QFileDialog.getSaveFileName(
        window,
        "导出诊断报告",
        str(store.suggested_path(fmt=ReportFormat.MARKDOWN)),
        formats,
    )
    if not path_text:
        return
    target = Path(path_text)
    if not target.suffix:
        target = target.with_suffix(_suffix_of(selected) or ReportFormat.MARKDOWN.suffix)
    fmt = next(
        (item for item in ReportFormat if item.suffix == target.suffix.lower()),
        None,
    )
    try:
        written = export_report(context, target, fmt=fmt)
    except AppError as exc:
        window.show_status(f"导出诊断报告失败：{exc}")
        return
    window.show_status(f"已导出诊断报告到 {written}")


def _import_logs(window: MainWindow, context: ApplicationContext) -> None:
    """导入对话框：逐行喂进流水线并刷新表格。"""

    from PySide6.QtWidgets import QFileDialog

    from serial_log_analyzer.core.errors import AppError

    path_text, _ = QFileDialog.getOpenFileName(
        window, "导入日志", str(_log_store(context).default_dir), "日志文本 (*.log *.txt)"
    )
    if not path_text:
        return
    updates: list[PipelineUpdate] = []
    try:
        count = import_logs(context, Path(path_text), updates.append)
    except AppError as exc:
        window.show_status(f"导入失败：{exc}")
        return
    merged = coalesce_updates(updates)
    if merged.added or merged.updated or merged.dropped_sequences:
        window.log_view.append_update(merged)
        window.chart_panel.append_update(merged)
        if context.anomaly_controller is not None:
            context.anomaly_controller.ingest_update(merged)
    window.show_status(f"已导入 {count} 行到日志表格")


def _suffix_of(selected_filter: str) -> str:
    """从文件对话框的选择项里取出后缀，如 ``导出 (*.csv)`` → ``.csv``。"""

    start = selected_filter.rfind("*")
    end = selected_filter.rfind(")")
    return selected_filter[start + 1 : end] if 0 <= start < end else ""


def _open_provider(
    window: MainWindow, context: ApplicationContext, service: AnalysisService
) -> None:
    """打开模型服务对话框（可新建 / 编辑 / 删除 Profile、拉取模型列表）。

    关闭后重读 Profile 列表：当前 Profile 已被删除时切到第一个可用项，仍存在时把
    改动（base_url / model / extra_* / 凭据来源等）应用到分析服务。
    """

    from serial_log_analyzer.core.llm.adapter_loader import load_adapters
    from serial_log_analyzer.core.llm.model_discovery import ModelDiscoveryService
    from serial_log_analyzer.io.storage.profile_store import ProfileStore
    from serial_log_analyzer.ui.dialogs.provider_dialog import ProviderDialog

    reload_profiles = lambda: load_profiles(context.resources)  # noqa: E731 - 传给对话框的取数回调
    ProviderDialog(
        reload_profiles(),
        load_adapters(context.resources),
        window,
        keyring=context.keyring,
        reload=reload_profiles,
        store=ProfileStore(),
        discovery=ModelDiscoveryService(context.http_transport, context.credentials),
    ).exec()
    _refresh_profiles(window, context, service)


def _refresh_profiles(
    window: MainWindow, context: ApplicationContext, service: AnalysisService
) -> None:
    """Profile 列表变动后刷新工具栏，并把当前 Profile 的最新声明应用到分析服务。"""

    profiles = load_profiles(context.resources)
    ids = {item.profile_id for item in profiles}
    if context.profile.profile_id not in ids:
        _switch_profile(
            window, context, service, profiles[0].profile_id if profiles else ""
        )
    elif profiles:
        try:
            profile = load_profile(context.resources, context.profile.profile_id)
            adapter = load_adapter(context.resources, profile.adapter_id)
            service.set_profile(profile, adapter)
            context.profile = profile
            context.adapter = adapter
        except AppError as exc:
            window.show_status(f"Profile 改动未能即时生效：{exc}")
    window.analysis_panel.set_profiles(profiles, context.profile.profile_id)


def _switch_profile(
    window: MainWindow, context: ApplicationContext, service: AnalysisService, profile_id: str
) -> None:
    """切换当前 LLM Profile：写设置、换 Adapter 与请求构建器。"""

    from serial_log_analyzer.core.errors import AppError

    if not profile_id or profile_id == context.profile.profile_id:
        return
    try:
        profile = load_profile(context.resources, profile_id)
        adapter = load_adapter(context.resources, profile.adapter_id)
        service.set_profile(profile, adapter)
    except AppError as exc:
        window.analysis_panel.set_current_profile(context.profile.profile_id)
        window.show_status(f"切换 Profile 失败：{exc}")
        return
    context.profile = profile
    context.adapter = adapter
    context.settings.set(SETTINGS_KEYS.CURRENT_PROFILE, profile_id)
    window.analysis_panel.set_state(AnalysisState.IDLE)
    window.show_status(f"已切换到 Profile {profile_id}（{profile.model}）")


def _choose_preset(window: MainWindow, context: ApplicationContext) -> None:
    """让用户从内置 Preset 中选一个并切换。"""

    from PySide6.QtWidgets import QInputDialog

    presets = sorted(load_presets(context.resources), key=lambda item: item.preset_id)
    if not presets:
        window.show_status("没有可用的日志 Preset")
        return
    labels = [f"{item.preset_id} · {item.display_name}" for item in presets]
    current = next(
        (index for index, item in enumerate(presets) if item.preset_id == context.preset.preset_id),
        0,
    )
    choice, accepted = QInputDialog.getItem(window, "切换日志 Preset", "Preset", labels, current, False)
    if accepted:
        _switch_preset(window, context, presets[labels.index(choice)].preset_id)


def _switch_preset(window: MainWindow, context: ApplicationContext, preset_id: str) -> None:
    """切换日志 Preset：重建流水线并清空表格（连接中不允许）。"""

    from serial_log_analyzer.core.errors import AppError

    if not preset_id or preset_id == context.preset.preset_id:
        return
    try:
        preset = load_preset(context.resources, preset_id)
        pipeline = LogPipeline(
            LogParser(preset), capacity=_capacity(context.settings)
        )
        context.session.set_pipeline(pipeline)
    except AppError as exc:
        window.show_status(f"切换 Preset 失败：{exc}")
        return
    context.preset = preset
    context.pipeline = pipeline
    context.context_builder.set_pipeline(pipeline)
    if context.notification_controller is not None:
        context.notification_controller.set_pipeline(pipeline)
    elif context.notification_service is not None:
        context.notification_service.set_pipeline(pipeline)
    if context.analysis_service is not None:
        context.analysis_service.set_board_prompt(preset.prompt)
    window.log_view.clear()
    if context.anomaly_controller is not None:
        context.anomaly_controller.reset()
    window.anomaly_panel.clear_alert_banner()
    window.command_panel.set_commands(preset.commands)
    window.chart_panel.set_preset_fields(tuple(preset.line.fields))
    window.analysis_panel.set_board_prompt(preset.display_name, preset.prompt)
    window.set_preset_name(preset_id)
    context.settings.set(SETTINGS_KEYS.CURRENT_PRESET, preset_id)
    window.show_status(f"已切换到 Preset {preset_id}，日志已清空")


def _restore_layout(window: MainWindow, settings: Any) -> None:
    """按存档恢复停靠布局；面板集合变过就丢弃存档，改用设计好的默认排布。

    Qt 的 ``restoreState`` 会把存档里不存在的面板直接隐藏，所以新增/删除面板后必须放弃旧布局，
    否则新面板一启动就不见了。
    """

    state = settings.get(SETTINGS_KEYS.WINDOW_STATE)
    if state is None:
        return
    saved = settings.get(SETTINGS_KEYS.WINDOW_DOCKS)
    if sorted(map(str, saved or [])) != window.dock_names():
        return
    window.restore_layout(state)


def _restore_view(window: MainWindow, toolbar: SerialToolBar, log_view: LogView, settings: Any) -> None:
    """按设置恢复窗口几何、停靠布局、串口选择、自动滚动与分析细节折叠。"""

    geometry = settings.get(SETTINGS_KEYS.WINDOW_GEOMETRY)
    if geometry is not None:
        window.restoreGeometry(geometry)
    _restore_layout(window, settings)
    window.analysis_panel.set_details_expanded(
        parse_bool(settings.get(SETTINGS_KEYS.CHAT_DETAILS_EXPANDED, False), False)
    )
    toolbar.restore(
        str(settings.get(SETTINGS_KEYS.LAST_PORT, "") or ""),
        str(settings.get(SETTINGS_KEYS.LAST_BAUDRATE, "115200") or "115200"),
    )
    log_view.set_autoscroll(parse_bool(settings.get(SETTINGS_KEYS.AUTOSCROLL, True), True))


def _shutdown(main_controller: MainController, window: MainWindow, settings: Any) -> None:
    """退出前清理并同步界面偏好。"""

    main_controller.shutdown()
    settings.set(SETTINGS_KEYS.WINDOW_GEOMETRY, window.saveGeometry())
    settings.set(SETTINGS_KEYS.WINDOW_STATE, window.saveState())
    settings.set(SETTINGS_KEYS.WINDOW_DOCKS, window.dock_names())
    sync = getattr(settings, "sync", None)
    if callable(sync):
        sync()


def main(argv: list[str] | None = None) -> int:
    """应用入口：组装 → 显示窗口 → 进入事件循环。

    参数:
        argv: 命令行参数；``None`` 时使用 ``sys.argv``。

    返回:
        进程退出码。
    """

    context = build_application(argv)
    context.window = build_window(context)
    context.window.show()
    return int(context.app.exec())


def _current_preset(resources: Any, settings: Any) -> Any:
    """按设置选择 Preset；未设置或已失效时按 ``preset_id`` 取第一个。"""

    presets = sorted(load_presets(resources), key=lambda item: item.preset_id)
    if not presets:
        raise ConfigError("没有可用的日志 Preset")
    wanted = str(settings.get(SETTINGS_KEYS.CURRENT_PRESET, "") or "")
    if wanted and any(item.preset_id == wanted for item in presets):
        return load_preset(resources, wanted)
    return load_preset(resources, presets[0].preset_id)


def _current_profile(resources: Any, settings: Any) -> Any:
    """按设置选择 Profile；未设置或已失效时用内置列表的第一项。"""

    profiles = load_profiles(resources)
    if not profiles:
        raise ConfigError("没有可用的 LLM Profile")
    wanted = str(settings.get(SETTINGS_KEYS.CURRENT_PROFILE, "") or "")
    if wanted and any(item.profile_id == wanted for item in profiles):
        return load_profile(resources, wanted)
    return load_profile(resources, profiles[0].profile_id)


def _history_rounds(settings: Any) -> int:
    """读取「最多携带历史轮数」；``0`` 表示不限制，非法值直接失败。"""

    value = settings.get(SETTINGS_KEYS.LLM_HISTORY_ROUNDS, 0)
    try:
        rounds = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"携带历史轮数必须是整数：{value}") from exc
    if rounds < 0:
        raise ConfigError(f"携带历史轮数不能为负：{rounds}")
    return rounds


def _capacity(settings: Any) -> int:
    """读取日志缓冲容量；非法或非正数时直接失败，不静默取默认值。"""

    value = settings.get(SETTINGS_KEYS.LOG_CAPACITY, _DEFAULT_CAPACITY)
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"日志缓冲容量必须是整数：{value}") from exc
    if size <= 0:
        raise ConfigError(f"日志缓冲容量必须为正数：{size}")
    return size
