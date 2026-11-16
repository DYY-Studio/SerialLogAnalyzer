"""异常规则加载与校验测试（不启动 Qt）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from serial_log_analyzer.core.anomalies.rule_loader import load_rule_set, load_rule_sets
from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.models.anomaly import AnomalySeverity
from serial_log_analyzer.core.models.logs import LogLevel

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RULES_PATH = _REPO_ROOT / "rules" / "anomalies" / "default.yaml"


def _default_yaml() -> str:
    return _DEFAULT_RULES_PATH.read_text(encoding="utf-8")


def test_load_shipped_default_rule_set(make_loader) -> None:
    loader = make_loader({"rules/anomalies/default.yaml": _default_yaml()})

    rule_set = load_rule_set(loader, "default")

    assert rule_set.rule_set_id == "default"
    assert rule_set.schema_version == 1
    assert len(rule_set.rules) >= 6
    mem = rule_set.rules[0]
    assert mem.rule_id == "memory-alloc-failed"
    assert mem.severity is AnomalySeverity.CRITICAL
    assert mem.immediate_alert is True
    assert mem.min_level is LogLevel.WARN


def test_load_rule_sets_empty_dir_returns_empty(make_loader) -> None:
    assert load_rule_sets(make_loader({})) == []


def test_load_rule_sets_sorts_and_respects_loader_order() -> None:
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

    a = _default_yaml().replace("rule_set_id: default", "rule_set_id: alpha")
    b = _default_yaml().replace("rule_set_id: default", "rule_set_id: beta")
    loader = RecordingLoader({"rules/anomalies/beta.yaml": b, "rules/anomalies/alpha.yaml": a})

    loaded = load_rule_sets(loader)

    assert [item.rule_set_id for item in loaded] == ["alpha", "beta"]
    assert loader.dirs == ["rules/anomalies"]


@pytest.mark.parametrize(
    "bad_yaml",
    [
        "schema_version: 2\nrule_set_id: bad\ndisplay_name: B\nrules: []\n",
        "schema_version: 1\nrule_set_id: other\ndisplay_name: B\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    keywords: ['err']\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\nextra: 1\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    keywords: ['err']\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\ndefaults:\n  unknown: 1\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    keywords: ['err']\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\nrules: []\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    keywords: ['a']\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    keywords: ['b']\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    pattern: '['\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    pattern: '" + ("a" * 257) + "'\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    keywords: ['a']\n    window_seconds: true\n",
        "schema_version: 1\nrule_set_id: bad\ndisplay_name: B\nrules:\n  - rule_id: r1\n    category: c\n    severity: HIGH\n    keywords: ['a']\n    cooldown_seconds: -1\n",
    ],
)
def test_invalid_rule_set_raises_config_error(make_loader, bad_yaml: str) -> None:
    loader = make_loader({"rules/anomalies/bad.yaml": bad_yaml})

    with pytest.raises(ConfigError):
        load_rule_set(loader, "bad")
