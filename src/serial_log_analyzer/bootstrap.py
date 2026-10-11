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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import QApplication

from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.llm.adapter_loader import load_adapter
from serial_log_analyzer.core.llm.profile_loader import load_profile, load_profiles
from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline, PipelineUpdate
from serial_log_analyzer.core.logs.preset_loader import load_preset, load_presets
from serial_log_analyzer.core.models.analysis import AnalysisState
from serial_log_analyzer.core.models.device import DeviceConnectionState
from serial_log_analyzer.core.prompts.loader import PromptLibrary
from serial_log_analyzer.core.services.analysis import AnalysisContextBuilder, AnalysisService
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver
from serial_log_analyzer.core.services.device_session import DeviceSession
from serial_log_analyzer.diagnostics.app_logging import configure_logging
from serial_log_analyzer.io.credentials.keyring_store import KeyringStoreAdapter
from serial_log_analyzer.io.environment import DotEnvEnvironmentReader
from serial_log_analyzer.io.llm.qt_http_transport import QtHttpTransport
from serial_log_analyzer.io.paths import default_export_dir, repo_root, user_config_dir
from serial_log_analyzer.io.resources import CompositeResourceLoader
from serial_log_analyzer.io.serial.qt_serial_transport import QtSerialTransport
from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS, QtSettingsStore
from serial_log_analyzer.ui.controllers.analysis_controller import AnalysisController
from serial_log_analyzer.ui.controllers.device_controller import DeviceController
from serial_log_analyzer.ui.controllers.main_controller import MainController
from serial_log_analyzer.ui.main_window import MainWindow
from serial_log_analyzer.ui.models.log_table_model import LogTableModel
from serial_log_analyzer.ui.widgets.analysis_panel import AnalysisPanel
from serial_log_analyzer.ui.widgets.command_panel import CommandPanel
from serial_log_analyzer.ui.widgets.log_view import LogView
from serial_log_analyzer.ui.widgets.serial_toolbar import SerialToolBar

__all__ = ["ApplicationContext", "build_application", "export_logs", "import_logs", "main"]

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
        window: 主窗口，由 :func:`build_window` 填充。
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
    window: Any = None


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

    settings = QtSettingsStore()
    configure_logging(level=str(settings.get(SETTINGS_KEYS.LOG_LEVEL, "INFO")))

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
    manager = QNetworkAccessManager()
    return ApplicationContext(
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
    )


def build_window(context: ApplicationContext) -> MainWindow:
    """组装 ``ui`` 层（控制器 / 窗口 / 组件）并接通信号。

    参数:
        context: :func:`build_application` 的组装结果。

    返回:
        已接线的 :class:`MainWindow`。
    """

    settings = context.settings
    log_view = LogView(LogTableModel())
    panel = AnalysisPanel()
    panel.set_goals(context.prompts.goals())
    toolbar = SerialToolBar()
    command_panel = CommandPanel()

    device = DeviceController(context.session)
    service = _analysis_service(context)
    analysis = AnalysisController(service, context.context_builder)
    service.set_history_rounds(_history_rounds(settings))
    main = MainController(device, analysis, settings)
    window = MainWindow(
        log_view,
        panel,
        toolbar,
        command_panel,
        on_close=lambda: _shutdown(main, window, settings),
    )
    panel.set_profiles(load_profiles(context.resources), context.profile.profile_id)

    toolbar.refresh_requested.connect(device.refresh_ports)
    toolbar.connect_requested.connect(device.connect)
    toolbar.disconnect_requested.connect(device.disconnect)
    command_panel.command_submitted.connect(device.send_command)
    device.ports_refreshed.connect(toolbar.set_ports)

    def _on_connection(state: object, message: str) -> None:
        toolbar.set_connected(state is DeviceConnectionState.CONNECTED)
        window.show_status(message)

    device.connection_changed.connect(_on_connection)
    device.log_update.connect(log_view.append_update)
    device.error_occurred.connect(window.show_status)
    device.command_reply.connect(command_panel.append_reply)

    log_view.selection_changed.connect(analysis.selected_sequences)
    log_view.autoscroll_toggled.connect(
        lambda enabled: settings.set(SETTINGS_KEYS.AUTOSCROLL, bool(enabled))
    )

    window.clear_requested.connect(device.clear_logs)
    window.clear_requested.connect(log_view.clear)
    window.export_requested.connect(lambda: _export_logs(window, context))
    window.import_requested.connect(lambda: _import_logs(window, context))
    toolbar.serial_settings_requested.connect(lambda: _open_serial_settings(window, toolbar))
    toolbar.error_occurred.connect(window.show_status)
    panel.profile_changed.connect(lambda profile_id: _switch_profile(window, context, service, profile_id))

    panel.analyze_requested.connect(lambda payload: analysis.start_analysis(*payload))
    panel.follow_up_requested.connect(analysis.follow_up)
    panel.cancel_requested.connect(analysis.cancel)
    panel.reset_requested.connect(analysis.reset)
    analysis.result_updated.connect(panel.set_result)
    analysis.state_changed.connect(panel.set_state)
    analysis.error_occurred.connect(window.show_status)

    window.settings_requested.connect(lambda: _open_settings(window, context, service))
    window.provider_requested.connect(lambda: _open_provider(window, context, service))
    window.credential_requested.connect(lambda: _open_credential(window, context))
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
    )


def _open_settings(window: MainWindow, context: ApplicationContext, service: AnalysisService) -> None:
    """打开设置对话框；关闭后把可即时生效的项立即应用到界面与流水线。"""

    from serial_log_analyzer.ui.dialogs.settings_dialog import SettingsDialog

    SettingsDialog(context.settings, window).exec()
    _apply_settings(window, context, service)


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
    window.log_view.set_autoscroll(bool(settings.get(SETTINGS_KEYS.AUTOSCROLL, True)))
    window.analysis_panel.set_details_expanded(
        bool(settings.get(SETTINGS_KEYS.CHAT_DETAILS_EXPANDED, False))
    )
    service.set_history_rounds(_history_rounds(settings))
    context.pipeline.capacity = _capacity(settings)
    dropped = context.pipeline.enforce_capacity()
    if dropped:
        window.log_view.append_update(PipelineUpdate(dropped_sequences=dropped))
    configure_logging(level=str(settings.get(SETTINGS_KEYS.LOG_LEVEL, "INFO")))


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


def _import_logs(window: MainWindow, context: ApplicationContext) -> None:
    """导入对话框：逐行喂进流水线并刷新表格。"""

    from PySide6.QtWidgets import QFileDialog

    from serial_log_analyzer.core.errors import AppError

    path_text, _ = QFileDialog.getOpenFileName(
        window, "导入日志", str(_log_store(context).default_dir), "日志文本 (*.log *.txt)"
    )
    if not path_text:
        return
    try:
        count = import_logs(context, Path(path_text), window.log_view.append_update)
    except AppError as exc:
        window.show_status(f"导入失败：{exc}")
        return
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
    改动（base_url / model / extra_* 等）应用到分析服务。
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


def _open_credential(window: MainWindow, context: ApplicationContext) -> None:
    """打开凭据对话框；钥匙串账号与 Profile 声明保持一致。"""

    from serial_log_analyzer.ui.dialogs.credential_dialog import CredentialDialog

    credential = context.profile.credential
    CredentialDialog(
        context.keyring,
        context.profile.profile_id,
        window,
        account=credential.name or context.profile.profile_id,
    ).exec()


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
    window.log_view.clear()
    context.settings.set(SETTINGS_KEYS.CURRENT_PRESET, preset_id)
    window.show_status(f"已切换到 Preset {preset_id}，日志已清空")


def _restore_view(window: MainWindow, toolbar: SerialToolBar, log_view: LogView, settings: Any) -> None:
    """按设置恢复窗口几何、工具栏/停靠布局、串口选择、自动滚动与分析细节折叠。"""

    geometry = settings.get(SETTINGS_KEYS.WINDOW_GEOMETRY)
    if geometry is not None:
        window.restoreGeometry(geometry)
    state = settings.get(SETTINGS_KEYS.WINDOW_STATE)
    if state is not None:
        window.restoreState(state)
    window.analysis_panel.set_details_expanded(
        bool(settings.get(SETTINGS_KEYS.CHAT_DETAILS_EXPANDED, False))
    )
    toolbar.restore(
        str(settings.get(SETTINGS_KEYS.LAST_PORT, "") or ""),
        str(settings.get(SETTINGS_KEYS.LAST_BAUDRATE, "115200") or "115200"),
    )
    log_view.set_autoscroll(bool(settings.get(SETTINGS_KEYS.AUTOSCROLL, True)))


def _shutdown(main_controller: MainController, window: MainWindow, settings: Any) -> None:
    """退出前清理并同步界面偏好。"""

    main_controller.shutdown()
    settings.set(SETTINGS_KEYS.WINDOW_GEOMETRY, window.saveGeometry())
    settings.set(SETTINGS_KEYS.WINDOW_STATE, window.saveState())


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
