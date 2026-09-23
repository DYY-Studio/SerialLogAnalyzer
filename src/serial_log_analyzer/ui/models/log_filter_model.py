"""日志过滤模型：按级别 / 模块 / 关键字过滤。

基于 ``QSortFilterProxyModel``；过滤条件由工具栏设置，不修改源模型数据。
"""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel

from serial_log_analyzer.core.models.logs import LogLevel

__all__ = ["LogFilterModel"]


class LogFilterModel(QSortFilterProxyModel):
    """日志过滤代理模型。

    参数:
        parent: 可选父对象。
    """

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def set_min_level(self, level: LogLevel | None) -> None:
        """设置最低显示级别；``None`` 表示不过滤级别。"""

        raise NotImplementedError

    def set_module_filter(self, module: str) -> None:
        """设置模块过滤（子串匹配，空串表示不过滤）。"""

        raise NotImplementedError

    def set_text_filter(self, text: str) -> None:
        """设置消息关键字过滤（大小写不敏感子串匹配）。"""

        raise NotImplementedError

    def filterAcceptsRow(self, source_row: int, source_parent: object) -> bool:
        """判断源行是否通过全部过滤条件。"""

        raise NotImplementedError
