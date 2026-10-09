"""单测共享 fixture（logs 解析链路的 Preset/Loader/Parser）。"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.preset_loader import load_preset

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _REPO_ROOT / "presets" / "logs" / "hi3861-default.yaml"


class FakeLoader:
    """内存 ResourceLoader，用于单测。"""

    def __init__(self, files: dict[str, str]) -> None:
        self._files = dict(files)

    def read_text(self, relative_path: str) -> str:
        if relative_path not in self._files:
            raise ConfigError(relative_path)
        return self._files[relative_path]

    def list_files(self, relative_dir: str, pattern: str) -> list[str]:
        return sorted(
            path
            for path in self._files
            if path.startswith(relative_dir)
            and fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern)
        )


@pytest.fixture
def default_preset_yaml() -> str:
    return _DEFAULT_PATH.read_text(encoding="utf-8")


@pytest.fixture
def make_loader():
    def _make(files: dict[str, str]) -> FakeLoader:
        return FakeLoader(files)

    return _make


@pytest.fixture
def default_preset(default_preset_yaml: str):
    loader = FakeLoader({"presets/logs/hi3861-default.yaml": default_preset_yaml})
    return load_preset(loader, "hi3861-default")


@pytest.fixture
def parser(default_preset):
    return LogParser(default_preset)
