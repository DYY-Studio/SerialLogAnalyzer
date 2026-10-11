"""真实资源目录的集成测试：内置 Preset / Adapter / Profile / Prompt 必须可加载。"""

from __future__ import annotations

from pathlib import Path

import pytest

from serial_log_analyzer.core.llm.adapter_loader import load_adapters
from serial_log_analyzer.core.llm.profile_loader import load_profiles
from serial_log_analyzer.core.logs.preset_loader import load_presets
from serial_log_analyzer.core.prompts.loader import PromptLibrary
from serial_log_analyzer.diagnostics.report import collect
from serial_log_analyzer.io.resources import CompositeResourceLoader

_REPO_ROOT = Path(__file__).resolve().parents[2]
_USER_PRESET = """
schema_version: 1
preset_id: hi3861-default
display_name: 用户覆盖的 Preset
line:
  pattern: '^\\[(?P<level>[A-Z])\\] \\[(?P<module>[^\\]]+)\\] (?P<message>.*)$'
  level_map:
    I: INFO
"""


@pytest.fixture
def loader() -> CompositeResourceLoader:
    return CompositeResourceLoader.from_environment(_REPO_ROOT)


def test_shipped_resources_are_loadable(loader):
    presets = load_presets(loader)
    adapters = load_adapters(loader)
    profiles = load_profiles(loader)

    assert {item.preset_id for item in presets} == {"hi3861-default", "hi3861-timestamped"}
    assert {item.adapter_id for item in adapters} == {
        "openai-compatible",
        "openai-responses",
        "anthropic",
        "google-gemini",
    }
    assert {item.profile_id for item in profiles} == {
        "deepseek",
        "internlm",
        "ollama-local",
        "openai-default",
        "sensenova",
    }


def test_every_profile_can_find_its_adapter(loader):
    adapters = {item.adapter_id for item in load_adapters(loader)}

    for profile in load_profiles(loader):
        assert profile.adapter_id in adapters


def test_prompt_library_exposes_shipped_goals(loader):
    library = PromptLibrary(loader)

    goals = library.goals()
    assert {goal.goal_id for goal in goals} == {
        "aggregate-anomalies",
        "explain-logs",
        "locate-error",
        "suggest-fix",
    }
    assert all(goal.display_name for goal in goals)

    text = library.render("locate-error", context="[E] [wifi] disconnect")
    assert "[E] [wifi] disconnect" in text


def test_diagnostics_report_has_no_config_errors(loader, tmp_path):
    report = collect(loader, keyring_available=False, config_dir=tmp_path)

    assert report.config_errors == ()
    assert report.ok is True
    assert len(report.presets) == 2
    assert len(report.adapters) == 4
    assert len(report.profiles) == 5


def test_user_configuration_overrides_bundled_preset(monkeypatch, tmp_path):
    preset_dir = tmp_path / "presets" / "logs"
    preset_dir.mkdir(parents=True)
    (preset_dir / "hi3861-default.yaml").write_text(_USER_PRESET, encoding="utf-8")
    monkeypatch.setenv("SLA_CONFIG_HOME", str(tmp_path))

    loader = CompositeResourceLoader.from_environment(_REPO_ROOT)
    presets = load_presets(loader)

    assert loader.roots[0] == tmp_path
    overridden = [item for item in presets if item.preset_id == "hi3861-default"]
    assert len(overridden) == 1
    assert overridden[0].display_name == "用户覆盖的 Preset"
