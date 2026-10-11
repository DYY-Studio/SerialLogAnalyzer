"""``AppLogPanel`` 测试（离屏）：取数、刷新与可见时才轮询。"""

from __future__ import annotations

from serial_log_analyzer.ui.widgets.app_log_panel import AppLogPanel


def test_reload_follows_the_provider_and_polls_only_while_visible(qtbot) -> None:
    lines = ["第一行"]
    panel = AppLogPanel(lambda: list(lines), "D:/logs/app.log")
    qtbot.addWidget(panel)

    assert panel._timer.isActive() is False
    assert panel._view.toPlainText() == ""

    panel.show()
    assert panel._timer.isActive() is True
    assert panel._view.toPlainText() == "第一行"  # 显示时立刻读一次

    lines.append("第二行")
    panel.reload()
    assert panel._view.toPlainText() == "第一行\n第二行"

    panel.hide()
    assert panel._timer.isActive() is False
