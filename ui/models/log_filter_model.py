"""
日志过滤模型 - 基于 QSortFilterProxyModel
支持按级别、模块、关键字进行过滤
"""

from __future__ import annotations

from typing import Set, Optional

from PySide6.QtCore import QSortFilterProxyModel, QModelIndex

from serial_log_analyzer.core.models.logs import LogLevel


class LogFilterModel(QSortFilterProxyModel):
    """
    日志过滤代理模型
    
    支持：
    - 按日志级别过滤（多选）
    - 按模块名过滤
    - 按文本关键字过滤
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._allowed_levels: Optional[Set[LogLevel]] = None
        self._module_filter: str = ""
        self._text_filter: str = ""

    # ------------------------------------------------------------------
    # 过滤条件设置
    # ------------------------------------------------------------------

    def set_allowed_levels(self, levels: Optional[Set[LogLevel]]) -> None:
        """设置允许显示的日志级别，None 表示全部"""
        self._allowed_levels = levels
        self.invalidateFilter()

    def set_module_filter(self, module: str) -> None:
        """设置模块名过滤（精确匹配，空字符串表示全部）"""
        self._module_filter = module.strip()
        self.invalidateFilter()

    def set_text_filter(self, text: str) -> None:
        """设置文本关键字过滤（不区分大小写，匹配消息内容）"""
        self._text_filter = text.strip().lower()
        self.invalidateFilter()

    def clear_filters(self) -> None:
        """清空所有过滤条件"""
        self._allowed_levels = None
        self._module_filter = ""
        self._text_filter = ""
        self.invalidateFilter()

    # ------------------------------------------------------------------
    # 过滤逻辑
    # ------------------------------------------------------------------

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        # 获取源模型中的日志条目
        source_model = self.sourceModel()
        if source_model is None:
            return True

        # 级别过滤
        if self._allowed_levels is not None:
            level_index = source_model.index(source_row, 2, source_parent)
            level_name = source_model.data(level_index)
            if level_name:
                try:
                    level = LogLevel[level_name]
                    if level not in self._allowed_levels:
                        return False
                except KeyError:
                    pass

        # 模块过滤
        if self._module_filter:
            module_index = source_model.index(source_row, 3, source_parent)
            module = source_model.data(module_index) or ""
            if self._module_filter.lower() not in module.lower():
                return False

        # 文本过滤
        if self._text_filter:
            msg_index = source_model.index(source_row, 4, source_parent)
            message = (source_model.data(msg_index) or "").lower()
            if self._text_filter not in message:
                return False

        return True
