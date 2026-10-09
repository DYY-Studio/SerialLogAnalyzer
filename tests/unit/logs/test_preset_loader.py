"""Preset 加载与校验测试。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import PresetError
from serial_log_analyzer.core.logs.preset_loader import load_preset, load_presets
from serial_log_analyzer.core.models.logs import LogLevel


def test_load_default_preset_reads_level_map(make_loader, default_preset_yaml: str) -> None:
    loader = make_loader({"presets/logs/hi3861-default.yaml": default_preset_yaml})
    preset = load_preset(loader, "hi3861-default")
    assert preset.preset_id == "hi3861-default"
    assert preset.level_from_token("I") is LogLevel.INFO
    assert preset.line.continuation_pattern is not None


def test_missing_required_field_raises(make_loader) -> None:
    loader = make_loader({"presets/logs/bad.yaml": "schema_version: 1\n"})
    with pytest.raises(PresetError):
        load_preset(loader, "bad")


def test_unknown_top_level_field_raises(make_loader, default_preset_yaml: str) -> None:
    bad = default_preset_yaml + "\nunexpected_field: 1\n"
    with pytest.raises(PresetError):
        load_preset(make_loader({"presets/logs/bad.yaml": bad}), "bad")


def test_missing_required_group_raises(make_loader) -> None:
    bad = (
        "schema_version: 1\npreset_id: bad\ndisplay_name: Bad\n"
        "line:\n  pattern: '^(?P<message>.*)$'\n  level_map: {}\n"
    )
    with pytest.raises(PresetError):
        load_preset(make_loader({"presets/logs/bad.yaml": bad}), "bad")


def test_bad_level_target_raises(make_loader) -> None:
    bad = (
        "schema_version: 1\npreset_id: bad\ndisplay_name: Bad\n"
        "line:\n"
        r"  pattern: '\[(?P<level>\w+)\]\[(?P<module>[^\]]+)\] (?P<message>.*)'" + "\n"
        "  level_map:\n    I: NOT_A_LEVEL\n"
    )
    with pytest.raises(PresetError):
        load_preset(make_loader({"presets/logs/bad.yaml": bad}), "bad")


def test_load_presets_lists_and_sorts(make_loader, default_preset_yaml: str) -> None:
    a = default_preset_yaml.replace("hi3861-default", "aaa").replace("Hi3861 默认日志", "AAA")
    b = default_preset_yaml.replace("hi3861-default", "bbb").replace("Hi3861 默认日志", "BBB")
    loader = make_loader({"presets/logs/a.yaml": a, "presets/logs/b.yaml": b})
    presets = load_presets(loader)
    assert [p.preset_id for p in presets] == ["aaa", "bbb"]
