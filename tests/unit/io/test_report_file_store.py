"""``io/storage/report_file_store.py`` 的诊断报告导出测试。"""

from __future__ import annotations

import json
import re

import pytest

from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.anomaly import AnomalyRule, AnomalySeverity
from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.core.services.anomaly import AnomalyService
from serial_log_analyzer.core.services.report import build_diagnostic_report
from serial_log_analyzer.io.storage.report_file_store import ReportFileStore, ReportFormat


def _sample_report(default_preset):
    pipeline = LogPipeline(LogParser(default_preset))
    anomaly = AnomalyService(
        [
            AnomalyRule(
                rule_id="mem-oom",
                category="内存分配失败",
                severity=AnomalySeverity.CRITICAL,
                keywords=("malloc failed",),
                min_level=LogLevel.ERROR,
            )
        ]
    )
    anomaly.apply_update(pipeline.feed("[E] [memory] malloc failed size=64", 1_700_000_001.0))
    return build_diagnostic_report(
        pipeline, anomaly, preset_id="hi3861-default", generated_at=1_700_000_005.0
    )


def test_export_markdown_and_json_round_trip(default_preset, tmp_path) -> None:
    report = _sample_report(default_preset)
    store = ReportFileStore(tmp_path / "exports")

    md_path = store.export_report(report, tmp_path / "out" / "diag.md")
    json_path = store.export_report(report, tmp_path / "out" / "diag.json")

    assert md_path.is_file()
    md_text = md_path.read_text(encoding="utf-8")
    assert "# SerialLogAnalyzer 诊断报告" in md_text
    assert "malloc failed size=64" in md_text

    assert json_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["preset_id"] == "hi3861-default"
    assert payload["rule_facts"]["clusters"][0]["rule_id"] == "mem-oom"
    assert not (tmp_path / "out" / "diag.md.tmp").exists()
    assert not (tmp_path / "out" / "diag.json.tmp").exists()


def test_suggested_path_and_invalid_format(default_preset, tmp_path) -> None:
    store = ReportFileStore(tmp_path / "exports")
    md_suggested = store.suggested_path(fmt=ReportFormat.MARKDOWN)
    json_suggested = store.suggested_path("报告", fmt=ReportFormat.JSON)

    assert re.fullmatch(r"diagnostic-report-\d{8}-\d{6}\.md", md_suggested.name)
    assert re.fullmatch(r"diagnostic-report-\d{8}-\d{6}\.json", json_suggested.name)

    report = _sample_report(default_preset)
    with pytest.raises(ConfigError):
        store.export_report(report, tmp_path / "x.md", fmt="invalid")  # type: ignore[arg-type]


def test_export_failure_raises_app_error_and_cleans_temp(default_preset, tmp_path) -> None:
    store = ReportFileStore(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("file", encoding="utf-8")

    with pytest.raises(AppError):
        store.export_report(_sample_report(default_preset), blocker / "report.md")
