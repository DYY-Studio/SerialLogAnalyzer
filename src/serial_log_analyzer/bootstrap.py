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
from dataclasses import dataclass
from typing import Any

from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import QApplication

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.adapter_loader import load_adapter
from serial_log_analyzer.core.llm.profile_loader import load_profile, load_profiles
from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.logs.preset_loader import load_preset, load_presets
from serial_log_analyzer.core.models.device import DeviceConnectionState
from serial_log_analyzer.core.prompts.loader import PromptLibrary
from serial_log_analyzer.core.services.analysis import AnalysisContextBuilder, AnalysisService
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver
from serial_log_analyzer.core.services.device_session import DeviceSession
from serial_log_analyzer.diagnostics.app_logging import configure_logging
from serial_log_analyzer.io.credentials.keyring_store import KeyringStoreAdapter
from serial_log_analyzer.io.environment import DotEnvEnvironmentReader
from serial_log_analyzer.io.llm.qt_http_transport import QtHttpTransport
from serial_log_analyzer.io.paths import repo_root, user_config_dir
from serial_log_analyzer.io.resources import CompositeResourceLoader
from serial_log_analyzer.io.serial.qt_serial_transport import QtSerialTransport
from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS, QtSettingsStore
from serial_log_analyzer.ui.controllers.analysis_controller import AnalysisController
from serial_log_analyzer.ui.controllers.device_controller import DeviceController
from serial_log_analyzer.ui.controllers.main_controller import MainController
from serial_log_analyzer.ui.main_window import MainWindow
from serial_log_analyzer.ui.models.log_table_model import LogTableModel
from serial_log_analyzer.ui.widgets.analysis_panel import AnalysisPanel
from serial_log_analyzer.ui.widgets.log_view import LogView
from serial_log_analyzer.ui.widgets.serial_toolbar import SerialToolBar

__all__ = ["ApplicationContext", "build_application", "main"]

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

    device = DeviceController(context.session)
    analysis = AnalysisController(
        AnalysisService(
            context.adapter,
            context.http_transport,
            context.prompts,
            context.credentials,
            profile=context.profile,
        ),
        context.context_builder,
    )
    main = MainController(device, analysis, settings)
    window = MainWindow(log_view, panel, toolbar, on_close=lambda: _shutdown(main, window, settings))

    toolbar.refresh_requested.connect(device.refresh_ports)
    toolbar.connect_requested.connect(device.connect)
    toolbar.disconnect_requested.connect(device.disconnect)
    toolbar.clear_requested.connect(device.clear_logs)
    toolbar.clear_requested.connect(log_view.clear)
    toolbar.command_submitted.connect(device.send_command)
    device.ports_refreshed.connect(toolbar.set_ports)

    def _on_connection(state: object, message: str) -> None:
        toolbar.set_connected(state is DeviceConnectionState.CONNECTED)
        window.show_status(message)

    device.connection_changed.connect(_on_connection)
    device.log_update.connect(log_view.append_update)
    device.error_occurred.connect(window.show_status)
    device.command_reply.connect(lambda reply: toolbar.set_command_reply(reply.text))

    log_view.selection_changed.connect(analysis.selected_sequences)
    log_view.clear_requested.connect(device.clear_logs)
    log_view.clear_requested.connect(log_view.clear)
    log_view.export_requested.connect(
        lambda: window.show_status("导出功能待接通（io/storage 的 LogFileStore 已就绪）")
    )

    panel.analyze_requested.connect(lambda payload: analysis.start_analysis(*payload))
    panel.follow_up_requested.connect(analysis.follow_up)
    panel.cancel_requested.connect(analysis.cancel)
    panel.reset_requested.connect(analysis.reset)
    analysis.result_updated.connect(panel.set_result)
    analysis.state_changed.connect(panel.set_state)
    analysis.error_occurred.connect(window.show_status)

    window.settings_requested.connect(lambda: _open_settings(window, settings))
    window.provider_requested.connect(lambda: _open_provider(window, context))
    window.credential_requested.connect(lambda: _open_credential(window, context))

    _restore_view(window, toolbar, log_view, settings)
    device.refresh_ports()
    window.show_status("就绪")
    return window


def _open_settings(window: MainWindow, settings: Any) -> None:
    """打开设置对话框（键值由 ``io.settings`` 决定落盘位置）。"""

    from serial_log_analyzer.ui.dialogs.settings_dialog import SettingsDialog

    SettingsDialog(settings, window).exec()


def _open_provider(window: MainWindow, context: ApplicationContext) -> None:
    """打开模型服务对话框；保存走 ``ProfileStore`` 写用户配置目录。"""

    from serial_log_analyzer.io.storage.profile_store import ProfileStore
    from serial_log_analyzer.ui.dialogs.provider_dialog import ProviderDialog

    ProviderDialog(load_profiles(context.resources), window, store=ProfileStore()).exec()


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


def _restore_view(window: MainWindow, toolbar: SerialToolBar, log_view: LogView, settings: Any) -> None:
    """按设置恢复窗口几何、splitter、串口选择与自动滚动。"""

    geometry = settings.get(SETTINGS_KEYS.WINDOW_GEOMETRY)
    if geometry is not None:
        window.restoreGeometry(geometry)
    sizes = settings.get(SETTINGS_KEYS.SPLITTER_SIZES)
    if sizes:
        window.splitter.setSizes([int(size) for size in sizes])
    toolbar.restore(
        str(settings.get(SETTINGS_KEYS.LAST_PORT, "") or ""),
        str(settings.get(SETTINGS_KEYS.LAST_BAUDRATE, "115200") or "115200"),
    )
    log_view.set_autoscroll(bool(settings.get(SETTINGS_KEYS.AUTOSCROLL, True)))


def _shutdown(main_controller: MainController, window: MainWindow, settings: Any) -> None:
    """退出前清理并同步界面偏好。"""

    main_controller.shutdown()
    settings.set(SETTINGS_KEYS.WINDOW_GEOMETRY, window.saveGeometry())
    settings.set(SETTINGS_KEYS.SPLITTER_SIZES, window.splitter.sizes())


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
