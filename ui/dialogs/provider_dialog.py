"""
Provider 配置对话框 - LLM 提供商配置管理
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QDialogButtonBox,
    QGroupBox,
)


class ProviderDialog(QDialog):
    """
    LLM Provider 配置对话框
    
    左侧：已配置的 Profile 列表
    右侧：编辑选中的 Profile
    """

    def __init__(self, provider_loader, parent=None):
        super().__init__(parent)
        self._loader = provider_loader
        self.setWindowTitle("LLM Provider 配置")
        self.setMinimumSize(600, 400)
        self._setup_ui()
        self._load_profiles()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)

        # 左侧列表
        left_layout = QVBoxLayout()
        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.profile_list)

        btn_layout = QHBoxLayout()
        self.new_btn = QPushButton("新建")
        self.delete_btn = QPushButton("删除")
        btn_layout.addWidget(self.new_btn)
        btn_layout.addWidget(self.delete_btn)
        left_layout.addLayout(btn_layout)

        layout.addLayout(left_layout)

        # 右侧编辑区
        right_group = QGroupBox("Profile 详情")
        right_layout = QFormLayout(right_group)

        self.name_edit = QLineEdit()
        right_layout.addRow("名称:", self.name_edit)

        self.adapter_combo = QComboBox()
        self.adapter_combo.addItems(["openai_compatible", "openai_responses", "anthropic", "gemini"])
        right_layout.addRow("适配器:", self.adapter_combo)

        self.base_url_edit = QLineEdit()
        right_layout.addRow("Base URL:", self.base_url_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("例如: gpt-4o-mini")
        right_layout.addRow("模型:", self.model_edit)

        self.credential_combo = QComboBox()
        self.credential_combo.addItems(["keyring", "environment", "runtime"])
        right_layout.addRow("凭据类型:", self.credential_combo)

        self.credential_name_edit = QLineEdit()
        self.credential_name_edit.setPlaceholderText("Keyring 名称或环境变量名")
        right_layout.addRow("凭据标识:", self.credential_name_edit)

        layout.addWidget(right_group)

        # 底部按钮
        bottom_layout = QVBoxLayout()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        bottom_layout.addWidget(buttons)
        layout.addLayout(bottom_layout)

    def _load_profiles(self) -> None:
        """加载已有的 Profile 列表"""
        # TODO: 从 loader 加载实际 profile
        self.profile_list.clear()
        self.profile_list.addItem("默认 Profile")

    def _on_profile_selected(self, row: int) -> None:
        """选中某个 Profile 时加载详情"""
        # TODO: 加载实际 profile 数据
        pass

    def _on_save(self) -> None:
        """保存配置"""
        # TODO: 调用 loader 保存
        self.accept()
