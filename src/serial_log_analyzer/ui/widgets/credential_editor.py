"""凭据编辑：来源选择 + 目标标识 + 写入系统钥匙串。

Profile 配置与密钥的写入目标依旧分离：来源与标识（`name` / `env_var`）随 Profile 写进 YAML，
密钥只进系统钥匙串，且只在用户点「保存到钥匙串」时才写；界面不读回密钥内容，只用
「已保存 / 未设置」表示状态（见 ``docs/protocols/credentials.md`` §4）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.errors import ConfigError, CredentialError
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.ports import KeyringStore

__all__ = ["CredentialEditor"]

_SOURCES: tuple[tuple[str, CredentialKind], ...] = (
    ("系统钥匙串", CredentialKind.KEYRING),
    ("环境变量", CredentialKind.ENVIRONMENT),
)


class CredentialEditor(QWidget):
    """凭据来源与密钥编辑。

    参数:
        keyring: 系统钥匙串适配器。
        parent: 可选父对象。
    """

    def __init__(self, keyring: KeyringStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._keyring = keyring
        self._keyring_available = _keyring_available(keyring)
        self._profile_id = ""
        self._build()

    def load(self, credential: CredentialRef, profile_id: str) -> None:
        """按 Profile 的声明填入界面。"""

        self._profile_id = profile_id
        index = self._source.findData(credential.kind)
        self._source.setCurrentIndex(index if index >= 0 else 0)
        self._target.setText(credential.name or credential.env_var or "")
        self._secret.clear()
        self._sync_fields()

    def clear(self) -> None:
        """没有可用 Profile 时清空。"""

        self._profile_id = ""
        self._target.clear()
        self._secret.clear()
        self._sync_fields()

    def credential(self) -> CredentialRef:
        """读回将要写进 Profile 的凭据引用。

        异常:
            ConfigError: 缺少目标标识（钥匙串账号名 / 环境变量名）。
        """

        kind = self._source.currentData()
        target = self._target.text().strip()
        if kind is CredentialKind.KEYRING:
            account = target or self._profile_id
            if not account:
                raise ConfigError("凭据缺少钥匙串账号名")
            return CredentialRef(kind=kind, name=account)
        if not target:
            raise ConfigError("凭据缺少环境变量名")
        return CredentialRef(kind=kind, env_var=target)

    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._source = QComboBox()
        self._source.setObjectName("credential-source")
        for label, kind in _SOURCES:
            self._source.addItem(label, kind)
        self._source.currentIndexChanged.connect(self._sync_fields)
        row.addWidget(self._source)
        self._target = QLineEdit()
        self._target.setObjectName("credential-target")
        row.addWidget(self._target, stretch=1)
        layout.addLayout(row)

        secret_row = QHBoxLayout()
        secret_row.setSpacing(6)
        self._secret = QLineEdit()
        self._secret.setObjectName("credential-secret")
        self._secret.setEchoMode(QLineEdit.EchoMode.Password)
        secret_row.addWidget(self._secret, stretch=1)
        self._show = QCheckBox("显示")
        self._show.setObjectName("credential-show")
        self._show.toggled.connect(self._toggle_echo)
        secret_row.addWidget(self._show)
        layout.addLayout(secret_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self._save = QPushButton("保存到钥匙串")
        self._save.setObjectName("credential-save")
        self._save.clicked.connect(self._save_secret)
        buttons.addWidget(self._save)
        self._clear = QPushButton("清除已保存")
        self._clear.setObjectName("credential-clear")
        self._clear.clicked.connect(self._clear_secret)
        buttons.addWidget(self._clear)
        buttons.addStretch()
        self._state = QLabel()
        self._state.setObjectName("credential-state")
        buttons.addWidget(self._state)
        layout.addLayout(buttons)

        self._sync_fields()

    def _sync_fields(self) -> None:
        """按当前来源调整字段文案与可用性，并刷新状态。"""

        keyring = self._source.currentData() is CredentialKind.KEYRING
        self._target.setPlaceholderText("钥匙串账号名（留空用 profile_id）" if keyring else "环境变量名")
        self._secret.setPlaceholderText("API Key（只写入系统钥匙串）")
        self._secret.setEnabled(keyring)
        self._show.setEnabled(keyring)
        self._save.setEnabled(keyring and self._keyring_available)
        self._save.setToolTip("" if self._keyring_available else "系统钥匙串不可用")
        self._clear.setEnabled(keyring and self._keyring_available)
        self._refresh_state()

    def _refresh_state(self) -> None:
        """刷新「已保存 / 未设置」状态；不读取也不回显密钥内容。"""

        if self._source.currentData() is not CredentialKind.KEYRING:
            self._state.setText("密钥来自环境变量")
            return
        if not self._keyring_available:
            self._state.setText("系统钥匙串不可用")
            return
        try:
            saved = bool(self._keyring.read(self._account()))
        except CredentialError as exc:
            self._state.setText(f"读取失败：{exc}")
            return
        self._state.setText("已保存" if saved else "未设置")

    def _account(self) -> str:
        """当前要读写的钥匙串账号名。"""

        return self._target.text().strip() or self._profile_id

    def _save_secret(self) -> None:
        """把输入的密钥写入钥匙串（空输入或失败时提示且不落盘）。"""

        value = self._secret.text().strip()
        if not value:
            QMessageBox.warning(self, "无法保存", "请先输入 API Key。")
            return
        try:
            self._keyring.save(self._account(), value)
        except CredentialError as exc:
            QMessageBox.critical(self, "写入系统钥匙串失败", str(exc))
            return
        self._secret.clear()
        self._refresh_state()

    def _clear_secret(self) -> None:
        """删除钥匙串中该账号的密钥（需二次确认）。"""

        account = self._account()
        confirmed = QMessageBox.question(
            self, "确认删除", f"确定要删除 {account} 在系统钥匙串中的密钥吗？"
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            self._keyring.delete(account)
        except CredentialError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self._refresh_state()

    def _toggle_echo(self, shown: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self._secret.setEchoMode(mode)


def _keyring_available(keyring: KeyringStore) -> bool:
    """探测钥匙串可用性；任何异常都视为不可用。"""

    try:
        return bool(keyring.available)
    except Exception:  # noqa: BLE001 - 第三方钥匙串后端可能抛任意异常
        return False
