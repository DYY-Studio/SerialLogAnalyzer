"""``io/storage/log_file_store.py`` 的导入 / 导出测试。"""

from __future__ import annotations

import csv
import json
import re

import pytest

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.io.storage.log_file_store import ExportFormat, LogFileStore


def _entry(
    sequence: int,
    message: str,
    *,
    level: LogLevel = LogLevel.INFO,
    module: str | None = "app",
    device_time: str | None = None,
    extra: dict[str, str] | None = None,
    raw: str | None = None,
) -> LogEntry:
    return LogEntry(
        sequence=sequence,
        received_at=1_700_000_000.0 + sequence,
        level=level,
        message=message,
        raw=raw if raw is not None else f"[INFO] {message}",
        device_time=device_time,
        module=module,
        extra=extra or {},
    )


def test_export_text_writes_raw_lines(tmp_path):
    store = LogFileStore(tmp_path / "exports")
    path = tmp_path / "out" / "session.log"
    entries = [_entry(1, "boot"), _entry(2, "wifi ready")]

    written = store.export_entries(entries, path)

    assert written == 2
    assert path.read_text(encoding="utf-8") == "[INFO] boot\n[INFO] wifi ready\n"


def test_export_text_counts_multiline_raw(tmp_path):
    store = LogFileStore(tmp_path)
    path = tmp_path / "multi.log"
    entries = [_entry(1, "trace", raw="line1\nline2\nline3")]

    assert store.export_entries(entries, path) == 3
    assert path.read_text(encoding="utf-8") == "line1\nline2\nline3\n"


def test_export_csv_has_header_and_records(tmp_path):
    store = LogFileStore(tmp_path)
    path = tmp_path / "session.csv"
    entries = [
        _entry(7, "温度过高", level=LogLevel.ERROR, extra={"code": "E12", "tag": "sensor"}),
        _entry(8, "done", module=None, device_time="00:00:01.250"),
    ]

    written = store.export_entries(entries, path, fmt=ExportFormat.CSV)

    assert written == 2
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == [
        "sequence",
        "received_at",
        "level",
        "module",
        "device_time",
        "message",
        "extra",
    ]
    assert rows[1][0] == "7"
    assert rows[1][2] == "ERROR"
    assert rows[1][3] == "app"
    assert rows[1][5] == "温度过高"
    assert json.loads(rows[1][6]) == {"code": "E12", "tag": "sensor"}
    assert rows[2][3] == ""
    assert rows[2][4] == "00:00:01.250"
    assert rows[2][6] == ""


def test_export_jsonl_round_trips_fields(tmp_path):
    store = LogFileStore(tmp_path)
    path = tmp_path / "session.jsonl"
    entries = [_entry(3, "multi\nline", raw="multi\nline", extra={"n": "1"})]

    written = store.export_entries(entries, path, fmt=ExportFormat.JSONL)

    assert written == 1
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["sequence"] == 3
    assert payload["level"] == "INFO"
    assert payload["message"] == "multi\nline"
    assert payload["raw"] == "multi\nline"
    assert payload["extra"] == {"n": "1"}


def test_suggested_path_uses_format_suffix_and_timestamp(tmp_path):
    store = LogFileStore(tmp_path / "exports")

    text_path = store.suggested_path()
    csv_path = store.suggested_path(fmt=ExportFormat.CSV)

    assert text_path.parent == tmp_path / "exports"
    assert re.fullmatch(r"serial-log-\d{8}-\d{6}\.log", text_path.name)
    assert re.fullmatch(r"serial-log-\d{8}-\d{6}\.csv", csv_path.name)


def test_suggested_path_sanitizes_stem_to_ascii(tmp_path):
    store = LogFileStore(tmp_path)

    csv_path = store.suggested_path("日志 2024/01", fmt=ExportFormat.CSV)

    assert re.fullmatch(r"2024-01-\d{8}-\d{6}\.csv", csv_path.name)


def test_suggested_path_falls_back_when_stem_is_unusable(tmp_path):
    store = LogFileStore(tmp_path)

    path = store.suggested_path("日志")

    assert path.name.startswith("serial-log-")


def test_export_reports_app_error_when_target_not_writable(tmp_path):
    store = LogFileStore(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(AppError):
        store.export_entries([_entry(1, "x")], blocker / "out.log")


def test_import_entries_skips_blank_lines_and_keeps_order(tmp_path):
    store = LogFileStore(tmp_path)
    source = tmp_path / "in.log"
    source.write_text("first\n\n  \nsecond\nthird\n", encoding="utf-8")
    seen: list[tuple[str, float]] = []

    count = store.import_entries(source, lambda text, received_at: seen.append((text, received_at)))

    assert count == 3
    assert [text for text, _ in seen] == ["first", "second", "third"]
    timestamps = [received_at for _, received_at in seen]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 3


def test_import_entries_missing_file_raises(tmp_path):
    store = LogFileStore(tmp_path)

    with pytest.raises(AppError):
        store.import_entries(tmp_path / "nope.log", lambda text, received_at: None)
