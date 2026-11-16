"""Preset 加载与校验测试。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import ConfigError, PresetError
from serial_log_analyzer.core.logs.preset import PresetCommand, PresetCommandMode
from serial_log_analyzer.core.logs.preset_loader import load_preset, load_presets
from serial_log_analyzer.core.models.logs import LogLevel


def test_load_default_preset_reads_level_map(make_loader, default_preset_yaml: str) -> None:
    loader = make_loader({"presets/logs/hi3861-default.yaml": default_preset_yaml})
    preset = load_preset(loader, "hi3861-default")
    assert preset.preset_id == "hi3861-default"
    assert preset.level_from_token("I") is LogLevel.INFO
    assert preset.line.continuation_pattern is not None
    assert [cmd.label for cmd in preset.commands] == [
        "PING",
        "VERSION",
        "HELP",
        "TEST …",
        "TEST wifi",
        "TEST all",
    ]
    assert preset.commands[3] == PresetCommand(
        label="TEST …",
        command="TEST ",
        mode=PresetCommandMode.PREFILL,
        tooltip=preset.commands[3].tooltip,
    )
    assert all(cmd.tooltip for cmd in preset.commands)


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
    loader = make_loader({"presets/logs/aaa.yaml": a, "presets/logs/bbb.yaml": b})
    presets = load_presets(loader)
    assert [p.preset_id for p in presets] == ["aaa", "bbb"]


def test_preset_id_must_match_file_name(make_loader, default_preset_yaml: str) -> None:
    loader = make_loader({"presets/logs/renamed.yaml": default_preset_yaml})
    with pytest.raises(PresetError):
        load_preset(loader, "renamed")


def test_load_presets_relies_on_loader_priority(default_preset_yaml: str) -> None:
    """用户覆盖由 ResourceLoader 的跨根优先级实现，不该由本模块拼 ``user/`` 前缀。"""

    class RecordingLoader:
        def __init__(self, files: dict[str, str]) -> None:
            self._files = files
            self.dirs: list[str] = []

        def read_text(self, relative_path: str) -> str:
            if relative_path not in self._files:
                raise ConfigError(relative_path)
            return self._files[relative_path]

        def list_files(self, relative_dir: str, pattern: str) -> list[str]:
            self.dirs.append(relative_dir)
            return sorted(path for path in self._files if path.startswith(relative_dir))

    loader = RecordingLoader({"presets/logs/hi3861-default.yaml": default_preset_yaml})
    presets = load_presets(loader)
    assert [p.preset_id for p in presets] == ["hi3861-default"]
    assert loader.dirs == ["presets/logs"]


def test_fields_must_be_mapping(make_loader) -> None:
    bad = (
        "schema_version: 1\npreset_id: bad\ndisplay_name: Bad\n"
        "line:\n"
        r"  pattern: '\[(?P<level>\w+)\]\[(?P<module>[^\]]+)\] (?P<message>.*)'" + "\n"
        "  level_map:\n    I: INFO\n"
        "  fields: [1, 2]\n"
    )
    with pytest.raises(PresetError):
        load_preset(make_loader({"presets/logs/bad.yaml": bad}), "bad")


_MINIMAL_PRESET = (
    "schema_version: 1\npreset_id: custom\ndisplay_name: Custom\n"
    "line:\n"
    r"  pattern: '\[(?P<level>\w+)\]\[(?P<module>[^\]]+)\] (?P<message>.*)'" + "\n"
    "  level_map:\n    I: INFO\n"
)


def test_commands_parsing_defaults_and_whitespace_rules(make_loader) -> None:
    """无 commands 时为空元组；send 去双端空白，prefill 保留末尾空格。"""

    empty = load_preset(make_loader({"presets/logs/custom.yaml": _MINIMAL_PRESET}), "custom")
    assert empty.commands == ()

    yaml_text = _MINIMAL_PRESET + (
        "commands:\n"
        "  - label: '  AT  '\n"
        "    command: '  AT+GMR  '\n"
        "  - label: 'TEST …'\n"
        "    command: '  TEST '\n"
        "    mode: prefill\n"
        "    tooltip: '  预填测试  '\n"
    )
    preset = load_preset(make_loader({"presets/logs/custom.yaml": yaml_text}), "custom")
    assert preset.commands == (
        PresetCommand(label="AT", command="AT+GMR", mode=PresetCommandMode.SEND, tooltip=""),
        PresetCommand(
            label="TEST …",
            command="TEST ",
            mode=PresetCommandMode.PREFILL,
            tooltip="预填测试",
        ),
    )


@pytest.mark.parametrize(
    "commands_yaml",
    [
        "commands: 'PING'\n",
        "commands:\n  - 'PING'\n",
        "commands:\n  - label: 'PING'\n    command: 'PING'\n    unknown: 1\n",
        "commands:\n  - label: '   '\n    command: 'PING'\n",
        "commands:\n  - label: 123\n    command: 'PING'\n",
        "commands:\n  - label: 'PING'\n",
        "commands:\n  - label: 'PING'\n    command: '   '\n",
        "commands:\n  - label: 'PING'\n    command: 'TEST '\n    mode: prefill_bad\n",
        "commands:\n  - label: 'PING'\n    command: 'PING'\n    mode: 1\n",
        "commands:\n  - label: 'PING'\n    command: 'PING'\n    tooltip: 123\n",
    ],
)
def test_invalid_commands_schema_raises(make_loader, commands_yaml: str) -> None:
    bad = _MINIMAL_PRESET + commands_yaml
    with pytest.raises(PresetError):
        load_preset(make_loader({"presets/logs/custom.yaml": bad}), "custom")
