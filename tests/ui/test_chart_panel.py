"""数据图表面板测试（使用 pytest-qt，离屏运行）：字段芯片、子图 XLink、Hover 读数与主题重绘。"""

from __future__ import annotations

from PySide6.QtWidgets import QToolButton

from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.ui.theme import DARK_TOKENS, LIGHT_TOKENS
from serial_log_analyzer.ui.widgets.chart_panel import ChartPanel


def _sensor_entry(
    sequence: int,
    received_at: float,
    extra: dict[str, str] | None = None,
) -> LogEntry:
    return LogEntry(
        sequence=sequence,
        received_at=received_at,
        level=LogLevel.INFO,
        message="sensor",
        raw=f"[I] [sensor] seq={sequence}",
        module="sensor",
        extra=extra or {},
    )


def test_chart_panel_empty_state_chips_subplots_and_xlink(qtbot) -> None:
    """多字段独立纵向堆叠子图、Preset 字段优先、X 轴联动与全取消空状态切换。"""

    panel = ChartPanel(preset_fields=("temperature", "humidity"))
    qtbot.addWidget(panel)

    assert panel._content_stack.currentWidget() is panel._empty_page
    assert panel.field_names() == ("temperature", "humidity")
    assert panel.visible_fields() == ("temperature", "humidity")

    # 收到两批采样（包含运行期发现的 voltage 与非数值/NaN 忽略项）
    panel.append_update(
        PipelineUpdate(
            added=(
                _sensor_entry(0, 100.0, {"temperature": "25.0", "humidity": "40.0", "mode": "ok"}),
                _sensor_entry(
                    1,
                    102.0,
                    {"temperature": "27.5", "humidity": "42.0", "voltage": "3.3", "bad": "nan"},
                ),
            )
        )
    )

    assert panel._content_stack.currentWidget() is panel._scroll_area
    assert panel.field_names() == ("temperature", "humidity", "voltage")
    assert panel.sample_count("temperature") == 2
    assert panel.sample_count("voltage") == 1
    assert set(panel._plots) == {"temperature", "humidity", "voltage"}

    first_plot = panel._plots["temperature"]
    second_plot = panel._plots["humidity"]
    third_plot = panel._plots["voltage"]
    assert second_plot.vb.linkedView(0) is first_plot.vb
    assert third_plot.vb.linkedView(0) is first_plot.vb
    assert first_plot.minimumHeight() >= 120
    assert panel._graphics_layout.minimumHeight() >= 3 * 135

    # 取消勾选部分字段 -> 隐藏对应子图；全部取消勾选 -> 切回空状态提示
    temp_chip = panel.findChild(QToolButton, "chart-field-temperature")
    hum_chip = panel.findChild(QToolButton, "chart-field-humidity")
    volt_chip = panel.findChild(QToolButton, "chart-field-voltage")
    assert temp_chip is not None and hum_chip is not None and volt_chip is not None

    hum_chip.click()
    assert panel.visible_fields() == ("temperature", "voltage")
    assert set(panel._plots) == {"temperature", "voltage"}

    temp_chip.click()
    volt_chip.click()
    assert panel.visible_fields() == ()
    assert panel._content_stack.currentWidget() is panel._empty_page
    assert "未勾选" in panel._empty_title.text()

    # 重新勾选后恢复渲染
    temp_chip.click()
    assert panel._content_stack.currentWidget() is panel._scroll_area
    assert panel.visible_fields() == ("temperature",)


def test_chart_panel_hover_readout_clear_eviction_and_themes(qtbot) -> None:
    """十字参考线联动、Hover 读数刷新、清空/淘汰同步、缩放控制与明暗主题切换。"""

    panel = ChartPanel(preset_fields=("temperature", "humidity"), tokens=LIGHT_TOKENS)
    qtbot.addWidget(panel)
    panel.resize(700, 420)
    panel.show()

    panel.append_update(
        PipelineUpdate(
            added=(
                _sensor_entry(0, 10.0, {"temperature": "20.0", "humidity": "50.0"}),
                _sensor_entry(1, 15.0, {"temperature": "30.0", "humidity": "60.0"}),
            )
        )
    )
    assert "最新 t=5.00s" in panel.readout_label.text()
    assert "temperature=30" in panel.readout_label.text()

    # Hover 定位到 t=0.2（最邻近 t=0.0 样本）
    panel.hover_at_time(0.2)
    assert all(line.isVisible() for line in panel._crosshairs.values())
    assert all(line.value() == 0.2 for line in panel._crosshairs.values())
    assert "指针 t=0.20s" in panel.readout_label.text()
    assert "temperature=20" in panel.readout_label.text()
    assert "humidity=50" in panel.readout_label.text()

    # 真实鼠标移动到第一个子图视图中心，验证 sigMouseMoved 联动
    plot_center = panel._plots["temperature"].sceneBoundingRect().center()
    panel._graphics_layout.scene().sigMouseMoved.emit(plot_center)
    assert "指针 t=" in panel.readout_label.text()

    panel.clear_hover()
    assert all(not line.isVisible() for line in panel._crosshairs.values())
    assert "最新 t=5.00s" in panel.readout_label.text()

    # 自动跟随与重置缩放
    panel.auto_follow_btn.click()
    assert panel.auto_follow_btn.isChecked() is False
    panel.reset_zoom_btn.click()
    panel.auto_follow_btn.click()
    assert panel.auto_follow_btn.isChecked() is True

    # 明暗主题切换
    panel.set_theme_tokens(DARK_TOKENS)
    assert panel._graphics_layout.backgroundBrush().color().name().lower() == DARK_TOKENS.bg_surface.lower()
    panel.set_theme_tokens(LIGHT_TOKENS)
    assert panel._graphics_layout.backgroundBrush().color().name().lower() == LIGHT_TOKENS.bg_surface.lower()

    # 淘汰最旧序号，仅保留 seq=1
    panel.append_update(PipelineUpdate(dropped_sequences=(0,)))
    assert panel.sample_count("temperature") == 1
    assert panel._content_stack.currentWidget() is panel._scroll_area

    # 清空图表仅清采样保留字段配置
    panel.clear()
    assert panel.sample_count("temperature") == 0
    assert panel.field_names() == ("temperature", "humidity")
    assert panel._content_stack.currentWidget() is panel._empty_page

    # 切换 Preset 字段集
    panel.set_preset_fields(("voltage",))
    assert panel.field_names() == ("voltage",)
    assert panel.findChild(QToolButton, "chart-field-temperature") is None
    assert panel.findChild(QToolButton, "chart-field-voltage") is not None
