"""Provider 配置对话框：选择 Profile、编辑 base_url / model / 流式开关。

Profile 的持久化以 ``providers/profiles/*.yaml`` 为准；本对话框只做界面编辑。
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

__all__ = ["ProviderDialog"]


class ProviderDialog(QDialog):
    """模型服务配置对话框。

    参数:
        profiles: 当前可用 Profile 列表。
        parent: 可选父窗口。
    """

    def __init__(self, profiles: list[object], parent: QDialog | None = None) -> None:
        raise NotImplementedError

    def selected_profile_id(self) -> str:
        """返回用户选定的 Profile 标识。"""

        raise NotImplementedError
