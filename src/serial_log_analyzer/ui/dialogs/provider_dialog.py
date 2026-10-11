"""模型服务（Profile）管理对话框：新建 / 编辑 / 删除 Profile 与拉取模型列表。

概念划分：Adapter 决定请求/响应的**格式**，Profile 决定**连哪个服务、用哪个模型与参数**；
仓库里的 Preset 专指设备日志格式，与模型配置无关。

Profile 的持久化以 ``providers/profiles/*.yaml``（内置）与用户配置目录的同名文件（覆盖内置）
为准；本对话框的每一步操作都立即落盘，因此不保留“未保存编辑”。凭据的来源与标识随 Profile
写进 YAML，密钥只在用户点「保存到钥匙串」时写入系统钥匙串。
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable

import yaml
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.llm.model_discovery import ModelDiscoveryService
from serial_log_analyzer.core.models.provider import ModelOption, ProviderProfile
from serial_log_analyzer.core.ports import KeyringStore
from serial_log_analyzer.io.storage.profile_store import ProfileStore
from serial_log_analyzer.ui.widgets.credential_editor import CredentialEditor

__all__ = ["ProviderDialog"]

_MIN_TIMEOUT = 1
_MAX_TIMEOUT = 3_600
_PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class ProviderDialog(QDialog):
    """模型服务配置对话框。

    参数:
        profiles: 当前可用 Profile 列表。
        adapters: 可用 Adapter 列表（用于改选 Adapter 与判断拉取模型能力）。
        keyring: 系统钥匙串适配器（凭据区写密钥用）。
        parent: 可选父窗口。
        reload: 重新读取 Profile 列表（落盘后调用，含内置与用户配置）。
        store: 用户 Profile 存储；缺省使用 :class:`ProfileStore`（用户配置目录）。
        discovery: 模型发现服务；``None`` 时「拉取模型」不可用。
    """

    def __init__(
        self,
        profiles: list[ProviderProfile],
        adapters: list[JSONAdapter],
        parent: QDialog | None = None,
        *,
        keyring: KeyringStore,
        reload: Callable[[], list[ProviderProfile]],
        store: ProfileStore | None = None,
        discovery: ModelDiscoveryService | None = None,
    ) -> None:
        super().__init__(parent)
        self._reload = reload
        self._store = store if store is not None else ProfileStore()
        self._discovery = discovery
        self._adapters = {adapter.adapter_id: adapter for adapter in adapters}
        self._profiles: list[ProviderProfile] = []
        self._saved_path = ""
        self.setWindowTitle("模型服务")

        self._combo = QComboBox()
        self._combo.setObjectName("provider-combo")
        self._combo.currentIndexChanged.connect(self._load_selected)

        self._new_button = QPushButton("新建…")
        self._new_button.setObjectName("provider-new")
        self._new_button.clicked.connect(self._create)
        self._delete_button = QPushButton("删除")
        self._delete_button.setObjectName("provider-delete")
        self._delete_button.clicked.connect(self._delete)

        self._adapter = QComboBox()
        self._adapter.setObjectName("provider-adapter")

        self._base_url = QLineEdit()
        self._base_url.setObjectName("provider-base-url")
        self._base_url.setPlaceholderText("https://api.example.com/v1")

        self._model = QComboBox()
        self._model.setObjectName("provider-model")
        self._model.setEditable(True)

        self._fetch_button = QPushButton("拉取模型")
        self._fetch_button.setObjectName("provider-model-fetch")
        self._fetch_button.clicked.connect(self._fetch_models)

        self._stream = QCheckBox("启用流式输出（SSE）")
        self._stream.setObjectName("provider-stream")

        self._timeout = QSpinBox()
        self._timeout.setObjectName("provider-timeout")
        self._timeout.setRange(_MIN_TIMEOUT, _MAX_TIMEOUT)
        self._timeout.setSuffix(" 秒")

        self._extra_body = QPlainTextEdit()
        self._extra_body.setObjectName("provider-extra-body")
        self._extra_body.setPlaceholderText('YAML 映射，如 {"top_p": 0.9}；留空表示不追加')
        self._extra_body.setFixedHeight(70)

        self._extra_headers = QPlainTextEdit()
        self._extra_headers.setObjectName("provider-extra-headers")
        self._extra_headers.setPlaceholderText('YAML 映射，如 {"X-Org": "team-a"}；留空表示不追加')
        self._extra_headers.setFixedHeight(70)

        self._credential = CredentialEditor(keyring)

        profile_row = QHBoxLayout()
        profile_row.addWidget(self._combo, 1)
        profile_row.addWidget(self._new_button)
        profile_row.addWidget(self._delete_button)

        model_row = QHBoxLayout()
        model_row.addWidget(self._model, 1)
        model_row.addWidget(self._fetch_button)

        form = QFormLayout()
        form.addRow("Profile", profile_row)
        form.addRow("Adapter", self._adapter)
        form.addRow("Base URL", self._base_url)
        form.addRow("模型", model_row)
        form.addRow("流式输出", self._stream)
        form.addRow("请求超时", self._timeout)
        form.addRow("extra_body", self._extra_body)
        form.addRow("extra_headers", self._extra_headers)
        form.addRow("凭据", self._credential)

        self._status = QLabel()
        self._status.setObjectName("provider-status")
        self._status.setWordWrap(True)

        hint = QLabel(
            "Profile 以 providers/profiles/*.yaml 为准；保存写入用户配置目录并覆盖同 ID 的内置"
            " Profile（内置文件本身不会被修改）。凭据来源随 Profile 落盘，密钥只写系统钥匙串。"
        )
        hint.setWordWrap(True)

        self._save_button = QPushButton("保存到用户配置")
        self._save_button.setObjectName("provider-save")
        self._save_button.clicked.connect(self._save_current)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.addButton(self._save_button, QDialogButtonBox.ButtonRole.ActionRole)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._status)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self._set_profiles(profiles)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def selected_profile_id(self) -> str:
        """返回用户选定的 Profile 标识。"""

        return str(self._combo.currentData() or "")

    def saved_path(self) -> str:
        """返回最近一次「保存到用户配置」写入的路径；未保存时为空串。"""

        return self._saved_path

    # ------------------------------------------------------------------
    # 列表维护
    # ------------------------------------------------------------------

    def _set_profiles(self, profiles: list[ProviderProfile]) -> None:
        """刷新下拉列表并尽量保留当前选择。"""

        wanted = self.selected_profile_id()
        self._profiles = list(profiles)
        self._combo.blockSignals(True)
        self._combo.clear()
        for profile in self._profiles:
            self._combo.addItem(f"{profile.profile_id} — {profile.model}", profile.profile_id)
        index = self._combo.findData(wanted)
        self._combo.setCurrentIndex(index if index >= 0 else (0 if self._profiles else -1))
        self._combo.blockSignals(False)
        self._load_selected()

    def _refresh(self, select: str = "") -> None:
        """落盘后重读列表并选中 ``select``（缺省保留当前项）。"""

        self._set_profiles(self._reload())
        if select:
            index = self._combo.findData(select)
            if index >= 0:
                self._combo.setCurrentIndex(index)

    def _current_profile(self) -> ProviderProfile | None:
        profile_id = self.selected_profile_id()
        return next((item for item in self._profiles if item.profile_id == profile_id), None)

    def _load_selected(self) -> None:
        """把当前选中 Profile 的字段填入界面。"""

        profile = self._current_profile()
        editable = profile is not None
        self._delete_button.setEnabled(editable)
        for widget in (
            self._adapter,
            self._base_url,
            self._model,
            self._stream,
            self._timeout,
            self._extra_body,
            self._extra_headers,
            self._credential,
            self._save_button,
        ):
            widget.setEnabled(editable)
        if profile is None:
            self._adapter.clear()
            self._base_url.clear()
            self._model.clear()
            self._extra_body.setPlainText("")
            self._extra_headers.setPlainText("")
            self._credential.clear()
            self._status.setText("")
            self._fetch_button.setEnabled(False)
            return
        self._fill_adapters(profile.adapter_id)
        self._base_url.setText(profile.base_url)
        self._model.setCurrentText(profile.model)
        self._stream.setChecked(bool(profile.stream))
        self._timeout.setValue(_timeout_value(profile))
        self._extra_body.setPlainText(_mapping_text(profile.extra_body))
        self._extra_headers.setPlainText(_mapping_text(profile.extra_headers))
        self._credential.load(profile.credential, profile.profile_id)
        self._status.setText("")

    def _fill_adapters(self, current: str) -> None:
        """填充 Adapter 下拉；当前声明不在内置列表时照样列出，避免界面说谎。"""

        self._adapter.blockSignals(True)
        self._adapter.clear()
        for adapter_id, adapter in self._adapters.items():
            suffix = "" if adapter.streaming_supported else "（仅非流式）"
            self._adapter.addItem(f"{adapter_id}{suffix}", adapter_id)
        if current and self._adapter.findData(current) < 0:
            self._adapter.addItem(f"{current}（资源中未找到）", current)
        index = self._adapter.findData(current)
        self._adapter.setCurrentIndex(index if index >= 0 else -1)
        self._adapter.blockSignals(False)
        self._update_fetch_state()

    def _update_fetch_state(self) -> None:
        adapter = self._adapters.get(self._selected_adapter_id())
        usable = (
            self._discovery is not None
            and adapter is not None
            and adapter.model_discovery is not None
        )
        self._fetch_button.setEnabled(usable)

    def _selected_adapter_id(self) -> str:
        return str(self._adapter.currentData() or "")

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------

    def _create(self) -> None:
        """以当前项为模板新建一个 Profile（立即落盘）。"""

        template = self._current_profile()
        if template is None:
            template = ProviderProfile(
                profile_id="", adapter_id=self._selected_adapter_id() or "", base_url="", model=""
            )
        new_id, accepted = QInputDialog.getText(self, "新建 Profile", "新的 profile_id：")
        new_id = new_id.strip()
        if not accepted or not new_id:
            return
        if not _PROFILE_ID_RE.match(new_id):
            QMessageBox.warning(self, "无法新建", "profile_id 只能用 a-z、0-9 与连字符，且以字母开头。")
            return
        if any(item.profile_id == new_id for item in self._profiles):
            QMessageBox.warning(self, "无法新建", f"Profile {new_id} 已存在，请改用其它标识。")
            return
        created = dataclasses.replace(
            template,
            profile_id=new_id,
            adapter_id=self._selected_adapter_id() or template.adapter_id,
            base_url=self._base_url.text().strip() or template.base_url,
            model=self._model.currentText().strip() or template.model,
        )
        if not self._write(created):
            return
        self._refresh(select=new_id)
        self._status.setText(f"已新建 Profile {new_id}（写入用户配置目录）")

    def _delete(self) -> None:
        """删除用户配置目录中的 Profile；内置文件不受影响。"""

        profile = self._current_profile()
        if profile is None:
            return
        profile_id = profile.profile_id
        if not self._store.exists(profile_id):
            QMessageBox.warning(
                self, "无法删除", f"{profile_id} 只存在于内置资源中，内置 Profile 无法删除。"
            )
            return
        answer = QMessageBox.question(
            self,
            "删除 Profile",
            f"删除用户配置目录中的 {profile_id}.yaml？\n若存在同 ID 的内置 Profile，删除后将回退到内置。",
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.delete(profile_id)
        except AppError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self._refresh()
        self._status.setText(f"已删除用户配置中的 {profile_id}")

    def _fetch_models(self) -> None:
        """用当前界面字段（含未保存的编辑）拉取服务端模型列表。"""

        discovery = self._discovery
        adapter = self._adapters.get(self._selected_adapter_id())
        if discovery is None or adapter is None or adapter.model_discovery is None:
            return
        try:
            profile = self._collect()
        except ConfigError as exc:
            QMessageBox.warning(self, "无法拉取", str(exc))
            return
        self._fetch_button.setEnabled(False)
        self._status.setText("正在拉取模型列表…")

        def _done(options: list[ModelOption]) -> None:
            current = self._model.currentText().strip()
            self._model.clear()
            for option in options:
                self._model.addItem(f"{option.display}", option.model_id)
            self._model.setCurrentText(current)
            self._update_fetch_state()
            self._status.setText(f"已获取 {len(options)} 个模型")

        def _failed(error: AppError) -> None:
            self._update_fetch_state()
            self._status.setText("")
            QMessageBox.warning(self, "拉取模型失败", str(error))

        try:
            discovery.fetch(adapter, profile, _done, _failed)
        except AppError as exc:
            self._update_fetch_state()
            self._status.setText("")
            QMessageBox.warning(self, "拉取模型失败", str(exc))

    def _save_current(self) -> None:
        """把界面编辑结果写入用户配置目录。"""

        profile = self._current_profile()
        if profile is None:
            QMessageBox.warning(self, "无法保存", "当前没有可保存的 Profile。")
            return
        try:
            updated = self._collect(base=profile)
        except ConfigError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        path = self._write(updated)
        if not path:
            return
        self._refresh(select=updated.profile_id)
        QMessageBox.information(self, "已保存", f"Profile 已写入：\n{path}")

    # ------------------------------------------------------------------
    # 组装与落盘
    # ------------------------------------------------------------------

    def _collect(self, base: ProviderProfile | None = None) -> ProviderProfile:
        """按界面字段组装 Profile；``base`` 为 ``None`` 时用当前项（拉取模型用）。

        异常:
            ConfigError: 字段为空或 YAML 文本不是映射。
        """

        profile = base if base is not None else self._current_profile()
        if profile is None:
            raise ConfigError("当前没有可用的 Profile")
        model = self._model.currentText().strip()
        if not model:
            raise ConfigError("模型名不能为空")
        headers = _parse_mapping(self._extra_headers.toPlainText(), "extra_headers", strings_only=True)
        return dataclasses.replace(
            profile,
            adapter_id=self._selected_adapter_id() or profile.adapter_id,
            base_url=self._base_url.text().strip(),
            model=model,
            stream=self._stream.isChecked(),
            request_timeout_seconds=float(self._timeout.value()),
            credential=self._credential.credential(),
            extra_body=_parse_mapping(self._extra_body.toPlainText(), "extra_body"),
            extra_headers=headers,
        )

    def _write(self, profile: ProviderProfile) -> str:
        """写盘；失败时弹窗并返回空串。"""

        try:
            path = self._store.save(profile)
        except (ConfigError, AppError) as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return ""
        self._saved_path = str(path)
        return self._saved_path


def _parse_mapping(text: str, field: str, *, strings_only: bool = False) -> dict:
    """把界面上的 YAML 文本解析为映射；空文本视为 ``{}``。

    异常:
        ConfigError: YAML 非法或不是映射；``strings_only`` 时值必须为字符串。
    """

    if not text.strip():
        return {}
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{field} 不是合法 YAML：{exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(f"{field} 必须是 YAML 映射（如 {{\"a\": 1}}）")
    if strings_only:
        for key, value in parsed.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ConfigError(f"{field} 的键与值都必须是字符串")
    return parsed


def _mapping_text(mapping: dict) -> str:
    """把映射渲染为界面文本；空映射显示为空。"""

    if not mapping:
        return ""
    return yaml.safe_dump(mapping, allow_unicode=True, sort_keys=False, default_flow_style=True).strip()


def _timeout_value(profile: ProviderProfile) -> int:
    """读取请求超时并限制在界面控件范围内。"""

    try:
        seconds = int(float(profile.request_timeout_seconds))
    except (TypeError, ValueError):  # pragma: no cover - 加载期已校验为数值
        seconds = 120
    return max(_MIN_TIMEOUT, min(_MAX_TIMEOUT, seconds))
