"""
设置对话框 - 应用全局设置
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QSpinBox,
    QDialogButtonBox,
    QCheckBox,
)


class SettingsDialog(QDialog):
    """
    设置对话框
    
    包含：
    - 最大日志行数
    - 自动滚动开关
    - 其他 UI 选项
    """

    def __init__(self, settings_store, parent=None):
        super().__init__(parent)
        self._settings = settings_store
        self.setWindowTitle("设置")
        self.setMinimumWidth(400)
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 最大行数
        self.max_rows_spin = QSpinBox()
        self.max_rows_spin.setRange(1000, 1000000)
        self.max_rows_spin.setSingleStep(10000)
        form.addRow("最大日志行数:", self.max_rows_spin)

        # 自动滚动
        self.auto_scroll_cb = QCheckBox("新日志自动滚动到底部")
        form.addRow("", self.auto_scroll_cb)

        layout.addLayout(form)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_settings(self) -> None:
        """从 settings store 加载设置"""
        self.max_rows_spin.setValue(int(self._settings.get("ui.max_rows", 100000)))
        self.auto_scroll_cb.setChecked(bool(self._settings.get("ui.auto_scroll", True)))

    def _on_accept(self) -> None:
        """保存设置并关闭"""
        self._settings.set("ui.max_rows", self.max_rows_spin.value())
        self._settings.set("ui.auto_scroll", self.auto_scroll_cb.isChecked())
        self.accept()
