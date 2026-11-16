"""组合根组装测试：只到 ``io`` + ``core`` 为止（``ui`` 仍是 stub）。"""

from __future__ import annotations

import sys

import pytest

from serial_log_analyzer import bootstrap
from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS


class FakeSettings:
    """内存设置存储，避免测试写用户注册表。"""

    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def set(self, key: str, value: object) -> None:
        self.values[key] = value


@pytest.fixture
def fake_settings(monkeypatch):
    settings = FakeSettings()

    def _factory(*args, **kwargs) -> FakeSettings:
        return settings

    monkeypatch.setattr(bootstrap, "QtSettingsStore", _factory)
    return settings


def test_build_application_assembles_io_and_core(qapp, fake_settings) -> None:
    context = bootstrap.build_application(["-platform", "offscreen"])

    assert context.app is qapp or context.app is not None
    assert context.preset.preset_id == "hi3861-default"
    assert context.profile.profile_id == "deepseek"
    assert context.adapter.adapter_id == context.profile.adapter_id
    assert context.session.pipeline is context.pipeline
    assert context.context_builder is not None
    assert len(context.prompts.goals()) == 4
    assert context.window is None


@pytest.mark.skipif(sys.platform != "win32", reason="Schannel 只在 Windows 上可用")
def test_windows_forces_system_tls_backend(qapp, fake_settings) -> None:
    """Windows 上必须固定用 Schannel：Qt 的 OpenSSL 插件与进程里的 Python ``ssl`` 混用会崩进程。"""

    from PySide6.QtNetwork import QSslSocket

    bootstrap.build_application(["-platform", "offscreen"])

    assert QSslSocket.activeBackend() == "schannel"


def test_build_application_honours_stored_preset_and_profile(qapp, fake_settings) -> None:
    fake_settings.values[SETTINGS_KEYS.CURRENT_PRESET] = "hi3861-timestamped"
    fake_settings.values[SETTINGS_KEYS.CURRENT_PROFILE] = "internlm"
    fake_settings.values[SETTINGS_KEYS.LOG_CAPACITY] = 500

    context = bootstrap.build_application(["-platform", "offscreen"])

    assert context.preset.preset_id == "hi3861-timestamped"
    assert context.profile.profile_id == "internlm"


def test_invalid_capacity_fails_loudly(qapp, fake_settings) -> None:
    fake_settings.values[SETTINGS_KEYS.LOG_CAPACITY] = "many"

    with pytest.raises(ConfigError):
        bootstrap.build_application(["-platform", "offscreen"])


def test_switch_profile_and_preset_stay_in_sync(qapp, fake_settings) -> None:
    from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS as KEYS

    context = bootstrap.build_application(["-platform", "offscreen"])
    window = bootstrap.build_window(context)
    previous_pipeline = context.pipeline

    index = window.analysis_panel.profile_combo.findData("internlm")
    window.analysis_panel.profile_combo.setCurrentIndex(index)

    assert context.profile.profile_id == "internlm"
    assert context.adapter.adapter_id == "openai-compatible"
    assert fake_settings.values[KEYS.CURRENT_PROFILE] == "internlm"

    bootstrap._switch_preset(window, context, "hi3861-timestamped")

    assert context.preset.preset_id == "hi3861-timestamped"
    assert context.pipeline is not previous_pipeline
    assert len(context.pipeline) == 0
    assert fake_settings.values[KEYS.CURRENT_PRESET] == "hi3861-timestamped"


def test_build_window_wires_the_ui(qapp, fake_settings) -> None:
    context = bootstrap.build_application(["-platform", "offscreen"])

    window = bootstrap.build_window(context)

    assert window.windowTitle().startswith("SerialLogAnalyzer")
    assert window.analysis_panel.goal_combo.count() == 5  # 4 个内置目标 + 「无」
    assert window.serial_toolbar.baud_combo.currentText() == "115200"
    assert window.analysis_dock.widget() is window.analysis_panel
    assert window.command_dock.widget() is window.command_panel
    # 设备控制器已把回调安装到会话上
    assert context.session._handlers is not None


def test_build_window_wires_status_bar_and_command_timeout(qapp, fake_settings, monkeypatch, qtbot) -> None:
    from serial_log_analyzer.ui.controllers.device_controller import DeviceController

    created_devices: list[DeviceController] = []
    created_analyses: list[object] = []

    def _fast_device(session):
        ctrl = DeviceController(session, batch_interval_ms=20, command_timeout_ms=50)
        created_devices.append(ctrl)
        return ctrl

    orig_analysis = bootstrap.AnalysisController

    def _capture_analysis(service, builder):
        ctrl = orig_analysis(service, builder)
        created_analyses.append(ctrl)
        return ctrl

    monkeypatch.setattr(bootstrap, "DeviceController", _fast_device)
    monkeypatch.setattr(bootstrap, "AnalysisController", _capture_analysis)

    context = bootstrap.build_application(["-platform", "offscreen"])
    window = bootstrap.build_window(context)

    # 1) 日志条数变化通过 DeviceController 批处理驱动状态栏计数
    context.session._on_bytes(b"[I] [wifi] ok\r\n")
    qtbot.waitUntil(lambda: window.log_count_label.text() == "日志 1 条", timeout=1000)

    # 2) 命令超时信号联动写入 CommandPanel 与状态栏
    created_devices[0].command_timed_out.emit("PING")
    assert "⏱ 超时未收到响应：PING" in window.command_panel.reply_view.toPlainText()
    assert "PING" in window.status_bar.currentMessage()

    # 3) 用量更新与新会话重置同步状态栏
    created_analyses[0].usage_updated.emit(10, 5, 15)
    assert window.usage_status_label.text() == "Token: 10 / 5 / 15"
    assert window.usage_status_label.isHidden() is False
    window.analysis_panel.new_session_btn.click()
    assert window.usage_status_label.isHidden() is True

    # 4) 窗口关闭清理无未停定时器异常
    window.close()
