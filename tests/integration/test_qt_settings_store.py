"""``QtSettingsStore`` 集成测试：真实 ``QSettings`` 读写与类型转换。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS, QtSettingsStore


@pytest.fixture
def store(tmp_path) -> QtSettingsStore:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return QtSettingsStore(settings=settings)


def test_value_roundtrip_and_defaults(store: QtSettingsStore) -> None:
    assert store.get("missing") is None
    assert store.get("missing", "回退值") == "回退值"

    store.set(SETTINGS_KEYS.CURRENT_PROFILE, "deepseek")

    assert store.get(SETTINGS_KEYS.CURRENT_PROFILE) == "deepseek"
    assert store.contains(SETTINGS_KEYS.CURRENT_PROFILE) is True


def test_sync_writes_ini_file(store: QtSettingsStore) -> None:
    store.set(SETTINGS_KEYS.LOG_CAPACITY, 50_000)
    store.sync()

    path = store.file_path()
    assert path.is_file()
    assert "capacity" in path.read_text(encoding="utf-8")


def test_bool_and_int_coercion(store: QtSettingsStore) -> None:
    store.set(SETTINGS_KEYS.AUTOSCROLL, True)
    store.set(SETTINGS_KEYS.LOG_CAPACITY, 12_000)
    store.sync()

    assert store.get_bool(SETTINGS_KEYS.AUTOSCROLL, False) is True
    assert store.get_int(SETTINGS_KEYS.LOG_CAPACITY, 0) == 12_000


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("false", False), ("1", True), ("0", False), ("", False)],
)
def test_bool_parsing_covers_ini_text(store: QtSettingsStore, raw, expected) -> None:
    store.set("logs/flag", raw)

    assert store.get_bool("logs/flag", not expected) is expected


def test_bool_parsing_falls_back_on_garbage(store: QtSettingsStore) -> None:
    store.set("logs/flag", "也许")

    assert store.get_bool("logs/flag", True) is True
    assert store.get_bool("logs/flag", False) is False


def test_int_and_str_fallback(store: QtSettingsStore) -> None:
    store.set("logs/flag", "不是数字")

    assert store.get_int("logs/flag", 7) == 7
    assert store.get_str("logs/absent", "默认") == "默认"
    assert store.get_str(SETTINGS_KEYS.EXPORT_DIR, "") == ""


def test_remove_and_clear(store: QtSettingsStore) -> None:
    store.set(SETTINGS_KEYS.EXPORT_DIR, "D:/exports")
    store.set(SETTINGS_KEYS.LAST_PORT, "COM3")

    store.remove(SETTINGS_KEYS.EXPORT_DIR)
    assert store.contains(SETTINGS_KEYS.EXPORT_DIR) is False
    assert store.contains(SETTINGS_KEYS.LAST_PORT) is True

    store.clear()
    assert store.contains(SETTINGS_KEYS.LAST_PORT) is False


def test_settings_keys_are_unique_and_prefixed() -> None:
    values = [
        value
        for name, value in vars(SETTINGS_KEYS).items()
        if name.isupper() and isinstance(value, str)
    ]

    assert len(values) == len(set(values))
    assert all(value.split("/", 1)[0] in {"window", "device", "llm", "logs"} for value in values)


def test_default_construction_uses_application_namespace() -> None:
    store = QtSettingsStore()

    assert "SerialLogAnalyzer" in str(store.file_path())
