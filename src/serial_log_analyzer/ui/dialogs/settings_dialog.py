"""设置对话框：界面偏好与日志容量等。

只读写 :class:`SettingsStore`，不触碰凭据与 Provider 配置。
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

__all__ = ["SettingsDialog"]


class SettingsDialog(QDialog):
    """应用设置对话框。

    参数:
        settings: 设置存储。
        parent: 可选父窗口。
    """

    def __init__(self, settings: object, parent: QDialog | None = None) -> None:
        raise NotImplementedError

    def accept(self) -> None:
        """保存设置并关闭。"""

        raise NotImplementedError
