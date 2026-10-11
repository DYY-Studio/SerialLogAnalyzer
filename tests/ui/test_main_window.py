"""界面测试：批量刷新、过滤、面板状态与菜单意图（使用 pytest-qt，离屏运行）。"""

from __future__ import annotations

from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.models.analysis import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisState,
    ContextSelector,
    TokenUsage,
)
from serial_log_analyzer.core.models.device import FlowControl, Parity, StopBits
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.ui.main_window import MainWindow
from serial_log_analyzer.ui.models.log_table_model import LogTableModel
from serial_log_analyzer.ui.widgets.analysis_panel import AnalysisPanel
from serial_log_analyzer.ui.widgets.log_view import LogView
from serial_log_analyzer.ui.widgets.serial_toolbar import SerialToolBar


def _entry(sequence: int, level: LogLevel = LogLevel.INFO, module: str = "wifi",
           message: str = "connected") -> LogEntry:
    return LogEntry(
        sequence=sequence,
        received_at=1700000000.0 + sequence,
        level=level,
        message=message,
        raw=f"[{level.name[0]}] [{module}] {message}",
        module=module,
    )


def _build_window(qtbot) -> MainWindow:
    window = MainWindow(LogView(LogTableModel()), AnalysisPanel(), SerialToolBar())
    qtbot.addWidget(window)
    return window


def test_append_update_inserts_updates_and_drops(qtbot) -> None:
    window = _build_window(qtbot)
    view = window.log_view

    view.append_update(PipelineUpdate(added=(_entry(0), _entry(1, LogLevel.ERROR, message="boom"))))
    assert view.table_view.model().rowCount() == 2

    view.append_update(PipelineUpdate(updated=(_entry(0, message="connected+"),)))
    assert view._model.entry_at(0).message == "connected+"

    view.append_update(PipelineUpdate(dropped_sequences=(0,)))
    assert view.table_view.model().rowCount() == 1
    assert view._model.entry_at(0).sequence == 1


def test_filters_narrow_rows_and_emit_selection(qtbot) -> None:
    window = _build_window(qtbot)
    view = window.log_view
    view.append_update(
        PipelineUpdate(added=(_entry(0), _entry(1, LogLevel.ERROR, message="boom")))
    )
    selected: list[list[int]] = []
    view.selection_changed.connect(selected.append)

    view._level_boxes[LogLevel.INFO].setChecked(False)
    assert view.table_view.model().rowCount() == 1

    view.text_filter.setText("boom")
    assert view.table_view.model().rowCount() == 1

    view.text_filter.setText("nope")
    assert view.table_view.model().rowCount() == 0

    view.text_filter.clear()
    view._level_boxes[LogLevel.INFO].setChecked(True)
    assert view.table_view.model().rowCount() == 2
    view.table_view.selectRow(0)
    assert selected and selected[-1] == [0]


def test_analysis_panel_reflects_state_and_request(qtbot) -> None:
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.set_goals([])
    captured: list[object] = []
    panel.analyze_requested.connect(captured.append)

    panel.set_state(AnalysisState.STREAMING)
    assert panel.analyze_btn.isEnabled() is False
    assert panel.stop_btn.isEnabled() is True

    panel.set_result(
        AnalysisResult(content="结论", usage=TokenUsage(3, 4, 7), state=AnalysisState.DONE)
    )
    assert panel.result_view.toPlainText() == "结论"
    assert "3" in panel.usage_label.text() and "7" in panel.usage_label.text()

    panel.set_state(AnalysisState.DONE)
    panel.input_edit.setText("看看这条")
    panel.analyze_btn.click()

    request, selector = captured[-1]
    assert isinstance(request, AnalysisRequest) and request.user_input == "看看这条"
    assert selector is ContextSelector.SELECTED


def test_menu_actions_emit_intent_signals(qtbot) -> None:
    window = _build_window(qtbot)
    seen: list[str] = []
    window.settings_requested.connect(lambda: seen.append("settings"))
    window.provider_requested.connect(lambda: seen.append("provider"))
    window.credential_requested.connect(lambda: seen.append("credential"))

    actions = window.menuBar().actions()[0].menu().actions()
    assert [action.text() for action in actions] == [
        "设置…",
        "模型服务…",
        "凭据…",
        "切换日志 Preset…",
    ]
    for action in actions[:3]:
        action.trigger()

    assert seen == ["settings", "provider", "credential"]


def test_toolbar_emits_config_and_command(qtbot) -> None:
    toolbar = SerialToolBar()
    qtbot.addWidget(toolbar)
    configs: list[object] = []
    commands: list[str] = []
    toolbar.connect_requested.connect(configs.append)
    toolbar.command_submitted.connect(commands.append)

    toolbar.set_ports([])
    toolbar.port_combo.addItem("COM3 - USB Serial", "COM3")
    toolbar.baud_combo.setCurrentText("115200")
    toolbar.connect_btn.click()
    toolbar.command_edit.setText("PING")
    toolbar.send_btn.click()

    assert configs[0].port == "COM3" and configs[0].baudrate == 115200
    assert commands == ["PING"]


def test_panel_profile_combo_emits_change(qtbot) -> None:
    class _Profile:
        def __init__(self, profile_id: str) -> None:
            self.profile_id = profile_id
            self.model = f"{profile_id}-model"

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    seen: list[str] = []
    panel.profile_changed.connect(seen.append)

    panel.set_profiles([_Profile("deepseek"), _Profile("internlm")], "internlm")
    assert panel.current_profile() == "internlm"

    panel.set_current_profile("deepseek")
    assert seen == []  # 程序化切换不触发信号

    panel.profile_combo.setCurrentIndex(1)
    assert seen == ["internlm"]


def test_log_view_autoscroll_switch_emits(qtbot) -> None:
    view = LogView(LogTableModel())
    qtbot.addWidget(view)
    seen: list[bool] = []
    view.autoscroll_toggled.connect(seen.append)

    view.autoscroll_box.setChecked(False)

    assert seen == [False]
    view.set_autoscroll(True)
    assert view.autoscroll_box.isChecked() is True and seen == [False]


def test_toolbar_serial_settings_feed_current_config(qtbot) -> None:
    toolbar = SerialToolBar()
    qtbot.addWidget(toolbar)
    requested: list[bool] = []
    toolbar.serial_settings_requested.connect(lambda: requested.append(True))
    toolbar.port_combo.addItem("COM4", "COM4")

    toolbar.settings_btn.click()
    assert requested == [True]

    toolbar.apply_serial_settings(
        {
            "baudrate": "9600",
            "data_bits": 7,
            "parity": Parity.EVEN,
            "stop_bits": StopBits.TWO,
            "flow_control": FlowControl.HARDWARE,
        }
    )
    config = toolbar.current_config()

    assert (config.baudrate, config.data_bits) == (9600, 7)
    assert config.parity is Parity.EVEN
    assert config.stop_bits is StopBits.TWO
    assert config.flow_control is FlowControl.HARDWARE
