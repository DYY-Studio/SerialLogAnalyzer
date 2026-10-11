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
    assert window.analysis_panel.goal_combo.count() == 4
    assert window.serial_toolbar.baud_combo.currentText() == "115200"
    assert window.analysis_dock.widget() is window.analysis_panel
    assert window.command_dock.widget() is window.command_panel
    # 设备控制器已把回调安装到会话上
    assert context.session._handlers is not None
