"""导入导出回环测试：走 bootstrap 的纯逻辑入口，不弹对话框。"""

from __future__ import annotations

import pytest

from serial_log_analyzer import bootstrap
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
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
def context(qapp, monkeypatch, tmp_path):
    settings = FakeSettings({SETTINGS_KEYS.EXPORT_DIR: str(tmp_path)})
    monkeypatch.setattr(bootstrap, "QtSettingsStore", lambda *a, **k: settings)
    return bootstrap.build_application(["-platform", "offscreen"])


def test_export_then_import_round_trip(context, tmp_path) -> None:
    from serial_log_analyzer.io.storage.log_file_store import ExportFormat

    for index, line in enumerate(["[I] [wifi] connected", "[E] [uart] rx overflow"]):
        context.pipeline.feed(line, float(index))

    target = tmp_path / "session.log"
    lines = bootstrap.export_logs(context, target, ExportFormat.TEXT)

    assert target.is_file() and lines == 2  # 文本格式每条一行

    imported = []
    count = bootstrap.import_logs(context, target, imported.append)
    assert count == 2
    assert len(imported) == 2


def test_export_infers_format_from_suffix(context, tmp_path) -> None:
    context.pipeline.feed("[I] [main] boot done", 1.0)

    text_path = tmp_path / "session.jsonl"
    bootstrap.export_logs(context, text_path)

    payload = text_path.read_text(encoding="utf-8").strip()
    assert payload.startswith("{")  # JSONL 每行一个对象


def test_export_dialog_path_fills_suffix_from_filter(context, tmp_path, monkeypatch) -> None:
    """对话框路径：无后缀时按选择项补后缀（property / method 混用过，这里把它盖住）。"""

    from PySide6.QtWidgets import QFileDialog

    window = bootstrap.build_window(context)
    context.pipeline.feed("[I] [main] boot done", 1.0)
    picked = tmp_path / "picked"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(picked), "JSON Lines (*.jsonl)")),
    )

    bootstrap._export_logs(window, context)

    written = picked.with_suffix(".jsonl")
    assert written.is_file()
    assert written.read_text(encoding="utf-8").startswith("{")


def test_import_dialog_path_feeds_rows_into_view(context, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    window = bootstrap.build_window(context)
    source = tmp_path / "old.log"
    source.write_text("[I] [wifi] connected\n[E] [uart] rx overflow\n", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(source), "日志文本 (*.log *.txt)")),
    )

    bootstrap._import_logs(window, context)

    assert window.log_view.table_view.model().rowCount() == 2


def test_settings_take_effect_immediately(context) -> None:
    window = bootstrap.build_window(context)
    for index in range(5):
        context.pipeline.feed(f"[I] [main] line {index}", float(index))
    window.log_view.append_update(PipelineUpdate(added=tuple(context.pipeline.entries())))
    assert window.log_view.table_view.model().rowCount() == 5

    context.settings.values[SETTINGS_KEYS.AUTOSCROLL] = False
    context.settings.values[SETTINGS_KEYS.LOG_CAPACITY] = 2
    bootstrap._apply_settings(window, context, bootstrap._analysis_service(context))

    assert context.pipeline.capacity == 2
    assert len(context.pipeline.entries()) == 2
    assert window.log_view.table_view.model().rowCount() == 2
