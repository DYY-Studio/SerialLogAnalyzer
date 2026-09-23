"""基于 ``QSettings`` 的设置存储实现。

只保存简单首选项（窗口尺寸、splitter 状态、最近串口与波特率、当前 Profile、UI 选项）；
结构复杂的 Provider Profile 使用 ``providers/profiles/*.yaml``，不塞进 ``QSettings``。
"""

from __future__ import annotations

from typing import Any

__all__ = ["QtSettingsStore", "SETTINGS_KEYS"]


class SETTINGS_KEYS:
    """集中定义设置键名，避免各处硬编码字符串。"""

    WINDOW_GEOMETRY = "window/geometry"
    WINDOW_STATE = "window/state"
    SPLITTER_SIZES = "window/splitter_sizes"
    LAST_PORT = "device/last_port"
    LAST_BAUDRATE = "device/last_baudrate"
    CURRENT_PROFILE = "llm/current_profile"
    CURRENT_PRESET = "logs/current_preset"
    AUTOSCROLL = "logs/autoscroll"
    LOG_CAPACITY = "logs/capacity"


class QtSettingsStore:
    """``SettingsStore`` 的 QSettings 实现。

    参数:
        organization: 组织名，默认 ``SerialLogAnalyzer``。
        application: 应用名，默认 ``SerialLogAnalyzer``。
    """

    def __init__(
        self,
        organization: str = "SerialLogAnalyzer",
        application: str = "SerialLogAnalyzer",
    ) -> None:
        raise NotImplementedError

    def get(self, key: str, default: Any = None) -> Any:
        """读取设置值；不存在时返回 ``default``。"""

        raise NotImplementedError

    def set(self, key: str, value: Any) -> None:
        """写入并同步设置值。"""

        raise NotImplementedError

    def sync(self) -> None:
        """强制刷新到磁盘（退出前调用）。"""

        raise NotImplementedError
