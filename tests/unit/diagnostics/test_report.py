"""``diagnostics/report.py`` 的诊断采集与导出测试。"""

from __future__ import annotations

import json

import pytest

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.diagnostics.report import collect, export, to_json

_MINIMAL_PRESET = """
schema_version: 1
preset_id: hi3861-default
display_name: 最小 Preset
line:
  pattern: '^\\[(?P<level>[A-Z])\\] \\[(?P<module>[^\\]]+)\\] (?P<message>.*)$'
  level_map:
    I: INFO
"""

_ADAPTER = """
schema_version: 3
adapter_id: demo-adapter
endpoint: /v1/chat/completions
response_content_pointer: /choices/0/message/content
"""

_PROFILE = """
schema_version: 1
profile_id: demo
adapter_id: demo-adapter
base_url: https://api.example.com/v1
model: demo-model
stream: false
credential:
  kind: environment
  env_var: DEMO_KEY
"""


def _loader(make_loader, *, preset_yaml: str, adapter: bool = True, profile: bool = True):
    files = {"presets/logs/hi3861-default.yaml": preset_yaml}
    if adapter:
        files["providers/adapters/demo-adapter.yaml"] = _ADAPTER
    if profile:
        files["providers/profiles/demo.yaml"] = _PROFILE
    return make_loader(files)


def test_collect_reports_loaded_resources(make_loader, default_preset_yaml, tmp_path):
    report = collect(
        _loader(make_loader, preset_yaml=default_preset_yaml),
        keyring_available=True,
        config_dir=tmp_path,
        resource_roots=[tmp_path / "user", tmp_path / "repo"],
    )

    assert report.ok is True
    assert report.config_errors == ()
    assert report.app_version
    assert report.python_version
    assert report.presets and report.presets[0].startswith("hi3861-default（")
    assert report.adapters == ("demo-adapter",)
    assert report.profiles == ("demo（demo-model）",)
    assert report.resource_roots == (str(tmp_path / "user"), str(tmp_path / "repo"))
    assert report.config_dir == str(tmp_path)
    assert report.keyring_available is True
    assert report.log_file == ""


def test_collect_records_errors_without_raising(make_loader, tmp_path):
    report = collect(
        _loader(make_loader, preset_yaml="schema_version: [1\n"),
        config_dir=tmp_path,
    )

    assert report.ok is False
    assert len(report.config_errors) == 1
    assert report.config_errors[0].startswith("Preset：")
    assert report.presets == ()
    assert "配置错误（1）" in report.render()


def test_collect_keeps_other_sections_when_preset_fails(make_loader, tmp_path):
    report = collect(
        _loader(make_loader, preset_yaml="schema_version: 1\npreset_id: hi3861-default\n"),
        config_dir=tmp_path,
    )

    assert report.presets == ()
    assert report.adapters == ("demo-adapter",)
    assert report.profiles == ("demo（demo-model）",)
    assert report.ok is False
    assert any(item.startswith("Preset：") for item in report.config_errors)


def test_render_marks_unknown_keyring_and_disabled_file_log(make_loader, tmp_path):
    report = collect(_loader(make_loader, preset_yaml=_MINIMAL_PRESET), config_dir=tmp_path)

    text = report.render()

    assert "系统钥匙串  : 未探测" in text
    assert "（未启用文件日志）" in text
    assert "配置错误    : 无" in text


def test_render_marks_unavailable_keyring(make_loader, tmp_path):
    report = collect(
        _loader(make_loader, preset_yaml=_MINIMAL_PRESET),
        keyring_available=False,
        config_dir=tmp_path,
    )

    assert "不可用（将回退环境变量）" in report.render()


def test_log_tail_reads_last_lines(make_loader, tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text("\n".join(f"line-{index}" for index in range(5)) + "\n", encoding="utf-8")

    report = collect(
        _loader(make_loader, preset_yaml=_MINIMAL_PRESET),
        log_file=log_file,
        log_tail_lines=3,
        config_dir=tmp_path,
    )

    assert report.log_tail == ("line-2", "line-3", "line-4")
    assert report.log_file == str(log_file)
    assert "日志末尾（3 行）:" in report.render()


def test_log_tail_missing_file_is_empty(make_loader, tmp_path):
    report = collect(
        _loader(make_loader, preset_yaml=_MINIMAL_PRESET),
        log_file=tmp_path / "absent.log",
        config_dir=tmp_path,
    )

    assert report.log_tail == ()


def test_to_json_is_serialisable(make_loader, tmp_path):
    report = collect(_loader(make_loader, preset_yaml=_MINIMAL_PRESET), config_dir=tmp_path)

    payload = json.loads(to_json(report))

    assert payload["config_errors"] == []
    assert payload["log_file"] is None
    assert isinstance(payload["resource_roots"], list)
    assert payload["app_version"] == report.app_version


def test_export_writes_report_to_file(make_loader, tmp_path):
    report = collect(_loader(make_loader, preset_yaml=_MINIMAL_PRESET), config_dir=tmp_path)
    target = tmp_path / "nested" / "report.txt"

    written = export(report, target)

    assert written == target
    assert target.read_text(encoding="utf-8") == report.render() + "\n"


def test_export_into_directory_uses_timestamped_name(make_loader, tmp_path):
    report = collect(_loader(make_loader, preset_yaml=_MINIMAL_PRESET), config_dir=tmp_path)

    written = export(report, tmp_path)

    assert written.parent == tmp_path
    assert written.name.startswith("diagnostics-")
    assert written.suffix == ".txt"
    assert written.is_file()


def test_export_failure_raises_app_error(make_loader, tmp_path):
    report = collect(_loader(make_loader, preset_yaml=_MINIMAL_PRESET), config_dir=tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("不是目录", encoding="utf-8")

    with pytest.raises(AppError):
        export(report, blocker / "report.txt")
