"""界面测试：批量刷新、过滤、面板状态与菜单意图（使用 pytest-qt，离屏运行）。"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDockWidget

from serial_log_analyzer.core.device.command import CommandReply
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.logs.preset import PresetCommand, PresetCommandMode
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
from serial_log_analyzer.core.prompts.loader import PromptGoal
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
    assert panel._action_stack.currentWidget() is panel.stop_btn

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
    assert panel._action_stack.currentWidget() is panel.send_btn
    assert panel._scope_widget.isHidden() is True
    assert panel._scope_summary.isHidden() is False
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
    assert panel._scope_widget.isHidden() is False
    assert panel._scope_summary.isHidden() is True
    assert panel.turns_label.text() == ""


def test_analysis_panel_none_goal_sends_no_template(qtbot) -> None:
    """目标下拉首项「无」：goal_id 为空，不会套目标模板（对照测试用）。"""

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.set_goals([PromptGoal("explain-logs", "解释日志", "模板：$context")])
    requests: list[object] = []
    panel.analyze_requested.connect(requests.append)

    assert panel.goal_combo.itemText(0) == "无" and panel.goal_combo.itemData(0) == ""
    assert panel.goal_combo.itemData(1) == "explain-logs"
    assert panel.goal_combo.currentData() == "explain-logs"  # 缺省仍是第一个真实目标

    panel.goal_combo.setCurrentIndex(0)  # 显式选「无」
    panel.message_edit.setPlainText("ping")
    panel.send_btn.click()

    request, _selector = requests[-1]
    assert request.goal_id == ""


def test_docks_start_in_the_designed_layout(qtbot) -> None:
    """没有存档时按设计好的默认排布：右下角归右侧、三个面板都可见。"""

    from PySide6.QtCore import Qt

    window = _build_window(qtbot)
    window.show()

    # 右下角归右侧 => 分析面板贯通上下、命令/应用日志只占左下
    assert window.corner(Qt.Corner.BottomRightCorner) is Qt.DockWidgetArea.RightDockWidgetArea
    assert window.analysis_dock.isHidden() is False
    assert window.command_dock.isHidden() is False
    assert window.app_log_dock.isHidden() is False


def test_layout_is_restored_only_when_the_dock_set_matches(qtbot) -> None:
    """面板集合一致才恢复存档；变过就丢弃，免得新面板被 Qt 藏起来。"""

    from PySide6.QtCore import Qt

    from serial_log_analyzer import bootstrap
    from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS

    window = _build_window(qtbot)
    window.resize(1200, 800)
    window.show()

    # 存档：分析面板停靠在左侧
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, window.analysis_dock)
    state = window.saveState()
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window.analysis_dock)

    bootstrap._restore_layout(
        window,
        {SETTINGS_KEYS.WINDOW_STATE: state, SETTINGS_KEYS.WINDOW_DOCKS: window.dock_names()},
    )
    assert window.dockWidgetArea(window.analysis_dock) is Qt.DockWidgetArea.LeftDockWidgetArea
    # 恢复后要重新声明角落归属，否则分析面板不再贯通上下
    assert window.corner(Qt.Corner.BottomRightCorner) is Qt.DockWidgetArea.RightDockWidgetArea

    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window.analysis_dock)
    bootstrap._restore_layout(
        window,
        {
            SETTINGS_KEYS.WINDOW_STATE: state,
            SETTINGS_KEYS.WINDOW_DOCKS: ["analysis-dock", "command-dock"],  # 少一个面板
        },
    )
    assert window.dockWidgetArea(window.analysis_dock) is Qt.DockWidgetArea.RightDockWidgetArea


def test_menu_actions_emit_intent_signals(qtbot) -> None:
    window = _build_window(qtbot)
    seen: list[str] = []
    window.export_requested.connect(lambda: seen.append("export"))
    window.export_report_requested.connect(lambda: seen.append("export_report"))
    window.import_requested.connect(lambda: seen.append("import"))
    window.clear_requested.connect(lambda: seen.append("clear"))
    window.settings_requested.connect(lambda: seen.append("settings"))
    window.provider_requested.connect(lambda: seen.append("provider"))

    menus = window.menuBar().actions()
    assert [menu.text() for menu in menus] == ["文件", "配置", "视图"]
    file_actions = [item for item in menus[0].menu().actions() if not item.isSeparator()]
    config_actions = menus[1].menu().actions()
    assert [action.text() for action in file_actions] == [
        "导出日志…",
        "导出诊断报告…",
        "导入日志…",
        "清空日志",
    ]
    assert [action.text() for action in config_actions] == [
        "设置…",
        "模型服务…",
        "切换日志 Preset…",
    ]
    # 「视图」里必须能开关停靠面板，否则关掉就找不回来
    assert [action.text() for action in menus[2].menu().actions()] == [
        "LLM 分析",
        "命令",
        "应用日志",
        "异常与告警",
    ]
    assert window.analysis_dock.widget() is window.analysis_panel
    assert window.command_dock.widget() is window.command_panel
    assert window.app_log_dock.widget() is window.app_log_panel
    assert window.anomaly_dock.widget() is window.anomaly_panel
    # 命令、应用日志与异常面板共用底部区域，按标签页切换
    assert set(window.tabifiedDockWidgets(window.command_dock)) == {
        window.app_log_dock,
        window.anomaly_dock,
    }
    for dock in (
        window.analysis_dock,
        window.command_dock,
        window.app_log_dock,
        window.anomaly_dock,
    ):
        assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetMovable

    for action in (*file_actions, *config_actions[:2]):
        action.trigger()

    assert seen == ["export", "export_report", "import", "clear", "settings", "provider"]


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
    panel.append_timeout("VERSION")
    assert panel.reply_view.toPlainText().splitlines() == [
        "→ PING",
        "← PONG",
        "← 失败 [7] rx overflow",
        "⏱ 超时未收到响应：VERSION",
    ]

    panel.send_btn.click()  # 空命令不发
    assert sent == ["PING"]

    # 快捷命令芯片：PING 直接发送，TEST 仅预填前缀且不直接提交
    from PySide6.QtWidgets import QToolButton

    panel.findChild(QToolButton, "cmd-chip-ping").click()
    assert sent == ["PING", "PING"]

    panel.findChild(QToolButton, "cmd-chip-test").click()
    assert panel.command_edit.text() == "TEST "
    assert sent == ["PING", "PING"]

    panel.findChild(QToolButton, "cmd-clear").click()
    assert panel.reply_view.toPlainText() == ""


def test_command_panel_set_commands_replaces_chips_and_hides_when_empty(qtbot) -> None:
    """运行期替换快捷命令即时更新按钮、重名 slug、提示文案，空列表时隐藏快捷栏。"""

    from PySide6.QtWidgets import QToolButton

    panel = CommandPanel()
    qtbot.addWidget(panel)
    sent: list[str] = []
    panel.command_submitted.connect(sent.append)

    assert panel.findChild(QToolButton, "cmd-chip-ping") is not None

    panel.set_commands(
        [
            PresetCommand(label="AT", command="AT", tooltip="检查模组响应"),
            PresetCommand(label="TEST …", command="TEST ", mode=PresetCommandMode.PREFILL),
            PresetCommand(label="TEST!", command="TEST all"),
        ]
    )

    assert panel.findChild(QToolButton, "cmd-chip-ping") is None
    at_btn = panel.findChild(QToolButton, "cmd-chip-at")
    test_prefill_btn = panel.findChild(QToolButton, "cmd-chip-test")
    test_dup_btn = panel.findChild(QToolButton, "cmd-chip-test-2")
    assert at_btn is not None and at_btn.toolTip() == "检查模组响应"
    assert test_prefill_btn is not None and test_dup_btn is not None
    assert "AT" in panel.command_edit.placeholderText()
    assert panel._quick_label.isHidden() is False
    assert panel._chips_container.isHidden() is False

    at_btn.click()
    test_prefill_btn.click()
    assert panel.command_edit.text() == "TEST "
    test_dup_btn.click()
    assert sent == ["AT", "TEST all"]

    panel.set_commands([])
    assert panel.findChild(QToolButton, "cmd-chip-at") is None
    assert panel._quick_label.isHidden() is True
    assert panel._chips_container.isHidden() is True
    assert panel.clear_btn.isHidden() is False
    assert panel.command_edit.placeholderText() == "输入板端命令"


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


def test_head_drop_uses_incremental_remove_and_preserves_selection(qtbot) -> None:
    """连续头部淘汰应保持后续行选中状态，并支持 O(log N) 序号查行。"""

    window = _build_window(qtbot)
    view = window.log_view
    model = view._model
    view.append_update(PipelineUpdate(added=tuple(_entry(i) for i in range(5))))

    view.table_view.selectRow(3)
    assert [entry.sequence for entry in view.selected_log_entries()] == [3]

    reset_seen: list[bool] = []
    model.modelReset.connect(lambda: reset_seen.append(True))
    removed = model.remove_sequences([0, 1])

    assert removed == 2
    assert reset_seen == []  # 命中连续头部增量移除，未触发整表 reset
    assert [entry.sequence for entry in view.selected_log_entries()] == [3]
    assert model.row_for_sequence(0) is None
    assert model.row_for_sequence(2) == 0
    assert model.row_for_sequence(3) == 1
    assert model.row_for_sequence(99) is None

    # 非连续删除退化为整表 reset，确保视图正确
    assert model.remove_sequences([4]) == 1
    assert reset_seen == [True]
    assert [model.entry_at(row).sequence for row in range(model.rowCount())] == [2, 3]


def test_log_view_empty_state_clear_filters_and_delegate_render(qtbot) -> None:
    """空状态指引切换、一键清空过滤、结构化 Tooltip 与胶囊委托渲染。"""

    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtWidgets import QStyleOptionViewItem

    from serial_log_analyzer.ui.delegates import LogLevelDelegate

    window = _build_window(qtbot)
    view = window.log_view
    assert view._empty_state.isHidden() is False
    assert "暂无" in view._empty_title.text()

    rich_entry = LogEntry(
        sequence=0,
        received_at=1700000000.0,
        level=LogLevel.ERROR,
        message="temperature=29.7",
        raw="[1.234] [E] [sensor] temperature=29.7",
        device_time="1.234",
        module="sensor",
        extra={"temperature": "29.7"},
    )
    view.append_update(PipelineUpdate(added=(rich_entry,)))
    assert view._empty_state.isHidden() is True

    # 过滤为空后提示无匹配项，点重置恢复全部显示
    view.text_filter.setText("missing")
    assert view._empty_state.isHidden() is False
    assert "没有匹配" in view._empty_title.text()
    view.reset_filter_btn.click()
    assert view._empty_state.isHidden() is True
    assert view.table_view.model().rowCount() == 1

    # 结构化 Tooltip 含板上时间、extra 与原文
    tooltip = view._model.data(view._model.index(0, 4), Qt.ItemDataRole.ToolTipRole)
    assert "1.234" in tooltip and "temperature=29.7" in tooltip and rich_entry.raw in tooltip

    # 第 2 列挂载 LogLevelDelegate，可在离屏画布真实渲染胶囊
    delegate = view.table_view.itemDelegateForColumn(2)
    assert isinstance(delegate, LogLevelDelegate)
    pixmap = QPixmap(80, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 80, 28)
    delegate.paint(painter, option, view.table_view.model().index(0, 2))
    painter.end()
    assert not pixmap.toImage().isNull()


def test_main_window_segmented_status_and_dock_title_bars(qtbot) -> None:
    """主窗口 Dock 紧凑标题栏、状态栏分段胶囊与连接/Preset/告警状态同步。"""

    window = _build_window(qtbot)
    assert window.analysis_dock.titleBarWidget() is not None
    assert window.command_dock.titleBarWidget() is not None
    assert window.app_log_dock.titleBarWidget() is not None
    assert window.anomaly_dock.titleBarWidget() is not None

    window.set_connection_status(True, "COM3 · 115200")
    window.set_preset_name("hi3861-timestamped")
    window.set_log_count(42)
    assert "COM3 · 115200" in window.connection_status_label.text()
    assert "hi3861-timestamped" in window.preset_status_label.text()
    assert window.log_count_label.text() == "日志 42 条"

    assert window.alert_badge_btn.text() == "告警 0"
    assert window.alert_badge_btn.property("alertState") == "idle"
    window.set_alert_count(2, severe=True)
    assert window.alert_badge_btn.text() == "告警 2"
    assert window.alert_badge_btn.property("alertState") == "danger"
    window.anomaly_dock.hide()
    window.alert_badge_btn.click()
    assert window.anomaly_dock.isHidden() is False

    window.set_connection_status(False)
    assert "未连接" in window.connection_status_label.text()


def test_log_view_scroll_to_sequence_handles_visible_filtered_and_missing(qtbot) -> None:
    """证据跳转精确选中目标序号；被过滤隐藏或不存在时返回 False 且不误选。"""

    view = LogView(LogTableModel())
    qtbot.addWidget(view)
    view.append_update(
        PipelineUpdate(
            added=(
                _entry(0, LogLevel.INFO, message="boot ok"),
                _entry(1, LogLevel.ERROR, message="malloc failed"),
                _entry(2, LogLevel.INFO, message="heartbeat"),
            )
        )
    )

    assert view.scroll_to_sequence(1) is True
    assert [entry.sequence for entry in view.selected_log_entries()] == [1]

    # 隐藏 ERROR 级别后再次跳转到序号 1，必须明确返回 False 并保持无法定位语义
    view._level_boxes[LogLevel.ERROR].setChecked(False)
    assert view.scroll_to_sequence(1) is False
    assert view.scroll_to_sequence(99) is False

    # 恢复显示后再次跳转正常选中
    view._level_boxes[LogLevel.ERROR].setChecked(True)
    assert view.scroll_to_sequence(1) is True
    assert [entry.sequence for entry in view.selected_log_entries()] == [1]


def test_analysis_panel_export_report_button_emits_signal(qtbot) -> None:
    """分析面板头部「报告」按钮发出 export_report_requested 信号。"""

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    fired: list[bool] = []
    panel.export_report_requested.connect(lambda: fired.append(True))

    panel.export_report_btn.click()
    assert fired == [True]
