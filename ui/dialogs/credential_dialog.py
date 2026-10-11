"""
凭据输入对话框 - 运行时输入 API Key 等凭据
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QLabel,
    QDialogButtonBox,
    QMessageBox,
)


class CredentialDialog(QDialog):
    """
    运行时凭据输入对话框
    
    当 Keyring 中没有存储凭据时，弹出此对话框让用户输入
    """

    def __init__(self, credential_name: str, description: str = "", parent=None):
        super().__init__(parent)
        self._credential_name = credential_name
        self._secret: str | None = None

        self.setWindowTitle("输入凭据")
        self.setMinimumWidth(400)
        self._setup_ui(description)

    def _setup_ui(self, description: str) -> None:
        layout = QVBoxLayout(self)

        # 说明文字
        if description:
            label = QLabel(description)
            label.setWordWrap(True)
            layout.addWidget(label)

        form = QFormLayout()

        # 凭据名称（只读）
        name_label = QLabel(self._credential_name)
        name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("凭据:", name_label)

        # 密钥输入
        self.secret_edit = QLineEdit()
        self.secret_edit.setEchoMode(QLineEdit.Password)
        self.secret_edit.setPlaceholderText("请输入 API Key / 密钥")
        form.addRow("密钥:", self.secret_edit)

        # 显示密码选项
        from PySide6.QtWidgets import QCheckBox
        self.show_cb = QCheckBox("显示明文")
        self.show_cb.toggled.connect(self._on_show_toggled)
        form.addRow("", self.show_cb)

        layout.addLayout(form)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_show_toggled(self, checked: bool) -> None:
        """切换密码显示"""
        self.secret_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _on_accept(self) -> None:
        """验证并保存输入"""
        secret = self.secret_edit.text().strip()
        if not secret:
            QMessageBox.warning(self, "提示", "请输入密钥")
            return

        self._secret = secret
        self.accept()

    @property
    def secret_value(self) -> str | None:
        """获取输入的密钥"""
        return self._secret

    @classmethod
    def get_credential(cls, name: str, description: str = "", parent=None) -> str | None:
        """
        静态方法：弹出对话框并返回输入的密钥
        
        Returns:
            用户输入的密钥，取消则返回 None
        """
        dialog = cls(name, description, parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.secret_value
        return None
