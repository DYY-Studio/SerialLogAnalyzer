"""日志视图：表格 + 过滤栏 + 暂停滚动。

组合 ``QTableView`` 与 :class:`LogFilterModel`，提供自动滚动、暂停、
复制选中行与导出入口；不直接持有日志数据。
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

__all__ = ["LogView"]


class LogView(QWidget):
    """日志表格视图。

    参数:
        model: :class:`LogTableModel` 实例。
        parent: 可选父对象。
    """

    def __init__(self, model: object, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def append_update(self, update: object) -> None:
        """接收流水线增量，转交模型并处理自动滚动。"""

        raise NotImplementedError

    def selected_log_entries(self) -> list[object]:
        """返回当前用户选中的条目（用于分析上下文）。"""

        raise NotImplementedError

    def set_autoscroll(self, enabled: bool) -> None:
        """设置是否自动滚动到最新行。"""

        raise NotImplementedError

    def clear(self) -> None:
        """清空表格。"""

        raise NotImplementedError
