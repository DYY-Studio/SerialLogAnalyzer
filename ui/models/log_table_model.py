"""
日志表格数据模型 - 基于 QAbstractTableModel
负责批量插入、更新、删除日志条目，高效渲染大量日志数据
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QBrush

from serial_log_analyzer.core.models.logs import LogEntry, LogLevel


# 日志级别对应的颜色配置（浅色主题优化）
LEVEL_COLORS = {
    LogLevel.VERBOSE: QColor(150, 160, 175),
    LogLevel.DEBUG: QColor(49, 130, 206),
    LogLevel.INFO: QColor(56, 161, 105),
    LogLevel.WARN: QColor(214, 158, 46),
    LogLevel.ERROR: QColor(229, 62, 62),
    LogLevel.UNKNOWN: QColor(128, 90, 213),
}

LEVEL_HEADERS = ["#", "时间", "级别", "模块", "消息"]


class LogTableModel(QAbstractTableModel):
    """
    日志表格数据模型
    
    特性：
    - 环形缓冲：超过最大行数时自动移除最旧的日志
    - 批量更新：配合 PipelineUpdate 一次性插入/更新多条
    - 级别着色：不同日志级别显示不同颜色
    """

    # 行数变化时发出信号（用于状态栏更新）
    row_count_changed = Signal(int)

    def __init__(self, parent=None, max_rows: int = 100000):
        super().__init__(parent)
        self._entries: List[LogEntry] = []
        self._max_rows = max_rows

    # ------------------------------------------------------------------
    # 核心数据接口
    # ------------------------------------------------------------------

    def add_entries(self, entries: List[LogEntry]) -> int:
        """批量添加日志条目，返回实际添加的数量"""
        if not entries:
            return 0

        start_row = len(self._entries)
        end_row = start_row + len(entries) - 1

        self.beginInsertRows(QModelIndex(), start_row, end_row)
        self._entries.extend(entries)
        self.endInsertRows()

        # 超过最大行数时，从前面移除
        dropped = self._trim_excess()

        self.row_count_changed.emit(len(self._entries))
        return len(entries) - dropped

    def update_entry(self, sequence: int, updated: LogEntry) -> bool:
        """根据序列号更新某条日志（用于 continuation 行合并）"""
        for i, entry in enumerate(self._entries):
            if entry.sequence == sequence:
                self._entries[i] = updated
                self.dataChanged.emit(
                    self.index(i, 0),
                    self.index(i, self.columnCount() - 1),
                )
                return True
        return False

    def remove_entries(self, sequences: List[int]) -> int:
        """按序列号批量移除日志"""
        seq_set = set(sequences)
        keep = [e for e in self._entries if e.sequence not in seq_set]
        removed = len(self._entries) - len(keep)

        if removed > 0:
            self.beginResetModel()
            self._entries = keep
            self.endResetModel()
            self.row_count_changed.emit(len(self._entries))
        return removed

    def clear(self) -> None:
        """清空所有日志"""
        if self._entries:
            self.beginResetModel()
            self._entries.clear()
            self.endResetModel()
            self.row_count_changed.emit(0)

    def entry_at(self, row: int) -> Optional[LogEntry]:
        """获取指定行的日志条目"""
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def entries_at_rows(self, rows: List[int]) -> List[LogEntry]:
        """获取多行的日志条目"""
        return [self._entries[r] for r in rows if 0 <= r < len(self._entries)]

    def all_entries(self) -> List[LogEntry]:
        """获取所有日志条目（用于导出）"""
        return list(self._entries)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _trim_excess(self) -> int:
        """移除超出最大行数的旧日志，返回移除数量"""
        excess = len(self._entries) - self._max_rows
        if excess <= 0:
            return 0

        self.beginRemoveRows(QModelIndex(), 0, excess - 1)
        self._entries = self._entries[excess:]
        self.endRemoveRows()
        return excess

    # ------------------------------------------------------------------
    # QAbstractTableModel 必须实现的接口
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(LEVEL_HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._entries):
            return None

        entry = self._entries[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return str(entry.sequence)
            elif col == 1:
                # 格式化时间戳
                import time
                t = entry.received_at
                return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"
            elif col == 2:
                return entry.level.name
            elif col == 3:
                return entry.module or "-"
            elif col == 4:
                return entry.message

        elif role == Qt.ForegroundRole:
            if col == 2:
                color = LEVEL_COLORS.get(entry.level)
                if color:
                    return QBrush(color)

        elif role == Qt.ToolTipRole:
            # 悬停显示完整内容
            if col == 4:
                return entry.raw
            return None

        return None

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(LEVEL_HEADERS):
            return LEVEL_HEADERS[section]
        return None
