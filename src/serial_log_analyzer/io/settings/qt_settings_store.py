"""基于 ``QSettings`` 的设置存储实现。

只保存简单首选项（窗口尺寸与停靠布局、最近串口与波特率、当前 Profile/Preset、UI 选项）；
结构复杂的 Provider Profile 使用 ``providers/profiles/*.yaml``，不塞进 ``QSettings``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

__all__ = ["QtSettingsStore", "SETTINGS_KEYS"]


class SETTINGS_KEYS:
    """集中定义设置键名，避免各处硬编码字符串。"""

    WINDOW_GEOMETRY = "window/geometry"
    WINDOW_STATE = "window/state"
    LAST_PORT = "device/last_port"
    LAST_BAUDRATE = "device/last_baudrate"
    CURRENT_PROFILE = "llm/current_profile"
    CHAT_DETAILS_EXPANDED = "llm/details_expanded"
    LLM_HISTORY_ROUNDS = "llm/history_rounds"
    CURRENT_PRESET = "logs/current_preset"
    AUTOSCROLL = "logs/autoscroll"
    LOG_CAPACITY = "logs/capacity"
    LOG_LEVEL = "logs/app_log_level"
    EXPORT_DIR = "logs/export_dir"


def _as_bool(value: Any, default: bool) -> bool:
    """把 ``QSettings`` 读出的值稳健地转换为布尔值。

    IniFormat 会把布尔值写成 ``true`` / ``false`` 字符串，因此不能直接 ``bool(value)``。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return default


class QtSettingsStore:
    """``SettingsStore`` 的 QSettings 实现。

    参数:
        organization: 组织名，默认 ``SerialLogAnalyzer``。
        application: 应用名，默认 ``SerialLogAnalyzer``。
        settings: 可选的 ``QSettings`` 实例（测试时注入 IniFormat 实例，避免污染用户配置）。
    """

    def __init__(
        self,
        organization: str = "SerialLogAnalyzer",
        application: str = "SerialLogAnalyzer",
        *,
        settings: QSettings | None = None,
    ) -> None:
        self._settings = settings if settings is not None else QSettings(organization, application)

    def get(self, key: str, default: Any = None) -> Any:
        """读取设置值；不存在时返回 ``default``。"""
        return self._settings.value(key, default)

    def set(self, key: str, value: Any) -> None:
        """写入设置值（不立即落盘，退出前由 :meth:`sync` 刷新）。"""
        self._settings.setValue(key, value)

    def sync(self) -> None:
        """强制刷新到磁盘（退出前调用）。"""
        self._settings.sync()

    def remove(self, key: str) -> None:
        """删除单个设置项；不存在时为空操作。"""
        self._settings.remove(key)

    def clear(self) -> None:
        """清空全部设置（仅影响本应用命名空间）。"""
        self._settings.clear()

    def contains(self, key: str) -> bool:
        """判断某个设置项是否已写入。"""
        return bool(self._settings.contains(key))

    def get_bool(self, key: str, default: bool = False) -> bool:
        """读取布尔设置，兼容 ``true``/``false`` 字符串与 ``0``/``1``。"""
        return _as_bool(self._settings.value(key, default), default)

    def get_int(self, key: str, default: int = 0) -> int:
        """读取整数设置，无法转换时返回 ``default``。"""
        value = self._settings.value(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_str(self, key: str, default: str = "") -> str:
        """读取字符串设置；空值返回 ``default``。"""
        value = self._settings.value(key, default)
        text = "" if value is None else str(value)
        return text or default

    def file_path(self) -> Path:
        """返回底层设置文件的路径（用于诊断报告）。"""
        return Path(self._settings.fileName())
