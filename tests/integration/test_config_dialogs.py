"""配置类对话框的集成测试（需要 Qt，使用 pytest-qt）。

覆盖「设置」「模型服务」「API Key」三个对话框与设置存储 / Profile 存储 / 钥匙串适配器的协作，
并确认界面文案与 DESIGN.md §13 的凭据规则一致（运行时输入默认不写钥匙串）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from serial_log_analyzer.core.llm.profile_loader import load_profiles
from serial_log_analyzer.io.credentials.keyring_store import KeyringStoreAdapter
from serial_log_analyzer.io.resources import CompositeResourceLoader
from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS, QtSettingsStore
from serial_log_analyzer.io.storage.profile_store import ProfileStore
from serial_log_analyzer.ui.dialogs.credential_dialog import CredentialDialog
from serial_log_analyzer.ui.dialogs.provider_dialog import ProviderDialog
from serial_log_analyzer.ui.dialogs.settings_dialog import SettingsDialog

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def store(tmp_path) -> QtSettingsStore:
    return QtSettingsStore(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))


@pytest.fixture
def profiles():
    return load_profiles(CompositeResourceLoader.from_environment(_REPO_ROOT))


class FakeKeyringBackend:
    """keyring 后端替身：只需 get/set/delete_password 三个方法。"""

    def __init__(self, *, fail_on_save: bool = False) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail_on_save = fail_on_save

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        if self.fail_on_save:
            raise RuntimeError("钥匙串写入失败")
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


class UnavailableKeyring:
    """钥匙串不可用替身。"""

    available = False

    def read(self, credential_id: str) -> str | None:  # pragma: no cover - 不应被调用
        return None

    def save(self, credential_id: str, secret: str) -> None:  # pragma: no cover - 不应被调用
        raise AssertionError("钥匙串不可用时不应写入")

    def delete(self, credential_id: str) -> bool:  # pragma: no cover - 不应被调用
        return False


# --------------------------------------------------------------------------- 设置对话框


def test_settings_dialog_shows_current_values(qtbot, store: QtSettingsStore) -> None:
    store.set(SETTINGS_KEYS.AUTOSCROLL, False)
    store.set(SETTINGS_KEYS.LOG_CAPACITY, 20_000)
    store.set(SETTINGS_KEYS.LOG_LEVEL, "DEBUG")
    store.set(SETTINGS_KEYS.EXPORT_DIR, "D:/logs")

    dialog = SettingsDialog(store)
    qtbot.addWidget(dialog)

    assert dialog.findChild(QCheckBox, "settings-autoscroll").isChecked() is False
    assert dialog.findChild(QSpinBox, "settings-capacity").value() == 20_000
    assert dialog.findChild(QComboBox, "settings-log-level").currentText() == "DEBUG"
    assert dialog.findChild(QLineEdit, "settings-export-dir").text() == "D:/logs"


def test_settings_dialog_uses_defaults_when_empty(qtbot, store: QtSettingsStore) -> None:
    dialog = SettingsDialog(store)
    qtbot.addWidget(dialog)

    assert dialog.findChild(QSpinBox, "settings-capacity").value() == 100_000
    assert dialog.findChild(QComboBox, "settings-log-level").currentText() == "INFO"
    assert dialog.findChild(QLineEdit, "settings-export-dir").text() == ""


def test_settings_dialog_accept_persists_values(qtbot, store: QtSettingsStore) -> None:
    dialog = SettingsDialog(store)
    qtbot.addWidget(dialog)
    dialog.findChild(QCheckBox, "settings-autoscroll").setChecked(False)
    dialog.findChild(QSpinBox, "settings-capacity").setValue(1_500)
    dialog.findChild(QComboBox, "settings-log-level").setCurrentText("ERROR")
    dialog.findChild(QLineEdit, "settings-export-dir").setText("  D:/exports  ")

    dialog.accept()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert store.get_bool(SETTINGS_KEYS.AUTOSCROLL, True) is False
    assert store.get_int(SETTINGS_KEYS.LOG_CAPACITY, 0) == 1_500
    assert store.get(SETTINGS_KEYS.LOG_LEVEL) == "ERROR"
    assert store.get(SETTINGS_KEYS.EXPORT_DIR) == "D:/exports"


# --------------------------------------------------------------------------- 模型服务对话框


def test_provider_dialog_lists_profiles(qtbot, profiles, tmp_path) -> None:
    dialog = ProviderDialog(profiles, store=ProfileStore(tmp_path))
    qtbot.addWidget(dialog)

    assert dialog.selected_profile_id() == "deepseek"
    assert dialog.findChild(QLineEdit, "provider-model").text() == "deepseek-chat"
    assert dialog.findChild(QLabel, "provider-adapter").text() == "openai-compatible"
    assert "系统钥匙串" in dialog.findChild(QLabel, "provider-credential").text()


def test_provider_dialog_switches_profile(qtbot, profiles, tmp_path) -> None:
    dialog = ProviderDialog(profiles, store=ProfileStore(tmp_path))
    qtbot.addWidget(dialog)

    combo = dialog.findChild(QComboBox, "provider-combo")
    combo.setCurrentIndex(combo.findData("ollama-local"))

    assert dialog.selected_profile_id() == "ollama-local"
    assert dialog.findChild(QLineEdit, "provider-base-url").text().startswith("http://localhost")
    assert "运行时临时输入" in dialog.findChild(QLabel, "provider-credential").text()


def test_provider_dialog_saves_edits_to_user_config(qtbot, profiles, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    store = ProfileStore(tmp_path)
    dialog = ProviderDialog(profiles, store=store)
    qtbot.addWidget(dialog)
    dialog.findChild(QLineEdit, "provider-model").setText("deepseek-reasoner")
    dialog.findChild(QSpinBox, "provider-timeout").setValue(300)

    qtbot.mouseClick(
        dialog.findChild(QPushButton, "provider-save"), Qt.MouseButton.LeftButton
    )

    saved = Path(dialog.saved_path())
    assert saved == store.path_for("deepseek")
    text = store.load_text("deepseek")
    assert "deepseek-reasoner" in text
    assert "request_timeout_seconds: 300" in text


def test_provider_dialog_without_profiles(qtbot, tmp_path) -> None:
    dialog = ProviderDialog([], store=ProfileStore(tmp_path))
    qtbot.addWidget(dialog)

    assert dialog.selected_profile_id() == ""
    assert dialog.findChild(QLabel, "provider-adapter").text() == "（无可用 Profile）"


# --------------------------------------------------------------------------- API Key 对话框


def test_credential_dialog_runtime_only_by_default(qtbot) -> None:
    backend = FakeKeyringBackend()
    dialog = CredentialDialog(KeyringStoreAdapter(backend=backend), "deepseek")
    qtbot.addWidget(dialog)
    dialog.findChild(QLineEdit, "credential-secret").setText("sk-runtime")

    dialog.accept()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert dialog.secret() == "sk-runtime"
    assert dialog.save_to_keyring() is False
    assert backend.values == {}


def test_credential_dialog_saves_to_keyring_when_checked(qtbot) -> None:
    backend = FakeKeyringBackend()
    dialog = CredentialDialog(KeyringStoreAdapter(backend=backend), "deepseek")
    qtbot.addWidget(dialog)
    dialog.findChild(QLineEdit, "credential-secret").setText("sk-saved")
    dialog.findChild(QCheckBox, "credential-save-keyring").setChecked(True)

    dialog.accept()

    assert backend.values == {("SerialLogAnalyzer", "deepseek"): "sk-saved"}


def test_credential_dialog_uses_declared_account_name(qtbot) -> None:
    backend = FakeKeyringBackend()
    dialog = CredentialDialog(
        KeyringStoreAdapter(backend=backend),
        "deepseek",
        account="deepseek-prod",
    )
    qtbot.addWidget(dialog)
    dialog.findChild(QLineEdit, "credential-secret").setText("sk-prod")
    dialog.findChild(QCheckBox, "credential-save-keyring").setChecked(True)

    dialog.accept()

    assert dialog.account() == "deepseek-prod"
    assert backend.values == {("SerialLogAnalyzer", "deepseek-prod"): "sk-prod"}


def test_credential_dialog_falls_back_to_profile_id_as_account(qtbot) -> None:
    dialog = CredentialDialog(KeyringStoreAdapter(backend=FakeKeyringBackend()), "deepseek", account="  ")
    qtbot.addWidget(dialog)

    assert dialog.account() == "deepseek"


def test_credential_dialog_toggles_echo_mode(qtbot) -> None:
    dialog = CredentialDialog(KeyringStoreAdapter(backend=FakeKeyringBackend()), "deepseek")
    qtbot.addWidget(dialog)
    secret = dialog.findChild(QLineEdit, "credential-secret")

    assert secret.echoMode() == QLineEdit.EchoMode.Password

    dialog.findChild(QCheckBox, "credential-show").setChecked(True)

    assert secret.echoMode() == QLineEdit.EchoMode.Normal


def test_credential_dialog_blocks_empty_secret_when_saving(qtbot, monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warnings.append(str(args[2]))
    )
    backend = FakeKeyringBackend()
    dialog = CredentialDialog(KeyringStoreAdapter(backend=backend), "deepseek")
    qtbot.addWidget(dialog)
    dialog.findChild(QCheckBox, "credential-save-keyring").setChecked(True)

    dialog.accept()

    assert dialog.result() == int(QDialog.DialogCode.Rejected)
    assert warnings and "请先输入 API Key" in warnings[0]
    assert backend.values == {}


def test_credential_dialog_keeps_open_when_keyring_write_fails(qtbot, monkeypatch) -> None:
    errors: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append(str(args[2])))
    dialog = CredentialDialog(KeyringStoreAdapter(backend=FakeKeyringBackend(fail_on_save=True)), "deepseek")
    qtbot.addWidget(dialog)
    dialog.findChild(QLineEdit, "credential-secret").setText("sk-fail")
    dialog.findChild(QCheckBox, "credential-save-keyring").setChecked(True)

    dialog.accept()

    assert dialog.result() == int(QDialog.DialogCode.Rejected)
    assert errors and "钥匙串" in errors[0]


def test_credential_dialog_disables_saving_without_keyring(qtbot) -> None:
    dialog = CredentialDialog(UnavailableKeyring(), "deepseek")
    qtbot.addWidget(dialog)

    assert dialog.save_to_keyring() is False
    assert dialog.findChild(QCheckBox, "credential-save-keyring").isEnabled() is False
    assert dialog.findChild(QPushButton, "credential-clear").isEnabled() is False
    assert "系统钥匙串不可用" in dialog.findChild(QLabel, "credential-hint").text()


def test_credential_dialog_clear_saved_secret(qtbot, monkeypatch) -> None:
    backend = FakeKeyringBackend()
    keyring = KeyringStoreAdapter(backend=backend)
    keyring.save("deepseek", "sk-old")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    dialog = CredentialDialog(keyring, "deepseek")
    qtbot.addWidget(dialog)

    qtbot.mouseClick(
        dialog.findChild(QPushButton, "credential-clear"), Qt.MouseButton.LeftButton
    )

    assert backend.values == {}
