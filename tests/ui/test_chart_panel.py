"""数据图表面板测试（使用 pytest-qt，离屏运行）：互斥字段切换、滑动时间窗、Hover 读数与主题重绘。"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QToolButton

from serial_log_analyzer.core.errors import ConfigError
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


def test_chart_panel_single_select_auto_switch_and_empty_states(qtbot) -> None:
    """互斥标签胶囊切换单图、无采样字段自动跳转、用户主动选择保持与空状态提示。"""

    panel = ChartPanel(preset_fields=("led", "temperature", "humidity"))
    qtbot.addWidget(panel)

    assert panel._content_stack.currentWidget() is panel._empty_page
    assert "暂无遥测数值采样" in panel._empty_title.text()
    assert panel.field_names() == ("led", "temperature", "humidity")
    assert panel.current_field() == "led"

    # 首批日志仅含 temperature / humidity（led 无采样）-> 自动切换到第一个有采样的字段 temperature
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

    assert panel._content_stack.currentWidget() is panel._plot_widget
    assert panel.field_names() == ("led", "temperature", "humidity", "voltage")
    assert panel.current_field() == "temperature"

    led_chip = panel.findChild(QToolButton, "chart-field-led")
    temp_chip = panel.findChild(QToolButton, "chart-field-temperature")
    hum_chip = panel.findChild(QToolButton, "chart-field-humidity")
    volt_chip = panel.findChild(QToolButton, "chart-field-voltage")
    assert all(chip is not None for chip in (led_chip, temp_chip, hum_chip, volt_chip))
    assert temp_chip.isChecked() is True
    assert hum_chip.isChecked() is False

    # 点击 humidity 芯片 -> 互斥单选切换
    hum_chip.click()
    assert panel.current_field() == "humidity"
    assert hum_chip.isChecked() is True
    assert temp_chip.isChecked() is False
    assert panel._plot_item.getAxis("left").labelText == "humidity"

    # 新一批采样到达仍包含 humidity -> 保持用户主动选择
    panel.append_update(
        PipelineUpdate(added=(_sensor_entry(2, 104.0, {"temperature": "28.0", "humidity": "45.0"}),))
    )
    assert panel.current_field() == "humidity"

    # 切到暂无采样的字段 led -> 切换回清晰字段空状态提示；再次点击已选中芯片不取消选中
    led_chip.click()
    assert panel.current_field() == "led"
    assert panel._content_stack.currentWidget() is panel._empty_page
    assert "字段 led 暂无数值采样" in panel._empty_title.text()
    led_chip.click()
    assert led_chip.isChecked() is True

    # 未登记字段忽略
    panel.select_field("nonexistent")
    assert panel.current_field() == "led"

    # 切回有效字段恢复图表
    panel.select_field("voltage")
    assert panel.current_field() == "voltage"
    assert panel._content_stack.currentWidget() is panel._plot_widget


def test_chart_panel_sliding_window_y_adapt_and_symbol_threshold(qtbot) -> None:
    """5 档时间窗口、非压缩生长与滑动推进、窗内 Y 轴自适应、常数留白及 80 点符号阈值。"""

    panel = ChartPanel(preset_fields=("temperature", "led"))
    qtbot.addWidget(panel)

    options = [
        (panel.window_combo.itemText(i), panel.window_combo.itemData(i))
        for i in range(panel.window_combo.count())
    ]
    assert options == [
        ("15 秒", 15.0),
        ("30 秒", 30.0),
        ("1 分钟", 60.0),
        ("5 分钟", 300.0),
        ("全部", None),
    ]
    assert panel.window_seconds() == 30.0
    assert panel.auto_follow_btn.isChecked() is True

    # 1) 跨度 0..10s（<= 30s）：X 固定为 [0, 30] 向右生长，首点异常尖峰 999 在窗内
    panel.append_update(
        PipelineUpdate(
            added=(
                _sensor_entry(0, 100.0, {"temperature": "999.0", "led": "1"}),
                _sensor_entry(1, 110.0, {"temperature": "25.0", "led": "1"}),
            )
        )
    )
    panel.select_field("temperature")
    x_range, _y_range = panel._plot_item.viewRange()
    assert x_range == pytest.approx([0.0, 30.0])

    # 2) 推进到 45s（每隔 0.5s 共 91 个点，> 80 总点，但 30s 窗内 61 点 <= 80）：
    #    X 滑动到 [15.0, 45.6]，Y 轴仅按窗内 [15..45] 极值 [20.0, 30.0] 留 10% 边距 -> [19.0, 31.0]
    more = tuple(
        _sensor_entry(
            idx + 2,
            100.0 + 15.0 + idx * 0.5,
            {
                "temperature": f"{20.0 if idx % 2 == 0 else 30.0}",
                "led": "1",
            },
        )
        for idx in range(61)  # 15.0s .. 45.0s
    )
    panel.append_update(PipelineUpdate(added=more))
    # 补充 10..15s 之间点使总数超过 80
    mid = tuple(
        _sensor_entry(idx + 100, 100.0 + 10.5 + idx * 0.2, {"temperature": "25.0", "led": "1"})
        for idx in range(22)
    )
    panel.append_update(PipelineUpdate(added=mid))

    x_range, y_range = panel._plot_item.viewRange()
    assert x_range == pytest.approx([15.0, 45.6])
    assert y_range == pytest.approx([19.0, 31.0])
    assert panel._curve.opts.get("symbol") == "o"  # 窗内 <= 80 点保留圆点
    assert "窗内最小 20 / 最大 30" in panel.readout_label.text()

    # 3) 常数序列 led=1 在 Y 轴给 [v-1, v+1] = [0, 2]
    panel.select_field("led")
    _x_led, y_led = panel._plot_item.viewRange()
    assert y_led == pytest.approx([0.0, 2.0])

    # 4) 切回 temperature 并选「全部」：总点数 > 80 隐藏圆点，显示全量范围（含 999 尖峰）
    panel.select_field("temperature")
    panel.auto_follow_btn.setChecked(False)
    panel.set_window_seconds(None)
    assert panel.window_seconds() is None
    assert panel.auto_follow_btn.isChecked() is True  # 切换窗口档位主动重开自动跟随
    assert panel._curve.opts.get("symbol") is None
    x_all, y_all = panel._plot_item.viewRange()
    assert x_all[0] < 0.0 and x_all[1] > 45.0
    assert y_all[1] > 999.0
    assert "全量最小 20 / 最大 999" in panel.readout_label.text()

    # 5) 切换 15 秒窗口并验证非法窗口抛出 ConfigError
    panel.window_combo.setCurrentIndex(0)
    assert panel.window_seconds() == 15.0
    x_15, _ = panel._plot_item.viewRange()
    assert x_15 == pytest.approx([30.0, 45.3])

    with pytest.raises(ConfigError):
        panel.set_window_seconds(42.0)


def test_chart_panel_hover_manual_zoom_reset_clear_eviction_and_themes(qtbot) -> None:
    """单参考线 Hover 读数、手动缩放取消自动跟随、重置缩放全量范围、清空淘汰与明暗主题。"""

    panel = ChartPanel(preset_fields=("temperature", "humidity"), tokens=LIGHT_TOKENS)
    qtbot.addWidget(panel)
    panel.resize(700, 420)
    panel.show()

    panel.append_update(
        PipelineUpdate(
            added=(
                _sensor_entry(0, 10.0, {"temperature": "20.0", "humidity": "50.0"}),
                _sensor_entry(1, 20.0, {"temperature": "25.0", "humidity": "55.0"}),
                _sensor_entry(2, 50.0, {"temperature": "30.0", "humidity": "60.0"}),
            )
        )
    )
    assert panel.current_field() == "temperature"
    assert panel.readout_label.text() == "temperature · 最新 t=40.00s | 当前 30（窗内最小 25 / 最大 30）"

    # Hover 定位到 t=0.2（最邻近 t=0.0 样本）
    panel.hover_at_time(0.2)
    assert panel._crosshair.isVisible() is True
    assert panel._crosshair.value() == 0.2
    assert panel.readout_label.text() == "指针 t=0.20s | temperature=20"

    # 鼠标移动到绘图区，验证 sigMouseMoved 联动
    plot_center = panel._plot_item.sceneBoundingRect().center()
    panel._plot_widget.scene().sigMouseMoved.emit(plot_center)
    assert panel.readout_label.text().startswith("指针 t=")

    panel.clear_hover()
    assert panel._crosshair.isVisible() is False
    assert panel.readout_label.text().startswith("temperature · 最新 t=40.00s")

    # 手动缩放信号触发自动取消勾选「自动跟随」，程序化范围应用不误触发
    assert panel.auto_follow_btn.isChecked() is True
    panel._plot_item.vb.sigRangeChangedManually.emit([True, True])
    assert panel.auto_follow_btn.isChecked() is False

    # 重置缩放显示当前字段全量采样范围（涵盖 t=0..40）
    panel.reset_zoom_btn.click()
    x_reset, y_reset = panel._plot_item.viewRange()
    assert x_reset[0] < 0.0 and x_reset[1] > 40.0
    assert y_reset == pytest.approx([19.0, 31.0])
    assert "全量最小 20 / 最大 30" in panel.readout_label.text()

    # 重新开启自动跟随恢复 30s 窗口
    panel.auto_follow_btn.click()
    assert panel.auto_follow_btn.isChecked() is True
    x_follow, _ = panel._plot_item.viewRange()
    assert x_follow == pytest.approx([10.0, 40.6])

    # 明暗主题切换
    panel.set_theme_tokens(DARK_TOKENS)
    assert panel._plot_widget.backgroundBrush().color().name().lower() == DARK_TOKENS.bg_surface.lower()
    panel.set_theme_tokens(LIGHT_TOKENS)
    assert panel._plot_widget.backgroundBrush().color().name().lower() == LIGHT_TOKENS.bg_surface.lower()

    # 淘汰部分序号，仅保留 seq=2
    panel.append_update(PipelineUpdate(dropped_sequences=(0, 1)))
    assert panel.sample_count("temperature") == 1
    assert panel._content_stack.currentWidget() is panel._plot_widget

    # 清空图表仅清采样保留字段配置
    panel.clear()
    assert panel.sample_count("temperature") == 0
    assert panel.field_names() == ("temperature", "humidity")
    assert panel._content_stack.currentWidget() is panel._empty_page

    # 切换 Preset 字段集 -> 清空数据并默认选中第一个有效字段
    panel.set_preset_fields(("voltage", "current"))
    assert panel.field_names() == ("voltage", "current")
    assert panel.current_field() == "voltage"
    assert panel.findChild(QToolButton, "chart-field-temperature") is None
    assert panel.findChild(QToolButton, "chart-field-voltage") is not None

    # 切到空字段 Preset
    panel.set_preset_fields(())
    assert panel.field_names() == ()
    assert panel.current_field() is None
