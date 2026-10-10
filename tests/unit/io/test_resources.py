"""``io/resources.py`` 的多根资源加载测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.io import paths
from serial_log_analyzer.io.resources import CompositeResourceLoader


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_read_text_prefers_higher_priority_root(tmp_path):
    user, repo = tmp_path / "user", tmp_path / "repo"
    _write(user, "presets/logs/a.yaml", "user")
    _write(repo, "presets/logs/a.yaml", "repo")

    loader = CompositeResourceLoader([user, repo])

    assert loader.read_text("presets/logs/a.yaml") == "user"
    assert loader.resolve("presets/logs/a.yaml") == user / "presets/logs/a.yaml"


def test_read_text_reports_all_searched_roots(tmp_path):
    loader = CompositeResourceLoader([tmp_path / "a", tmp_path / "b"])

    with pytest.raises(ConfigError) as excinfo:
        loader.read_text("presets/logs/missing.yaml")

    message = str(excinfo.value)
    assert "missing.yaml" in message
    assert str(tmp_path / "a") in message
    assert str(tmp_path / "b") in message


@pytest.mark.parametrize(
    "bad_path",
    ["", "   ", "/etc/passwd", "C:/windows/x.yaml", "../secret.yaml", "presets/../../x.yaml"],
)
def test_rejects_escaping_paths(tmp_path, bad_path):
    loader = CompositeResourceLoader([tmp_path])

    with pytest.raises(ConfigError):
        loader.read_text(bad_path)


def test_rejects_empty_root_list():
    with pytest.raises(ConfigError):
        CompositeResourceLoader([])


def test_rejects_empty_directory_argument(tmp_path):
    loader = CompositeResourceLoader([tmp_path])

    with pytest.raises(ConfigError):
        loader.list_files("", "*.yaml")


def test_list_files_dedupes_by_name_and_sorts(tmp_path):
    user, repo = tmp_path / "user", tmp_path / "repo"
    _write(user, "providers/profiles/b.yaml", "user-b")
    _write(user, "providers/profiles/a.yaml", "user-a")
    _write(repo, "providers/profiles/b.yaml", "repo-b")
    _write(repo, "providers/profiles/c.yaml", "repo-c")
    _write(repo, "providers/adapters/z.yaml", "z")
    _write(repo, "providers/profiles/ignored.txt", "x")

    loader = CompositeResourceLoader([user, repo])

    assert loader.list_files("providers/profiles", "*.yaml") == [
        "providers/profiles/a.yaml",
        "providers/profiles/b.yaml",
        "providers/profiles/c.yaml",
    ]
    assert loader.read_text("providers/profiles/b.yaml") == "user-b"
    assert loader.list_files("providers/adapters", "*.yaml") == ["providers/adapters/z.yaml"]
    assert loader.list_files("prompts", "*.md") == []


def test_list_files_of_root_directory_has_no_prefix(tmp_path):
    _write(tmp_path, "top.md", "x")
    loader = CompositeResourceLoader([tmp_path])

    assert loader.list_files(".", "*.md") == ["top.md"]


def test_from_environment_orders_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("SLA_CONFIG_HOME", str(tmp_path / "cfg"))
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "presets").mkdir(parents=True)

    loader = CompositeResourceLoader.from_environment(root)

    assert loader.roots[0] == tmp_path / "cfg"
    assert loader.roots[1] == root
    assert loader.roots[-1].name == "resources"
    assert str(tmp_path / "cfg") in loader.describe_roots()


def test_from_environment_dedupes_when_config_home_is_package_dir(monkeypatch):
    package_dir = paths.package_resources_dir()
    monkeypatch.setenv("SLA_CONFIG_HOME", str(package_dir))

    loader = CompositeResourceLoader.from_environment(None)

    assert list(loader.roots).count(package_dir) == 1
