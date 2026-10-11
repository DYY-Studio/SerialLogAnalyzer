"""Provider 配置对话框：选择已有 Profile 并编辑其少数字段。

概念划分：Adapter 决定请求/响应的**格式**，Profile 决定**连哪个服务、用哪个模型与参数**；
仓库里的 Preset 专指设备日志格式，与模型配置无关。

Profile 的持久化以 ``providers/profiles/*.yaml`` 为准；本对话框只做界面编辑。
点击「保存到用户配置」会把当前编辑结果写入用户配置目录，覆盖同 ID 的内置 Profile
（内置文件本身不会被修改）。

**本对话框是壳子**，范围仅限：选择 Profile、编辑 base_url / model / stream / 请求超时、
查看 Adapter 与凭据来源、保存到用户配置。以下刻意不做（见 docs/configuration.md §4.4）：
新建 / 复制 / 删除 Profile、在界面上改选 Adapter、编辑 extra_body / extra_headers、
拉取服务端模型列表（依赖 LLM 分工的模型发现）。模型参数
（``${temperature}`` / ``${max_output_tokens}`` 的取值）由 LLM 分工的 RequestBuilder 决定，
Profile 只声明模型与 extra_body 透传，因此这里不提供这两项。
"""

from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef, ProviderProfile
from serial_log_analyzer.io.storage.profile_store import ProfileStore

__all__ = ["ProviderDialog"]

_MIN_TIMEOUT = 1
_MAX_TIMEOUT = 3_600


class ProviderDialog(QDialog):
    """模型服务配置对话框。

    参数:
        profiles: 当前可用 Profile 列表。
        parent: 可选父窗口。
        store: 用户 Profile 存储；缺省使用 :class:`ProfileStore`（用户配置目录）。
    """

    def __init__(
        self,
        profiles: list[object],
        parent: QDialog | None = None,
        *,
        store: ProfileStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._profiles = list(profiles)
        self._store = store if store is not None else ProfileStore()
        self._saved_path: str = ""
        self.setWindowTitle("模型服务")

        self._combo = QComboBox()
        self._combo.setObjectName("provider-combo")
        for profile in self._profiles:
            self._combo.addItem(
                f"{_text(profile, 'profile_id')} — {_text(profile, 'model')}",
                _text(profile, "profile_id"),
            )
        self._combo.currentIndexChanged.connect(self._load_selected)

        self._adapter = QLabel()
        self._adapter.setObjectName("provider-adapter")

        self._base_url = QLineEdit()
        self._base_url.setObjectName("provider-base-url")
        self._base_url.setPlaceholderText("https://api.example.com/v1")

        self._model = QLineEdit()
        self._model.setObjectName("provider-model")

        self._stream = QCheckBox("启用流式输出（SSE）")
        self._stream.setObjectName("provider-stream")

        self._timeout = QSpinBox()
        self._timeout.setObjectName("provider-timeout")
        self._timeout.setRange(_MIN_TIMEOUT, _MAX_TIMEOUT)
        self._timeout.setSuffix(" 秒")

        self._credential = QLabel()
        self._credential.setObjectName("provider-credential")
        self._credential.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Profile", self._combo)
        form.addRow("Adapter", self._adapter)
        form.addRow("Base URL", self._base_url)
        form.addRow("模型", self._model)
        form.addRow("流式输出", self._stream)
        form.addRow("请求超时", self._timeout)
        form.addRow("凭据来源", self._credential)

        hint = QLabel(
            "Profile 以 providers/profiles/*.yaml 为准；保存后写入用户配置目录并覆盖同 ID 的内置"
            " Profile。API Key 请在「API Key」对话框中设置。"
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
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self._load_selected()

    def selected_profile_id(self) -> str:
        """返回用户选定的 Profile 标识。"""

        return str(self._combo.currentData() or "")

    def saved_path(self) -> str:
        """返回「保存到用户配置」实际写入的路径；未保存时为空串。"""

        return self._saved_path

    def _current_profile(self) -> object | None:
        """返回当前选中的 Profile 对象。"""
        profile_id = self.selected_profile_id()
        return next(
            (item for item in self._profiles if _text(item, "profile_id") == profile_id), None
        )

    def _load_selected(self) -> None:
        """把当前选中 Profile 的字段填入界面。"""
        profile = self._current_profile()
        if profile is None:
            self._adapter.setText("（无可用 Profile）")
            self._credential.setText("")
            return
        self._adapter.setText(_text(profile, "adapter_id"))
        self._base_url.setText(_text(profile, "base_url"))
        self._model.setText(_text(profile, "model"))
        self._stream.setChecked(bool(getattr(profile, "stream", True)))
        self._timeout.setValue(_timeout_value(profile))
        self._credential.setText(_credential_text(profile))

    def _save_current(self) -> None:
        """把界面编辑结果写入用户配置目录。"""
        profile = self._current_profile()
        if profile is None:
            QMessageBox.warning(self, "无法保存", "当前没有可保存的 Profile。")
            return
        base_url = self._base_url.text().strip()
        model = self._model.text().strip()
        try:
            updated = _with_edits(
                profile,
                base_url=base_url,
                model=model,
                stream=self._stream.isChecked(),
                request_timeout_seconds=float(self._timeout.value()),
            )
            path = self._store.save(updated)
        except (ConfigError, AppError) as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self._saved_path = str(path)
        QMessageBox.information(self, "已保存", f"Profile 已写入：\n{path}")


def _with_edits(
    profile: object,
    *,
    base_url: str,
    model: str,
    stream: bool,
    request_timeout_seconds: float,
) -> ProviderProfile:
    """基于原 Profile 生成编辑后的副本，保留未在界面上暴露的字段。"""
    if dataclasses.is_dataclass(profile) and not isinstance(profile, type):
        return dataclasses.replace(  # type: ignore[arg-type]
            profile,
            base_url=base_url,
            model=model,
            stream=stream,
            request_timeout_seconds=request_timeout_seconds,
        )
    return ProviderProfile(
        profile_id=_text(profile, "profile_id"),
        adapter_id=_text(profile, "adapter_id"),
        base_url=base_url,
        model=model,
        credential=getattr(profile, "credential", None) or CredentialRef(kind=CredentialKind.RUNTIME),
        stream=stream,
        request_timeout_seconds=request_timeout_seconds,
        extra_body=dict(getattr(profile, "extra_body", {}) or {}),
        extra_headers=dict(getattr(profile, "extra_headers", {}) or {}),
    )


def _text(profile: object, field: str) -> str:
    """读取 Profile 上的字符串字段。"""
    value = getattr(profile, field, "")
    return "" if value is None else str(value)


def _timeout_value(profile: object) -> int:
    """读取请求超时并限制在界面控件范围内。"""
    try:
        seconds = int(float(getattr(profile, "request_timeout_seconds", 120)))
    except (TypeError, ValueError):
        seconds = 120
    return max(_MIN_TIMEOUT, min(_MAX_TIMEOUT, seconds))


def _credential_text(profile: object) -> str:
    """把凭据引用渲染为中文说明。"""
    credential = getattr(profile, "credential", None)
    kind = getattr(credential, "kind", None)
    name = str(getattr(credential, "name", "") or "")
    env_var = str(getattr(credential, "env_var", "") or "")
    if kind is CredentialKind.KEYRING:
        parts = [f"系统钥匙串（account：{name or '（未指定）'}）"]
        if env_var:
            parts.append(f"环境变量回退：{env_var}")
        return "；".join(parts)
    if kind is CredentialKind.ENVIRONMENT:
        return f"环境变量：{env_var or '（未指定）'}"
    if kind is CredentialKind.RUNTIME:
        return "运行时临时输入（不写入系统钥匙串）"
    return "（未声明）"
