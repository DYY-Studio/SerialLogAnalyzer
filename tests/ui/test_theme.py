"""主题引擎与 SVG 图标测试（pytest-qt，离屏）：Token、QSS、明暗动态重绘与图标渲染。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from serial_log_analyzer.core.models.analysis import (
    AnalysisMessage,
    AnalysisResult,
    AnalysisState,
    MessageRole,
)
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.ui.icons import available_icons, render_icon, render_pixmap
from serial_log_analyzer.ui.models.log_table_model import LogTableModel
from serial_log_analyzer.ui.theme import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    ThemeManager,
    build_qss,
    monospace_font,
    resolve_color_scheme,
)
from serial_log_analyzer.ui.widgets.chat_view import ChatView


def test_theme_manager_switches_schemes_and_updates_models_and_chat(qapp, qtbot) -> None:
    original = resolve_color_scheme(qapp)
    manager = ThemeManager(qapp)
    model = LogTableModel()
    model.add_entries(
        [
            LogEntry(
                sequence=0,
                received_at=1.0,
                level=LogLevel.ERROR,
                message="rx overflow",
                raw="[E] [uart] rx overflow",
                module="uart",
            )
        ]
    )
    chat = ChatView()
    qtbot.addWidget(chat)
    chat.render(
        AnalysisResult(
            content="**结论**\n\n```c\nint x = 1;\n```",
            reasoning="先核查串口",
            state=AnalysisState.DONE,
            conversation=[
                AnalysisMessage(MessageRole.USER, "目标：定位错误\n\n日志", "定位错误"),
                AnalysisMessage(MessageRole.ASSISTANT, "**结论**\n\n```c\nint x = 1;\n```"),
            ],
        )
    )

    manager.theme_changed.connect(model.set_tokens)
    manager.theme_changed.connect(chat.set_theme_tokens)

    try:
        light = manager.apply_scheme(Qt.ColorScheme.Light)
        assert light is LIGHT_TOKENS
        assert qapp.style().metaObject().className() in ("QFusionStyle", "QStyleSheetStyle")
        assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(LIGHT_TOKENS.bg_canvas)
        assert LIGHT_TOKENS.accent_primary in qapp.styleSheet()
        light_fg = model.data(model.index(0, 2), Qt.ItemDataRole.ForegroundRole).color()
        assert light_fg == QColor(LIGHT_TOKENS.level_error)
        light_card_bg = chat._cards[1].detail.palette().color(QPalette.ColorRole.Window)

        dark = manager.apply_scheme(Qt.ColorScheme.Dark)
        assert dark is DARK_TOKENS
        assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(DARK_TOKENS.bg_canvas)
        assert DARK_TOKENS.accent_primary in build_qss(dark)
        dark_fg = model.data(model.index(0, 2), Qt.ItemDataRole.ForegroundRole).color()
        dark_bg = model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole).color()
        assert dark_fg == QColor(DARK_TOKENS.level_error)
        assert dark_bg == QColor(DARK_TOKENS.level_error_row_bg)
        dark_card_bg = chat._cards[1].detail.palette().color(QPalette.ColorRole.Window)
        assert dark_card_bg != light_card_bg
        # 切换主题不破坏原始 Markdown 导出文本
        assert chat.plain_text().endswith("```c\nint x = 1;\n```")
    finally:
        manager.apply_scheme(original)


def test_monospace_font_and_builtin_icons_render(qapp) -> None:
    font = monospace_font(10.0)
    assert font.fixedPitch() is True
    assert font.pointSizeF() == 10.0

    names = available_icons()
    assert {"refresh", "connect", "disconnect", "sliders", "clear", "copy", "send", "stop", "alert"}.issubset(
        set(names)
    )
    for name in names:
        pixmap = render_pixmap(name, "#E6EDF5", size=16, dpr=2.0)
        assert not pixmap.isNull()
        img = pixmap.toImage()
        assert any(img.pixelColor(x, y).alpha() > 0 for y in range(16, 32) for x in range(16, 32))
        icon = render_icon(name, "#E6EDF5", size=16)
        assert not icon.isNull()
        assert not icon.pixmap(16, 16).isNull()
        assert not icon.pixmap(32, 32).isNull()
