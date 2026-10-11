"""凭据管理对话框：输入 / 更新 / 删除某 Profile 的 API Key。

行为约定（见 ``DESIGN.md`` §13）：
- 输入内容默认仅用于本次会话，不自动写入系统钥匙串；
- 用户勾选“保存到系统钥匙串”时才调用 :meth:`KeyringStore.save`；
- 钥匙串不可用时置灰保存选项并提示回退来源。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from serial_log_analyzer.core.errors import CredentialError
from serial_log_analyzer.core.ports import KeyringStore

__all__ = ["CredentialDialog"]


class CredentialDialog(QDialog):
    """API Key 输入与保存对话框。

    参数:
        keyring: 钥匙串适配器（用于探测可用性与保存）。
        profile_id: 目标 Profile 标识，用于界面标题。
        parent: 可选父窗口。
        account: 钥匙串账号名；缺省取 ``profile_id``。调用方应传入
            ``ProviderProfile.credential.name``（见 ``docs/protocols/credentials.md``）。
    """

    def __init__(
        self,
        keyring: KeyringStore,
        profile_id: str,
        parent: QDialog | None = None,
        *,
        account: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._keyring = keyring
        self._profile_id = profile_id
        self._account = (account or "").strip() or profile_id
        self._available = _keyring_available(keyring)
        self.setWindowTitle(f"API Key — {profile_id}")

        self._secret = QLineEdit()
        self._secret.setObjectName("credential-secret")
        self._secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._secret.setPlaceholderText("粘贴或输入 API Key")

        self._show = QCheckBox("显示密钥")
        self._show.setObjectName("credential-show")
        self._show.toggled.connect(self._toggle_echo)

        secret_row = QVBoxLayout()
        secret_row.addWidget(self._secret)
        secret_row.addWidget(self._show)

        self._save = QCheckBox("保存到系统钥匙串")
        self._save.setObjectName("credential-save-keyring")
        self._save.setEnabled(self._available)
        if not self._available:
            self._save.setToolTip("系统钥匙串不可用，密钥仅用于本次会话")

        self._hint = QLabel(_hint_text(self._available))
        self._hint.setObjectName("credential-hint")
        self._hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("API Key", secret_row)
        form.addRow("保存", self._save)

        clear = QPushButton("清除已保存的密钥")
        clear.setObjectName("credential-clear")
        clear.setEnabled(self._available)
        clear.clicked.connect(self._clear_saved)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addWidget(clear)
        layout.addWidget(buttons)

    def secret(self) -> str:
        """返回用户输入的密钥（未输入时为空串）。"""

        return self._secret.text().strip()

    def save_to_keyring(self) -> bool:
        """返回用户是否勾选了“保存到系统钥匙串”。"""

        return self._available and self._save.isChecked()

    def account(self) -> str:
        """返回本对话框写入 / 删除时使用的钥匙串账号名。"""

        return self._account

    def accept(self) -> None:
        """确认输入；勾选了保存且已输入密钥时写入系统钥匙串。

        仅当用户明确勾选时才写钥匙串；写入失败会提示并保持对话框打开。
        """

        if self.save_to_keyring():
            value = self.secret()
            if not value:
                QMessageBox.warning(self, "无法保存", "请先输入 API Key，再勾选保存到系统钥匙串。")
                return
            try:
                self._keyring.save(self._account, value)
            except CredentialError as exc:
                QMessageBox.critical(self, "写入系统钥匙串失败", str(exc))
                return
        super().accept()

    def _toggle_echo(self, shown: bool) -> None:
        """切换密钥的明文 / 密文显示。"""
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self._secret.setEchoMode(mode)

    def _clear_saved(self) -> None:
        """删除钥匙串中该账号已保存的密钥（需二次确认）。"""
        confirmed = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除 {self._account} 在系统钥匙串中的密钥吗？",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = self._keyring.delete(self._account)
        except CredentialError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        QMessageBox.information(self, "已处理", "已删除保存的密钥。" if removed else "未找到已保存的密钥。")


def _keyring_available(keyring: object) -> bool:
    """探测钥匙串可用性；任何异常都视为不可用。"""
    try:
        return bool(getattr(keyring, "available", False))
    except Exception:  # 第三方钥匙串后端可能抛任意异常，统一按不可用处理
        return False


def _hint_text(available: bool) -> str:
    """生成钥匙串可用性提示。"""
    if available:
        return (
            "未勾选「保存到系统钥匙串」时，密钥仅用于本次会话，不会写入系统钥匙串；"
            "未提供密钥且凭据声明了环境变量时，会回退到该环境变量。"
        )
    return (
        "系统钥匙串不可用：密钥仅用于本次会话，无法保存；"
        "未提供密钥且凭据声明了环境变量时，会回退到该环境变量。"
    )
