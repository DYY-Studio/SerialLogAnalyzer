"""配置类对话框的集成测试（需要 Qt，使用 pytest-qt）。

覆盖「设置」「模型服务」两个对话框与设置存储 / Profile 存储 / 钥匙串适配器的协作：
凭据来源随 Profile 落盘，密钥只写系统钥匙串（见 DESIGN.md §13 与 docs/protocols/credentials.md §4）。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
)

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.adapter_loader import load_adapters
from serial_log_analyzer.core.llm.profile_loader import load_profile, load_profiles
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef, ModelOption
from serial_log_analyzer.io.credentials.keyring_store import KeyringStoreAdapter
from serial_log_analyzer.io.resources import CompositeResourceLoader
from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS, QtSettingsStore
from serial_log_analyzer.io.storage.profile_store import ProfileStore
from serial_log_analyzer.ui.dialogs.provider_dialog import ProviderDialog
from serial_log_analyzer.ui.dialogs.settings_dialog import SettingsDialog
from serial_log_analyzer.ui.widgets.credential_editor import CredentialEditor

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def store(tmp_path) -> QtSettingsStore:
    return QtSettingsStore(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))


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


def _editor(qtbot, *, keyring=None, credential: CredentialRef | None = None) -> CredentialEditor:
    editor = CredentialEditor(keyring if keyring is not None else KeyringStoreAdapter(backend=FakeKeyringBackend()))
    qtbot.addWidget(editor)
    editor.load(credential or CredentialRef(kind=CredentialKind.KEYRING, name="deepseek"), "deepseek")
    return editor


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


def _provider_dialog(tmp_path, *, discovery=None, keyring=None) -> ProviderDialog:
    """用「临时用户目录 + 仓库内置」构造对话框：reload 与落盘共用同一份资源。"""

    loader = CompositeResourceLoader([Path(tmp_path), _REPO_ROOT])
    return ProviderDialog(
        load_profiles(loader),
        load_adapters(loader),
        keyring=keyring if keyring is not None else KeyringStoreAdapter(backend=FakeKeyringBackend()),
        reload=lambda: load_profiles(loader),
        store=ProfileStore(tmp_path),
        discovery=discovery,
    )


def test_provider_dialog_lists_profiles(qtbot, tmp_path) -> None:
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)

    assert dialog.selected_profile_id() == "deepseek"
    assert dialog.findChild(QComboBox, "provider-model").currentText() == "deepseek-chat"
    assert dialog.findChild(QComboBox, "provider-adapter").currentData() == "openai-compatible"
    assert dialog.findChild(QComboBox, "credential-source").currentData() is CredentialKind.KEYRING
    assert dialog.findChild(QLineEdit, "credential-target").text() == "deepseek"


def test_provider_dialog_switches_profile(qtbot, tmp_path) -> None:
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)

    combo = dialog.findChild(QComboBox, "provider-combo")
    combo.setCurrentIndex(combo.findData("ollama-local"))

    assert dialog.selected_profile_id() == "ollama-local"
    assert dialog.findChild(QLineEdit, "provider-base-url").text().startswith("http://localhost")
    assert dialog.findChild(QComboBox, "credential-source").currentData() is CredentialKind.ENVIRONMENT
    assert dialog.findChild(QLineEdit, "credential-target").text() == "OLLAMA_API_KEY"


def test_provider_dialog_saves_credential_source_to_yaml(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    store = ProfileStore(tmp_path)
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)
    source = dialog.findChild(QComboBox, "credential-source")
    source.setCurrentIndex(source.findData(CredentialKind.ENVIRONMENT))
    dialog.findChild(QLineEdit, "credential-target").setText("MY_DEEPSEEK_KEY")

    qtbot.mouseClick(dialog.findChild(QPushButton, "provider-save"), Qt.MouseButton.LeftButton)

    text = store.load_text("deepseek") or ""
    assert "kind: environment" in text
    assert "env_var: MY_DEEPSEEK_KEY" in text


def test_provider_dialog_saves_edits_to_user_config(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    store = ProfileStore(tmp_path)
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)
    dialog.findChild(QComboBox, "provider-model").setCurrentText("deepseek-reasoner")
    dialog.findChild(QSpinBox, "provider-timeout").setValue(300)
    dialog.findChild(QPlainTextEdit, "provider-extra-body").setPlainText('{"top_p": 0.9}')
    dialog.findChild(QComboBox, "provider-adapter").setCurrentIndex(
        dialog.findChild(QComboBox, "provider-adapter").findData("openai-responses")
    )

    qtbot.mouseClick(dialog.findChild(QPushButton, "provider-save"), Qt.MouseButton.LeftButton)

    assert Path(dialog.saved_path()) == store.path_for("deepseek")
    text = store.load_text("deepseek") or ""
    assert "deepseek-reasoner" in text
    assert "request_timeout_seconds: 300" in text
    assert "adapter_id: openai-responses" in text
    assert "top_p" in text


def test_provider_dialog_without_profiles(qtbot, tmp_path) -> None:
    dialog = ProviderDialog(
        [],
        [],
        keyring=KeyringStoreAdapter(backend=FakeKeyringBackend()),
        reload=lambda: [],
        store=ProfileStore(tmp_path),
    )
    qtbot.addWidget(dialog)

    assert dialog.selected_profile_id() == ""
    assert dialog.findChild(QComboBox, "provider-adapter").count() == 0
    assert dialog.findChild(QLineEdit, "credential-target").text() == ""
    assert dialog.findChild(QPushButton, "provider-save").isEnabled() is False


def test_provider_dialog_creates_profile_in_user_config(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("team-a", True))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.findChild(QPushButton, "provider-new"), Qt.MouseButton.LeftButton)

    store = ProfileStore(tmp_path)
    assert store.exists("team-a")
    assert "team-a" in (store.load_text("team-a") or "")
    combo = dialog.findChild(QComboBox, "provider-combo")
    assert dialog.selected_profile_id() == "team-a"
    assert [combo.itemData(index) for index in range(combo.count())].count("team-a") == 1


def test_provider_dialog_creation_rejects_bad_id(qtbot, tmp_path, monkeypatch) -> None:
    warned: list[str] = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Team A", True))
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warned.append(args[2] if args else "")
    )
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.findChild(QPushButton, "provider-new"), Qt.MouseButton.LeftButton)

    assert warned and "profile_id" in warned[0]
    assert not ProfileStore(tmp_path).exists("team-a")


def test_provider_dialog_delete_falls_back_to_builtin(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    store = ProfileStore(tmp_path)
    builtin = load_profile(CompositeResourceLoader.from_environment(_REPO_ROOT), "deepseek")
    store.save(dataclasses.replace(builtin, model="my-deepseek"))
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.findChild(QComboBox, "provider-model").currentText() == "my-deepseek"

    qtbot.mouseClick(dialog.findChild(QPushButton, "provider-delete"), Qt.MouseButton.LeftButton)

    assert not store.exists("deepseek")
    assert dialog.selected_profile_id() == "deepseek"
    assert dialog.findChild(QComboBox, "provider-model").currentText() == "deepseek-chat"


def test_provider_dialog_refuses_to_delete_builtin(qtbot, tmp_path, monkeypatch) -> None:
    warned: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warned.append(args[2] if args else "")
    )
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.findChild(QPushButton, "provider-delete"), Qt.MouseButton.LeftButton)

    assert warned and "内置" in warned[0]


def test_provider_dialog_rejects_non_mapping_extra_body(qtbot, tmp_path, monkeypatch) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args, **kwargs: errors.append(args[2] if args else "")
    )
    dialog = _provider_dialog(tmp_path)
    qtbot.addWidget(dialog)
    dialog.findChild(QPlainTextEdit, "provider-extra-body").setPlainText("[1, 2]")

    qtbot.mouseClick(dialog.findChild(QPushButton, "provider-save"), Qt.MouseButton.LeftButton)

    assert errors and "extra_body" in errors[0]
    assert ProfileStore(tmp_path).load_text("deepseek") is None


def test_provider_dialog_fetches_models_with_edited_fields(qtbot, tmp_path) -> None:
    calls: list[tuple[str, str, str]] = []

    class FakeDiscovery:
        def fetch(self, adapter, profile, on_done, on_error) -> None:
            calls.append((adapter.adapter_id, profile.base_url, profile.model))
            on_done([ModelOption("m-small", "M Small"), ModelOption("m-large", "M Large")])

    dialog = _provider_dialog(tmp_path, discovery=FakeDiscovery())
    qtbot.addWidget(dialog)
    dialog.findChild(QLineEdit, "provider-base-url").setText("https://example.test/v1")
    dialog.findChild(QComboBox, "provider-model").setCurrentText("deepseek-chat")

    qtbot.mouseClick(
        dialog.findChild(QPushButton, "provider-model-fetch"), Qt.MouseButton.LeftButton
    )

    model = dialog.findChild(QComboBox, "provider-model")
    assert [model.itemData(index) for index in range(model.count())] == ["m-small", "m-large"]
    assert calls == [("openai-compatible", "https://example.test/v1", "deepseek-chat")]
    assert "2" in dialog.findChild(QLabel, "provider-status").text()


# --------------------------------------------------------------------------- 凭据编辑器


def test_credential_editor_saves_to_keyring(qtbot) -> None:
    backend = FakeKeyringBackend()
    editor = _editor(qtbot, keyring=KeyringStoreAdapter(backend=backend))

    assert editor.credential() == CredentialRef(kind=CredentialKind.KEYRING, name="deepseek")
    editor.findChild(QLineEdit, "credential-secret").setText("sk-saved")
    qtbot.mouseClick(editor.findChild(QPushButton, "credential-save"), Qt.MouseButton.LeftButton)

    assert backend.values == {("SerialLogAnalyzer", "deepseek"): "sk-saved"}
    assert editor.findChild(QLineEdit, "credential-secret").text() == ""  # 不回显已保存内容
    assert editor.findChild(QLabel, "credential-state").text() == "已保存"


def test_credential_editor_uses_target_as_account_name(qtbot) -> None:
    backend = FakeKeyringBackend()
    editor = _editor(qtbot, keyring=KeyringStoreAdapter(backend=backend))
    editor.findChild(QLineEdit, "credential-target").setText("deepseek-prod")
    editor.findChild(QLineEdit, "credential-secret").setText("sk-prod")

    qtbot.mouseClick(editor.findChild(QPushButton, "credential-save"), Qt.MouseButton.LeftButton)

    assert editor.credential() == CredentialRef(kind=CredentialKind.KEYRING, name="deepseek-prod")
    assert backend.values == {("SerialLogAnalyzer", "deepseek-prod"): "sk-prod"}


def test_credential_editor_blocks_empty_secret(qtbot, monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(str(args[2])))
    backend = FakeKeyringBackend()
    editor = _editor(qtbot, keyring=KeyringStoreAdapter(backend=backend))

    qtbot.mouseClick(editor.findChild(QPushButton, "credential-save"), Qt.MouseButton.LeftButton)

    assert warnings and "请先输入 API Key" in warnings[0]
    assert backend.values == {}


def test_credential_editor_reports_keyring_write_failure(qtbot, monkeypatch) -> None:
    errors: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append(str(args[2])))
    editor = _editor(qtbot, keyring=KeyringStoreAdapter(backend=FakeKeyringBackend(fail_on_save=True)))
    editor.findChild(QLineEdit, "credential-secret").setText("sk-fail")

    qtbot.mouseClick(editor.findChild(QPushButton, "credential-save"), Qt.MouseButton.LeftButton)

    assert errors and "钥匙串" in errors[0]


def test_credential_editor_clears_saved_secret(qtbot, monkeypatch) -> None:
    backend = FakeKeyringBackend()
    keyring = KeyringStoreAdapter(backend=backend)
    keyring.save("deepseek", "sk-old")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    editor = _editor(qtbot, keyring=keyring)
    assert editor.findChild(QLabel, "credential-state").text() == "已保存"

    qtbot.mouseClick(editor.findChild(QPushButton, "credential-clear"), Qt.MouseButton.LeftButton)

    assert backend.values == {}
    assert editor.findChild(QLabel, "credential-state").text() == "未设置"


def test_credential_editor_toggles_echo_mode(qtbot) -> None:
    editor = _editor(qtbot)
    secret = editor.findChild(QLineEdit, "credential-secret")

    assert secret.echoMode() == QLineEdit.EchoMode.Password

    editor.findChild(QCheckBox, "credential-show").setChecked(True)

    assert secret.echoMode() == QLineEdit.EchoMode.Normal


def test_credential_editor_without_keyring_disables_secret_controls(qtbot) -> None:
    editor = _editor(qtbot, keyring=UnavailableKeyring())

    assert editor.findChild(QPushButton, "credential-save").isEnabled() is False
    assert editor.findChild(QPushButton, "credential-clear").isEnabled() is False
    assert editor.findChild(QLabel, "credential-state").text() == "系统钥匙串不可用"


def test_credential_editor_environment_kind_has_no_secret_input(qtbot) -> None:
    editor = _editor(
        qtbot,
        credential=CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="DEMO_KEY"),
    )

    assert editor.findChild(QLineEdit, "credential-secret").isEnabled() is False
    assert editor.findChild(QLabel, "credential-state").text() == "密钥来自环境变量"
    assert editor.credential() == CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="DEMO_KEY")

    editor.findChild(QLineEdit, "credential-target").setText("  ")
    with pytest.raises(ConfigError):
        editor.credential()
