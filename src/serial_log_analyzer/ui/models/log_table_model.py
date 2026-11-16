"""日志表格数据模型：把 ``LogEntry`` 映射到 ``QAbstractTableModel``。

职责边界：只做展示映射与批量变更通知，不保存业务状态——容量由 ``core.LogPipeline``
负责，截断后的行由 ``PipelineUpdate.dropped_sequences`` 驱动移除。
"""

from __future__ import annotations

import time
from bisect import bisect_left
from collections.abc import Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.ui.theme import LevelStyle, ThemeTokens, default_tokens, level_styles

__all__ = [
    "COLUMN_HEADERS",
    "LEVEL_LABELS",
    "LOG_LEVEL_ROLE",
    "LOG_MESSAGE_ROLE",
    "LOG_MODULE_ROLE",
    "LogTableModel",
]

# 供过滤代理读取原始字段，避免依赖展示文案。
LOG_LEVEL_ROLE = int(Qt.ItemDataRole.UserRole) + 1
LOG_MODULE_ROLE = int(Qt.ItemDataRole.UserRole) + 2
LOG_MESSAGE_ROLE = int(Qt.ItemDataRole.UserRole) + 3

# 级别展示文案（用户可见文案用中文）。
LEVEL_LABELS: dict[LogLevel, str] = {
    LogLevel.VERBOSE: "详细",
    LogLevel.DEBUG: "调试",
    LogLevel.INFO: "信息",
    LogLevel.WARN: "警告",
    LogLevel.ERROR: "错误",
    LogLevel.UNKNOWN: "未知",
}

COLUMN_HEADERS = ("序号", "时间", "级别", "模块", "消息")


class LogTableModel(QAbstractTableModel):
    """日志表格模型：批量插入 / 更新 / 移除，按主题级别着色。

    信号:
        row_count_changed(int): 行数变化后发出，供状态栏展示。
    """

    row_count_changed = Signal(int)

    def __init__(
        self,
        parent: object | None = None,
        *,
        tokens: ThemeTokens | None = None,
    ) -> None:
        super().__init__(parent)
        self._entries: list[LogEntry] = []
        self._tokens = tokens if tokens is not None else default_tokens()
        self._level_styles = level_styles(self._tokens)

    def set_tokens(self, tokens: ThemeTokens) -> None:
        """更新主题 Token 并刷新可见单元格前景色与行提示底色。"""

        self._tokens = tokens
        self._level_styles = level_styles(tokens)
        if self._entries:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._entries) - 1, self.columnCount() - 1),
                [Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole],
            )

    def level_style(self, level: LogLevel) -> LevelStyle:
        """返回指定日志级别在当前主题下的语义视觉色。"""

        return self._level_styles[level]

    # ------------------------------------------------------------------
    # 数据变更（由 LogView 依据 PipelineUpdate 调用）
    # ------------------------------------------------------------------

    def add_entries(self, entries: list[LogEntry]) -> int:
        """批量追加条目，返回追加数量。"""

        if not entries:
            return 0
        start = len(self._entries)
        self.beginInsertRows(QModelIndex(), start, start + len(entries) - 1)
        self._entries.extend(entries)
        self.endInsertRows()
        self.row_count_changed.emit(len(self._entries))
        return len(entries)

    def update_entries(self, entries: list[LogEntry]) -> int:
        """按 ``sequence`` 原地更新条目（continuation 合并），返回更新数量。"""

        positions = {entry.sequence: position for position, entry in enumerate(self._entries)}
        updated = 0
        for entry in entries:
            position = positions.get(entry.sequence)
            if position is None:
                continue
            self._entries[position] = entry
            self.dataChanged.emit(
                self.index(position, 0), self.index(position, self.columnCount() - 1)
            )
            updated += 1
        return updated

    def remove_sequences(self, sequences: Sequence[int]) -> int:
        """按 ``sequence`` 批量移除（容量截断），返回移除数量。

        若待移除序列精确匹配表头连续前 K 条，使用 ``beginRemoveRows`` 保护
        当前选区与滚动位置；否则退化为 ``beginResetModel`` 保证视图一致。
        """

        if not sequences or not self._entries:
            return 0
        count = len(sequences)
        if count <= len(self._entries) and all(
            self._entries[index].sequence == sequence for index, sequence in enumerate(sequences)
        ):
            self.beginRemoveRows(QModelIndex(), 0, count - 1)
            del self._entries[:count]
            self.endRemoveRows()
            self.row_count_changed.emit(len(self._entries))
            return count

        dropped = set(sequences)
        keep = [entry for entry in self._entries if entry.sequence not in dropped]
        removed = len(self._entries) - len(keep)
        if removed:
            self.beginResetModel()
            self._entries = keep
            self.endResetModel()
            self.row_count_changed.emit(len(self._entries))
        return removed

    def clear(self) -> None:
        """清空表格。"""

        if not self._entries:
            return
        self.beginResetModel()
        self._entries.clear()
        self.endResetModel()
        self.row_count_changed.emit(0)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def entry_at(self, row: int) -> LogEntry | None:
        """返回指定行的条目；越界时为 ``None``。"""

        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def entries_at_rows(self, rows: list[int]) -> list[LogEntry]:
        """返回多行的条目（忽略越界行），保持表格顺序。"""

        return [self._entries[row] for row in sorted(set(rows)) if 0 <= row < len(self._entries)]

    def entries(self) -> list[LogEntry]:
        """返回全部条目（只读副本）。"""

        return list(self._entries)

    def row_for_sequence(self, sequence: int) -> int | None:
        """按递增 ``sequence`` 查找所在行号；不存在时返回 ``None``。"""

        index = bisect_left(self._entries, sequence, key=lambda entry: entry.sequence)
        if index < len(self._entries) and self._entries[index].sequence == sequence:
            return index
        return None

    # ------------------------------------------------------------------
    # QAbstractTableModel
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return len(self._entries)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return len(COLUMN_HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        entry = self.entry_at(index.row())
        if entry is None:
            return None
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(entry, column)
        if role == Qt.ItemDataRole.ForegroundRole and column == 2:
            return QBrush(QColor(self._level_styles[entry.level].foreground))
        if role == Qt.ItemDataRole.BackgroundRole:
            row_bg = self._level_styles[entry.level].row_bg
            return QBrush(QColor(row_bg)) if row_bg is not None else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(entry)
        if role == LOG_LEVEL_ROLE:
            return entry.level
        if role == LOG_MODULE_ROLE:
            return entry.module or ""
        if role == LOG_MESSAGE_ROLE:
            return entry.message
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and 0 <= section < len(COLUMN_HEADERS)
        ):
            return COLUMN_HEADERS[section]
        return None

    @staticmethod
    def _format_time(moment: float) -> str:
        return f"{time.strftime('%H:%M:%S', time.localtime(moment))}.{int(moment % 1 * 1000):03d}"

    @classmethod
    def _display(cls, entry: LogEntry, column: int) -> str:
        if column == 0:
            return str(entry.sequence)
        if column == 1:
            return cls._format_time(entry.received_at)
        if column == 2:
            return LEVEL_LABELS.get(entry.level, entry.level.name)
        if column == 3:
            return entry.module or "-"
        return entry.message

    @classmethod
    def _tooltip(cls, entry: LogEntry) -> str:
        lines = [
            f"序号 #{entry.sequence} · {LEVEL_LABELS.get(entry.level, entry.level.name)}",
            f"接收时间: {cls._format_time(entry.received_at)}",
        ]
        if entry.device_time:
            lines.append(f"板上时间: {entry.device_time}")
        if entry.module:
            lines.append(f"模块: {entry.module}")
        if entry.extra:
            fields = "  ".join(f"{key}={value}" for key, value in entry.extra.items())
            lines.append(f"字段: {fields}")
        lines.append(f"原始行:\n{entry.raw}")
        return "\n".join(lines)
