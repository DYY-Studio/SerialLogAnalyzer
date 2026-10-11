"""界面测试：批量刷新、过滤、面板状态与菜单意图（使用 pytest-qt，离屏运行）。"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDockWidget

from serial_log_analyzer.core.device.command import CommandReply
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.models.analysis import (
    AnalysisMessage,
    AnalysisRequest,
    AnalysisResult,
    AnalysisState,
    ContextSelector,
    MessageRole,
    TokenUsage,
)
from serial_log_analyzer.core.models.device import FlowControl, Parity, StopBits
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.ui.main_window import MainWindow
from serial_log_analyzer.ui.models.log_table_model import LogTableModel
from serial_log_analyzer.ui.widgets.analysis_panel import AnalysisPanel
from serial_log_analyzer.ui.widgets.app_log_panel import AppLogPanel
from serial_log_analyzer.ui.widgets.command_panel import CommandPanel
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
    window = MainWindow(
        LogView(LogTableModel()),
        AnalysisPanel(),
        SerialToolBar(),
        CommandPanel(),
        AppLogPanel(lambda: [], ""),
    )
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


def test_level_filter_covers_every_level(qtbot) -> None:
    window = _build_window(qtbot)
    view = window.log_view
    view.append_update(
        PipelineUpdate(
            added=(
                _entry(0, LogLevel.VERBOSE),
                _entry(1, LogLevel.UNKNOWN, message="???"),
            )
        )
    )
    assert set(view._level_boxes) == set(LogLevel)
    assert view.table_view.model().rowCount() == 2

    # 只留错误级：详细与未知也被过滤掉，且它们都有勾选框可以勾回来
    for level, box in view._level_boxes.items():
        box.setChecked(level is LogLevel.ERROR)
    assert view.table_view.model().rowCount() == 0

    for box in view._level_boxes.values():
        box.setChecked(True)
    assert view.table_view.model().rowCount() == 2


def test_analysis_panel_first_turn_then_follow_up(qtbot) -> None:
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.set_goals([])
    requests: list[object] = []
    follow_ups: list[str] = []
    panel.analyze_requested.connect(requests.append)
    panel.follow_up_requested.connect(follow_ups.append)

    panel.message_edit.setPlainText("看看这条")
    panel.send_btn.click()

    request, selector = requests[-1]
    assert isinstance(request, AnalysisRequest) and request.user_input == "看看这条"
    assert selector is ContextSelector.SELECTED
    assert panel.message_edit.toPlainText() == ""

    panel.set_state(AnalysisState.STREAMING)
    assert panel.send_btn.isEnabled() is False and panel.stop_btn.isEnabled() is True

    panel.set_result(
        AnalysisResult(
            content="结论",
            usage=TokenUsage(3, 4, 7, 2),
            state=AnalysisState.DONE,
            conversation=[
                AnalysisMessage(MessageRole.USER, "看看这条"),
                AnalysisMessage(MessageRole.ASSISTANT, "结论"),
            ],
        )
    )
    panel.set_state(AnalysisState.DONE)
    assert "结论" in panel.chat.plain_text()
    assert "3" in panel.usage_label.text() and "7" in panel.usage_label.text()
    assert "缓存 2" in panel.usage_label.text()
    assert panel.turns_label.text() == "当前会话 1 轮"
    # 会话已开始：目标与上下文不再生效，发送走追问
    assert panel.goal_combo.isEnabled() is False and panel.context_combo.isEnabled() is False

    panel.message_edit.setPlainText("那内存呢")
    panel.send_btn.click()
    panel.send_btn.click()  # 空文本不再发
    assert follow_ups == ["那内存呢"]

    panel.copy_btn.click()
    assert "结论" in QGuiApplication.clipboard().text()

    panel.new_session_btn.click()
    assert panel.context_combo.isEnabled() is True and panel.goal_combo.isEnabled() is True
    assert panel.turns_label.text() == ""


def test_restore_layout_reapplies_bottom_right_corner(qtbot) -> None:
    """恢复旧布局不能让右下角归属回退（否则分析面板不再贯通上下）。"""

    from PySide6.QtCore import Qt

    window = _build_window(qtbot)
    state = window.saveState()
    # 模拟旧版本存下来的状态：右下角归底部停靠区
    window.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.BottomDockWidgetArea)

    window.restore_layout(state)

    assert window.corner(Qt.Corner.BottomRightCorner) is Qt.DockWidgetArea.RightDockWidgetArea


def test_menu_actions_emit_intent_signals(qtbot) -> None:
    window = _build_window(qtbot)
    seen: list[str] = []
    window.export_requested.connect(lambda: seen.append("export"))
    window.import_requested.connect(lambda: seen.append("import"))
    window.clear_requested.connect(lambda: seen.append("clear"))
    window.settings_requested.connect(lambda: seen.append("settings"))
    window.provider_requested.connect(lambda: seen.append("provider"))
    window.credential_requested.connect(lambda: seen.append("credential"))

    menus = window.menuBar().actions()
    assert [menu.text() for menu in menus] == ["文件", "配置", "视图"]
    file_actions = [item for item in menus[0].menu().actions() if not item.isSeparator()]
    config_actions = menus[1].menu().actions()
    assert [action.text() for action in file_actions] == ["导出日志…", "导入日志…", "清空日志"]
    assert [action.text() for action in config_actions] == [
        "设置…",
        "模型服务…",
        "凭据…",
        "切换日志 Preset…",
    ]
    # 「视图」里必须能开关停靠面板，否则关掉就找不回来
    assert [action.text() for action in menus[2].menu().actions()] == ["LLM 分析", "命令", "应用日志"]
    assert window.analysis_dock.widget() is window.analysis_panel
    assert window.command_dock.widget() is window.command_panel
    assert window.app_log_dock.widget() is window.app_log_panel
    # 命令与应用日志共用底部区域，按标签页切换
    assert window.tabifiedDockWidgets(window.command_dock) == [window.app_log_dock]
    for dock in (window.analysis_dock, window.command_dock, window.app_log_dock):
        assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetMovable

    for action in (*file_actions, *config_actions[:3]):
        action.trigger()

    assert seen == ["export", "import", "clear", "settings", "provider", "credential"]


def test_toolbar_emits_config(qtbot) -> None:
    toolbar = SerialToolBar()
    qtbot.addWidget(toolbar)
    configs: list[object] = []
    toolbar.connect_requested.connect(configs.append)

    toolbar.set_ports([])
    toolbar.port_combo.addItem("COM3 - USB Serial", "COM3")
    toolbar.baud_combo.setCurrentText("115200")
    toolbar.connect_btn.click()

    assert configs[0].port == "COM3" and configs[0].baudrate == 115200


def test_command_panel_echoes_command_and_appends_reply(qtbot) -> None:
    panel = CommandPanel()
    qtbot.addWidget(panel)
    sent: list[str] = []
    panel.command_submitted.connect(sent.append)

    panel.command_edit.setText("PING")
    panel.send_btn.click()
    assert sent == ["PING"]
    assert panel.command_edit.text() == ""

    panel.append_reply(CommandReply(text="PONG", ok=True))
    panel.append_reply(CommandReply(text="rx overflow", ok=False, code=7))
    assert panel.reply_view.toPlainText().splitlines() == [
        "→ PING",
        "← PONG",
        "← 失败 [7] rx overflow",
    ]

    panel.send_btn.click()  # 空命令不发
    assert sent == ["PING"]


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

    toolbar.baud_combo.setCurrentText("9600")
    toolbar.apply_serial_settings(
        {
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


def test_invalid_baudrate_reports_and_skips_connect(qtbot) -> None:
    toolbar = SerialToolBar()
    qtbot.addWidget(toolbar)
    toolbar.port_combo.addItem("COM4", "COM4")
    configs: list[object] = []
    errors: list[str] = []
    toolbar.connect_requested.connect(configs.append)
    toolbar.error_occurred.connect(errors.append)

    toolbar.baud_combo.setCurrentText("fast")
    toolbar.connect_btn.click()
    toolbar.baud_combo.setCurrentText("0")
    toolbar.connect_btn.click()

    assert configs == []
    assert len(errors) == 2 and all("波特率" in message for message in errors)
