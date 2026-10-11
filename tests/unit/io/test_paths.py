"""``io/paths.py`` 的路径解析测试（纯 Python，不涉及 Qt）。"""

from __future__ import annotations

from serial_log_analyzer.io import paths


def test_user_config_dir_prefers_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SLA_CONFIG_HOME", str(tmp_path / "cfg"))
    assert paths.user_config_dir() == tmp_path / "cfg"
    assert paths.user_log_dir() == tmp_path / "cfg" / "logs"


def test_user_config_dir_default_uses_app_name(monkeypatch):
    monkeypatch.delenv("SLA_CONFIG_HOME", raising=False)
    assert paths.user_config_dir().name == paths.APP_DIR_NAME


def test_default_export_dir_prefers_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SLA_EXPORT_DIR", str(tmp_path / "out"))
    assert paths.default_export_dir() == tmp_path / "out"


def test_default_export_dir_falls_back_to_repo_exports(monkeypatch):
    monkeypatch.delenv("SLA_EXPORT_DIR", raising=False)
    root = paths.repo_root()
    assert root is not None, "测试应在源码仓库内运行"
    assert paths.default_export_dir() == root / "exports"


def test_repo_root_is_source_checkout():
    root = paths.repo_root()
    assert root is not None
    assert (root / "src").is_dir()
    assert (root / "presets").is_dir()


def test_package_resources_dir_is_inside_package():
    resources = paths.package_resources_dir()
    assert resources.name == "resources"
    assert resources.parent.name == "serial_log_analyzer"
