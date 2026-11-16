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


def test_bootstrap_anomaly_wiring_capacity_import_and_report_export(
    qapp, fake_settings, monkeypatch, qtbot, tmp_path
) -> None:
    """全链路接线：异常入池、过滤跳转提示、容量淘汰同步、导入与诊断报告导出。"""

    import json

    from serial_log_analyzer.core.models.analysis import AnalysisResult, AnalysisState
    from serial_log_analyzer.core.models.logs import LogLevel
    from serial_log_analyzer.io.storage.report_file_store import ReportFormat
    from serial_log_analyzer.ui.controllers.device_controller import DeviceController

    def _fast_device(session):
        return DeviceController(session, batch_interval_ms=20, command_timeout_ms=50)

    monkeypatch.setattr(bootstrap, "DeviceController", _fast_device)
    fake_settings.values[SETTINGS_KEYS.EXPORT_DIR] = str(tmp_path)

    context = bootstrap.build_application(["-platform", "offscreen"])
    window = bootstrap.build_window(context)

    # 1) 实时串口到达告警级别日志 -> 异常面板与状态栏告警角标联动
    context.session._on_bytes(b"[I] [boot] system ready\r\n[E] [mem] malloc failed size=128\r\n")
    qtbot.waitUntil(lambda: window.log_count_label.text() == "日志 2 条", timeout=1000)
    assert window.alert_badge_btn.text() == "告警 1"
    assert len(window.anomaly_panel.clusters()) == 1
    cluster = window.anomaly_panel.clusters()[0]
    assert "新告警" in window.status_bar.currentMessage()

    # 2) 被过滤隐藏时定位不误跳并明确提示原因；解除过滤后正常选中目标行
    window.log_view._level_boxes[LogLevel.ERROR].setChecked(False)
    window.anomaly_panel.locate_requested.emit(cluster.evidence_sequences[-1])
    assert "被过滤条件隐藏" in window.status_bar.currentMessage()

    window.log_view._level_boxes[LogLevel.ERROR].setChecked(True)
    window.anomaly_panel.locate_requested.emit(cluster.evidence_sequences[-1])
    assert [entry.sequence for entry in window.log_view.selected_log_entries()] == [
        cluster.evidence_sequences[-1]
    ]

    # 3) _apply_settings 触发容量淘汰时，dropped_sequences 必须同步剔除异常簇证据
    fake_settings.values[SETTINGS_KEYS.LOG_CAPACITY] = 1
    context.session._on_bytes(b"[I] [boot] heartbeat ok\r\n")
    qtbot.waitUntil(lambda: window.log_count_label.text() == "日志 3 条", timeout=1000)
    bootstrap._apply_settings(window, context, context.analysis_service)
    assert context.anomaly_service.clusters()[0].evidence_sequences == ()

    # 4) 切换 Preset 时异常控制器与面板锁定联动清零
    bootstrap._switch_preset(window, context, "hi3861-timestamped")
    assert window.alert_badge_btn.text() == "告警 0"
    assert window.anomaly_panel.clusters() == []

    # 5) 导入日志必须将 coalesced 增量同步送入 AnomalyController
    sample_log = tmp_path / "import.log"
    sample_log.write_text("[1.000] [E] [uart] rx overflow cnt=4\n", encoding="utf-8")
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(sample_log), ""))
    bootstrap._import_logs(window, context)
    assert len(window.anomaly_panel.clusters()) == 1
    assert window.alert_badge_btn.text() == "告警 1"

    # 6) 导出 Markdown 与 JSON 诊断报告（含最近一次完成的分析结果摘要）
    context.analysis_service._latest_result = AnalysisResult(
        state=AnalysisState.DONE,
        content="确认为 UART RX FIFO 溢出导致丢包。",
    )
    md_path = bootstrap.export_report(context, tmp_path / "diag.md", fmt=ReportFormat.MARKDOWN)
    json_path = bootstrap.export_report(context, tmp_path / "diag.json", fmt=ReportFormat.JSON)
    md_text = md_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "hi3861-timestamped" in md_text
    assert "确认为 UART RX FIFO 溢出导致丢包。" in md_text
    assert payload["preset_id"] == "hi3861-timestamped"
    assert len(payload["rule_facts"]["clusters"]) == 1
    assert payload["llm_inference"]["content"] == "确认为 UART RX FIFO 溢出导致丢包。"

    window.close()


def test_bootstrap_analyze_cluster_resets_existing_chat_and_usage(
    qapp, fake_settings, monkeypatch, qtbot
) -> None:
    """已有 LLM 会话及用量后点击「LLM」分析异常簇，旧卡片与状态栏用量必须同步清零并渲染新首轮。"""

    import json

    from serial_log_analyzer.core.models.analysis import (
        AnalysisMessage,
        AnalysisResult,
        AnalysisState,
        MessageRole,
        TokenUsage,
    )
    from serial_log_analyzer.ui.controllers.device_controller import DeviceController

    class _StubToken:
        def cancel(self) -> None:
            pass

    class _FakeHttpTransport:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def send(self, request, on_chunk, on_done, on_error):
            self.requests.append(request)
            on_chunk(
                json.dumps(
                    {
                        "choices": [{"message": {"content": "聚类根因结论"}}],
                    }
                ).encode("utf-8")
            )
            on_done()
            return _StubToken()

    class _FakeCredentials:
        def resolve(self, _ref) -> str:
            return "sk-test"

    def _fast_device(session):
        return DeviceController(session, batch_interval_ms=20, command_timeout_ms=50)

    monkeypatch.setattr(bootstrap, "DeviceController", _fast_device)
    context = bootstrap.build_application(["-platform", "offscreen"])
    context.http_transport = _FakeHttpTransport()
    context.credentials = _FakeCredentials()
    context.profile = type(context.profile)(**{**context.profile.__dict__, "stream": False})

    window = bootstrap.build_window(context)

    # 先模拟一轮已有完整对话及状态栏 Token 摘要
    old_user = AnalysisMessage(MessageRole.USER, "旧请求正文", "旧会话提问")
    old_assistant = AnalysisMessage(MessageRole.ASSISTANT, "旧会话回答")
    context.analysis_service._conversation.extend([old_user, old_assistant])
    old_result = AnalysisResult(
        state=AnalysisState.DONE,
        conversation=[old_user, old_assistant],
        content="旧会话回答",
        usage=TokenUsage(input_tokens=120, output_tokens=30, total_tokens=150),
    )
    window.analysis_panel.set_result(old_result)
    window.set_usage_summary(120, 30, 150)
    assert [card.body_text() for card in window.analysis_panel.chat._cards] == [
        "旧会话提问",
        "旧会话回答",
    ]
    assert window.usage_status_label.isHidden() is False

    # 接入含异常的日志，随后通过异常面板触发一键「LLM」聚类分析
    context.session._on_bytes(b"[E] [mem] malloc failed size=64\r\n")
    qtbot.waitUntil(lambda: len(window.anomaly_panel.clusters()) == 1, timeout=1000)
    cluster = window.anomaly_panel.clusters()[0]
    window.anomaly_panel.analyze_requested.emit(cluster)

    assert len(context.http_transport.requests) == 1
    assert window.usage_status_label.isHidden() is True
    cards = [card.body_text() for card in window.analysis_panel.chat._cards]
    assert len(cards) == 2
    assert "旧会话提问" not in cards[0] and "旧会话回答" not in cards[1]
    assert "malloc failed" in cards[0]
    assert cards[1] == "聚类根因结论"

    window.close()
