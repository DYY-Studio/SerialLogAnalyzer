"""日志过滤代理模型：按级别 / 模块 / 关键字过滤 ``LogTableModel``。"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel

from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.ui.models.log_table_model import (
    LOG_LEVEL_ROLE,
    LOG_MESSAGE_ROLE,
    LOG_MODULE_ROLE,
)

__all__ = ["LogFilterModel"]


class LogFilterModel(QSortFilterProxyModel):
    """日志过滤代理。

    过滤条件互不影响，可组合使用：级别白名单、模块子串、消息子串（均不区分大小写）。
    """

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self._allowed_levels: set[LogLevel] | None = None
        self._module = ""
        self._text = ""

    def set_allowed_levels(self, levels: set[LogLevel] | None) -> None:
        """设置允许显示的级别；``None`` 表示不过滤。"""

        self._allowed_levels = set(levels) if levels is not None else None
        self.invalidate()

    def set_module_filter(self, module: str) -> None:
        """设置模块过滤（子串匹配，不区分大小写）。"""

        self._module = module.strip().lower()
        self.invalidate()

    def set_text_filter(self, text: str) -> None:
        """设置消息关键字过滤（子串匹配，不区分大小写）。"""

        self._text = text.strip().lower()
        self.invalidate()

    def clear_filters(self) -> None:
        """清空全部过滤条件。"""

        self._allowed_levels = None
        self._module = ""
        self._text = ""
        self.invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:  # pragma: no cover - 未设置源模型时不过滤
            return True
        if self._allowed_levels is not None:
            level = model.data(model.index(source_row, 0, source_parent), LOG_LEVEL_ROLE)
            if level not in self._allowed_levels:
                return False
        if self._module and self._module not in self._value(model, source_row, source_parent, LOG_MODULE_ROLE):
            return False
        return not self._text or self._text in self._value(
            model, source_row, source_parent, LOG_MESSAGE_ROLE
        )

    @staticmethod
    def _value(model: object, row: int, parent: QModelIndex, role: int) -> str:
        return str(model.data(model.index(row, 0, parent), role) or "").lower()
