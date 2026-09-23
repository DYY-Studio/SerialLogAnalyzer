"""日志表格模型：``QAbstractTableModel`` 适配 ``LogEntry`` 列表。

要点：
- 只在 GUI 线程更新；
- 批量插入使用 ``beginInsertRows`` / ``endInsertRows``，末条修改使用
  ``dataChanged``，超限丢弃使用 ``beginRemoveRows`` / ``endRemoveRows``；
- 不在模型内保存业务状态，条目数据来自 :class:`LogPipeline`。
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex

from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.models.logs import LogEntry

__all__ = ["COLUMNS", "LogTableModel"]

COLUMNS = ("时间", "级别", "模块", "消息")

_INVALID_INDEX = QModelIndex()


class LogTableModel(QAbstractTableModel):
    """日志表格数据模型。

    参数:
        parent: 可选父对象。
    """

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def rowCount(self, parent: QModelIndex = _INVALID_INDEX) -> int:
        """返回行数。"""

        raise NotImplementedError

    def columnCount(self, parent: QModelIndex = _INVALID_INDEX) -> int:
        """返回列数（见 :data:`COLUMNS`）。"""

        raise NotImplementedError

    def data(self, index: QModelIndex, role: int = 0) -> object:
        """返回单元格数据。

        支持 ``DisplayRole``（文本）、``ForegroundRole``（按级别着色）、
        ``UserRole``（返回 ``LogEntry`` 供控制器取序号）。
        """

        raise NotImplementedError

    def headerData(self, section: int, orientation: object, role: int = 0) -> object:
        """返回表头文本。"""

        raise NotImplementedError

    def apply_update(self, update: PipelineUpdate) -> None:
        """把流水线增量应用到模型。

        参数:
            update: 新增 / 修改 / 丢弃条目集合。
        """

        raise NotImplementedError

    def entry_at(self, row: int) -> LogEntry | None:
        """按行号取条目；越界返回 ``None``。"""

        raise NotImplementedError

    def clear(self) -> None:
        """清空全部行。"""

        raise NotImplementedError
