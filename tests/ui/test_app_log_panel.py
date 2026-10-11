"""``AppLogPanel`` 测试（离屏）：取数、刷新与可见时才轮询。"""

from __future__ import annotations

from serial_log_analyzer.ui.widgets.app_log_panel import AppLogPanel


def test_path_label_elides_and_copies_on_click(qtbot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    full = "C:/Users/ASUS/AppData/Roaming/SerialLogAnalyzer/logs/serial-log-analyzer.log"
    panel = AppLogPanel(lambda: [], full)
    qtbot.addWidget(panel)
    panel.resize(240, 120)
    panel.show()
    panel.layout().activate()

    label = panel.path_label
    assert label.minimumSizeHint().width() < 100  # 不靠长路径撑宽度
    assert label.text() != full and "…" in label.text()
    assert label.toolTip().startswith(full)

    qtbot.mouseClick(label, Qt.MouseButton.LeftButton)

    assert QGuiApplication.clipboard().text() == full


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
