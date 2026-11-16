"""设置对话框：双标签页管理常规偏好与 SMTP 邮件告警配置。

仅通过 :class:`SettingsStore` 与可选 :class:`KeyringStore` 协作：
非密钥配置写入设置存储，SMTP 密码或授权码仅经 :class:`CredentialEditor` 写入系统钥匙串，
绝不把明文密码写入 ``QSettings``。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.models.anomaly import AnomalySeverity
from serial_log_analyzer.core.models.notification import (
    DEFAULT_SMTP_KEYRING_NAME,
    DeliveryReceipt,
    SmtpConfig,
    SmtpSecurity,
    load_smtp_config,
    parse_recipients,
    save_smtp_config,
    validate_smtp_config,
)
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.ports import KeyringStore, SettingsStore
from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS, parse_bool
from serial_log_analyzer.ui.widgets.credential_editor import CredentialEditor

__all__ = ["SettingsDialog"]

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_DEFAULT_LOG_LEVEL = "INFO"
_MIN_CAPACITY = 1_000
_MAX_CAPACITY = 1_000_000
_MAX_HISTORY_ROUNDS = 50

_SECURITY_CHOICES: tuple[tuple[str, SmtpSecurity], ...] = (
    ("STARTTLS（推荐，常用 587）", SmtpSecurity.STARTTLS),
    ("SSL/TLS（常用 465）", SmtpSecurity.SSL),
    ("无加密明文（仅内网中继）", SmtpSecurity.NONE),
)

_SEVERITY_CHOICES: tuple[tuple[str, AnomalySeverity], ...] = (
    ("严重 (CRITICAL)", AnomalySeverity.CRITICAL),
    ("高 (HIGH) 及以上", AnomalySeverity.HIGH),
    ("中 (MEDIUM) 及以上", AnomalySeverity.MEDIUM),
    ("低 (LOW) 全部异常", AnomalySeverity.LOW),
)


class SettingsDialog(QDialog):
    """应用设置对话框（常规偏好 + SMTP 邮件告警）。

    参数:
        settings: 设置存储。
        parent: 可选父窗口。
        keyring: 可选系统钥匙串适配器；传入时展示 SMTP 凭据编辑区。
        on_test_smtp: 可选测试邮件回调，接收当前表单构造的 :class:`SmtpConfig`。
        initial_tab: 默认激活的标签页索引（``0`` 为常规，``1`` 为邮件告警）。
    """

    def __init__(
        self,
        settings: SettingsStore,
        parent: QWidget | None = None,
        *,
        keyring: KeyringStore | None = None,
        on_test_smtp: Callable[[SmtpConfig], None] | None = None,
        initial_tab: int = 0,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._keyring = keyring
        self._on_test_smtp = on_test_smtp
        self._loaded_credential = CredentialRef(
            CredentialKind.KEYRING, name=DEFAULT_SMTP_KEYRING_NAME
        )
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("settings-tabs")
        self._tabs.addTab(self._build_general_tab(), "常规")
        self._tabs.addTab(self._build_smtp_tab(), "邮件告警 (SMTP)")
        if 0 <= initial_tab < self._tabs.count():
            self._tabs.setCurrentIndex(initial_tab)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("确定")
        ok_btn.setProperty("variant", "primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        root.addWidget(self._tabs, stretch=1)
        root.addWidget(buttons)

        self._load()

    def show_smtp_test_result(self, receipt: DeliveryReceipt) -> None:
        """接收异步或同步测试邮件投递回执，并在设置页内联展示反馈。"""

        self._smtp_test_btn.setEnabled(self._on_test_smtp is not None)
        if receipt.ok:
            recipients = ", ".join(receipt.recipients)
            self._set_test_status("ok", f"✓ 测试邮件已投递至 {recipients}")
            return
        self._set_test_status("error", f"✗ 测试发送失败：{receipt.error or '未知错误'}")

    def accept(self) -> None:
        """校验并保存常规与 SMTP 设置；启用 SMTP 时先校验完整必填字段。"""

        try:
            smtp_cfg = self._build_smtp_config()
            validate_smtp_config(smtp_cfg, require_enabled_fields=smtp_cfg.enabled)
        except AppError as exc:
            self._tabs.setCurrentIndex(1)
            QMessageBox.warning(self, "邮件告警配置无效", str(exc))
            return

        try:
            self._settings.set(SETTINGS_KEYS.AUTOSCROLL, self._autoscroll.isChecked())
            self._settings.set(SETTINGS_KEYS.LOG_CAPACITY, self._capacity.value())
            self._settings.set(SETTINGS_KEYS.LOG_LEVEL, self._log_level.currentText())
            self._settings.set(
                SETTINGS_KEYS.CHAT_DETAILS_EXPANDED, self._details_expanded.isChecked()
            )
            self._settings.set(SETTINGS_KEYS.LLM_HISTORY_ROUNDS, self._history_rounds.value())
            self._settings.set(SETTINGS_KEYS.EXPORT_DIR, self._export_dir.text().strip())
            save_smtp_config(self._settings, smtp_cfg)
            sync = getattr(self._settings, "sync", None)
            if callable(sync):
                sync()
        except AppError as exc:
            QMessageBox.critical(self, "保存设置失败", str(exc))
            return
        super().accept()

    # ------------------------------------------------------------------
    # 标签页构建
    # ------------------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self._autoscroll = QCheckBox("自动滚动到最新日志")
        self._autoscroll.setObjectName("settings-autoscroll")

        self._capacity = QSpinBox()
        self._capacity.setObjectName("settings-capacity")
        self._capacity.setRange(_MIN_CAPACITY, _MAX_CAPACITY)
        self._capacity.setSingleStep(1_000)
        self._capacity.setSuffix(" 条")

        self._log_level = QComboBox()
        self._log_level.setObjectName("settings-log-level")
        self._log_level.addItems(_LOG_LEVELS)

        self._details_expanded = QCheckBox("思考 / 参考内容")
        self._details_expanded.setObjectName("settings-details-expanded")

        self._history_rounds = QSpinBox()
        self._history_rounds.setObjectName("settings-history-rounds")
        self._history_rounds.setRange(0, _MAX_HISTORY_ROUNDS)
        self._history_rounds.setSuffix(" 轮")
        self._history_rounds.setSpecialValueText("全部携带")
        self._details_expanded.setToolTip("「思考」与「参考内容」折叠块默认展开还是收起")
        self._history_rounds.setToolTip(
            "只裁剪发给模型的历史：保留首轮 + 最近 N 轮，界面仍显示完整会话；\n"
            "裁剪会让服务端前缀缓存失效，通常不比全部携带省。"
        )

        self._export_dir = QLineEdit()
        self._export_dir.setObjectName("settings-export-dir")
        self._export_dir.setPlaceholderText("留空使用默认导出目录")

        browse = QPushButton("浏览…")
        browse.setObjectName("settings-browse")
        browse.clicked.connect(self._choose_export_dir)
        export_row = QHBoxLayout()
        export_row.addWidget(self._export_dir)
        export_row.addWidget(browse)

        log_title = QLabel("日志")
        log_title.setProperty("role", "section-title")
        log_divider = QFrame()
        log_divider.setProperty("role", "section-divider")
        log_form = QFormLayout()
        log_form.setSpacing(9)
        log_form.addRow("容量", self._capacity)
        log_form.addRow("自动滚动", self._autoscroll)
        log_form.addRow("应用日志级别", self._log_level)
        log_form.addRow("导出目录", export_row)

        llm_title = QLabel("LLM 分析")
        llm_title.setProperty("role", "section-title")
        llm_divider = QFrame()
        llm_divider.setProperty("role", "section-divider")
        llm_form = QFormLayout()
        llm_form.setSpacing(9)
        llm_form.addRow("默认展开", self._details_expanded)
        llm_form.addRow("携带历史", self._history_rounds)

        hint = QLabel("偏好保存在本机系统配置；模型服务与 API Key 由「模型服务…」管理。")
        hint.setProperty("role", "muted-caption")
        hint.setWordWrap(True)

        layout.addWidget(log_title)
        layout.addWidget(log_divider)
        layout.addLayout(log_form)
        layout.addSpacing(4)
        layout.addWidget(llm_title)
        layout.addWidget(llm_divider)
        layout.addLayout(llm_form)
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def _build_smtp_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self._smtp_enabled = QCheckBox("启用异常告警邮件自动发送")
        self._smtp_enabled.setObjectName("settings-smtp-enabled")
        layout.addWidget(self._smtp_enabled)

        server_title = QLabel("服务器与传输")
        server_title.setProperty("role", "section-title")
        server_divider = QFrame()
        server_divider.setProperty("role", "section-divider")
        server_form = QFormLayout()
        server_form.setSpacing(7)

        self._smtp_host = QLineEdit()
        self._smtp_host.setObjectName("settings-smtp-host")
        self._smtp_host.setPlaceholderText("例如 smtp.example.com")
        server_form.addRow("SMTP 主机", self._smtp_host)

        port_timeout_row = QHBoxLayout()
        port_timeout_row.setSpacing(8)
        self._smtp_port = QSpinBox()
        self._smtp_port.setObjectName("settings-smtp-port")
        self._smtp_port.setRange(1, 65535)
        self._smtp_port.setValue(587)
        port_timeout_row.addWidget(self._smtp_port, stretch=1)

        timeout_lbl = QLabel("超时")
        port_timeout_row.addWidget(timeout_lbl)
        self._smtp_timeout = QDoubleSpinBox()
        self._smtp_timeout.setObjectName("settings-smtp-timeout")
        self._smtp_timeout.setRange(1.0, 300.0)
        self._smtp_timeout.setDecimals(1)
        self._smtp_timeout.setSingleStep(1.0)
        self._smtp_timeout.setSuffix(" 秒")
        self._smtp_timeout.setValue(15.0)
        port_timeout_row.addWidget(self._smtp_timeout, stretch=1)
        server_form.addRow("端口", port_timeout_row)

        self._smtp_security = QComboBox()
        self._smtp_security.setObjectName("settings-smtp-security")
        for label, mode in _SECURITY_CHOICES:
            self._smtp_security.addItem(label, mode)
        server_form.addRow("安全模式", self._smtp_security)

        layout.addWidget(server_title)
        layout.addWidget(server_divider)
        layout.addLayout(server_form)

        mail_title = QLabel("收发件、触发门槛与隐私")
        mail_title.setProperty("role", "section-title")
        mail_divider = QFrame()
        mail_divider.setProperty("role", "section-divider")
        mail_form = QFormLayout()
        mail_form.setSpacing(7)

        self._smtp_username = QLineEdit()
        self._smtp_username.setObjectName("settings-smtp-username")
        self._smtp_username.setPlaceholderText("留空表示免密中继（不进行登录认证）")
        mail_form.addRow("用户名", self._smtp_username)

        self._smtp_sender = QLineEdit()
        self._smtp_sender.setObjectName("settings-smtp-sender")
        self._smtp_sender.setPlaceholderText("例如 alerts@example.com")
        mail_form.addRow("发件人", self._smtp_sender)

        self._smtp_recipients = QLineEdit()
        self._smtp_recipients.setObjectName("settings-smtp-recipients")
        self._smtp_recipients.setPlaceholderText("多个邮箱请用逗号或分号分隔")
        mail_form.addRow("收件人", self._smtp_recipients)

        self._smtp_min_severity = QComboBox()
        self._smtp_min_severity.setObjectName("settings-smtp-min-severity")
        for label, severity in _SEVERITY_CHOICES:
            self._smtp_min_severity.addItem(label, severity)
        mail_form.addRow("最低告警级别", self._smtp_min_severity)

        self._smtp_include_evidence = QCheckBox("邮件附带最多 5 条原始日志（注意隐私）")
        self._smtp_include_evidence.setObjectName("settings-smtp-include-evidence")
        self._smtp_include_evidence.setToolTip(
            "默认关闭以保护日志隐私，邮件仅发送脱敏摘要与日志序号；开启后最多附加 5 条渲染原文。"
        )
        mail_form.addRow("正文隐私", self._smtp_include_evidence)

        layout.addWidget(mail_title)
        layout.addWidget(mail_divider)
        layout.addLayout(mail_form)

        cred_title = QLabel("SMTP 密码 / 授权码")
        cred_title.setProperty("role", "section-title")
        cred_divider = QFrame()
        cred_divider.setProperty("role", "section-divider")
        layout.addWidget(cred_title)
        layout.addWidget(cred_divider)

        self._smtp_credential_editor: CredentialEditor | None = None
        if self._keyring is not None:
            self._smtp_credential_editor = CredentialEditor(
                self._keyring,
                self,
                target_hint=f"钥匙串账号名（默认 {DEFAULT_SMTP_KEYRING_NAME}）",
                secret_hint="SMTP 密码 / 授权码（只写入系统钥匙串）",
                empty_secret_msg="请先输入 SMTP 密码或授权码。",
            )
            self._smtp_credential_editor.setObjectName("settings-smtp-credential-editor")
            layout.addWidget(self._smtp_credential_editor)
        else:
            no_keyring_hint = QLabel("当前环境未注入钥匙串适配器，将沿用既有凭据引用配置。")
            no_keyring_hint.setProperty("role", "muted-caption")
            layout.addWidget(no_keyring_hint)

        relay_hint = QLabel("提示：若 SMTP 服务为免密内网中继，请保持「用户名」留空即可。")
        relay_hint.setProperty("role", "muted-caption")
        relay_hint.setWordWrap(True)
        layout.addWidget(relay_hint)

        test_row = QHBoxLayout()
        test_row.setSpacing(8)
        self._smtp_test_btn = QPushButton("发送测试邮件")
        self._smtp_test_btn.setObjectName("settings-smtp-test")
        self._smtp_test_btn.setEnabled(self._on_test_smtp is not None)
        self._smtp_test_btn.setToolTip("绕过启用开关与冷却限制，按当前表单配置即时发送一封测试邮件")
        self._smtp_test_btn.clicked.connect(self._on_test_smtp_clicked)
        test_row.addWidget(self._smtp_test_btn)

        self._smtp_test_status = QLabel()
        self._smtp_test_status.setObjectName("settings-smtp-test-status")
        self._smtp_test_status.setWordWrap(True)
        self._smtp_test_status.setVisible(False)
        test_row.addWidget(self._smtp_test_status, stretch=1)
        layout.addLayout(test_row)
        layout.addStretch()
        return page

    # ------------------------------------------------------------------
    # 数据加载 / 构造与测试发送
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._autoscroll.setChecked(
            parse_bool(self._settings.get(SETTINGS_KEYS.AUTOSCROLL), True)
        )
        self._capacity.setValue(
            _clamp(_as_int(self._settings.get(SETTINGS_KEYS.LOG_CAPACITY), 100_000))
        )
        level = str(self._settings.get(SETTINGS_KEYS.LOG_LEVEL) or _DEFAULT_LOG_LEVEL).upper()
        if level not in _LOG_LEVELS:
            level = _DEFAULT_LOG_LEVEL
        self._log_level.setCurrentText(level)
        self._details_expanded.setChecked(
            parse_bool(self._settings.get(SETTINGS_KEYS.CHAT_DETAILS_EXPANDED), False)
        )
        self._history_rounds.setValue(
            _as_int(self._settings.get(SETTINGS_KEYS.LLM_HISTORY_ROUNDS), 0)
        )
        self._export_dir.setText(str(self._settings.get(SETTINGS_KEYS.EXPORT_DIR) or ""))

        try:
            smtp_cfg = load_smtp_config(self._settings)
        except AppError as exc:
            smtp_cfg = SmtpConfig()
            self._set_test_status("error", f"已回落默认 SMTP 表单（原配置无效：{exc}）")

        self._smtp_enabled.setChecked(smtp_cfg.enabled)
        self._smtp_host.setText(smtp_cfg.host)
        self._smtp_port.setValue(smtp_cfg.port)
        self._smtp_timeout.setValue(smtp_cfg.timeout_seconds)
        sec_idx = self._smtp_security.findData(smtp_cfg.security)
        self._smtp_security.setCurrentIndex(sec_idx if sec_idx >= 0 else 0)
        self._smtp_username.setText(smtp_cfg.username)
        self._smtp_sender.setText(smtp_cfg.sender)
        self._smtp_recipients.setText(", ".join(smtp_cfg.recipients))
        sev_idx = self._smtp_min_severity.findData(smtp_cfg.min_severity)
        self._smtp_min_severity.setCurrentIndex(sev_idx if sev_idx >= 0 else 1)
        self._smtp_include_evidence.setChecked(smtp_cfg.include_evidence_lines)
        self._loaded_credential = smtp_cfg.credential
        if self._smtp_credential_editor is not None:
            self._smtp_credential_editor.load(smtp_cfg.credential, DEFAULT_SMTP_KEYRING_NAME)

    def _build_smtp_config(self, *, require_credentials: bool | None = None) -> SmtpConfig:
        enabled = self._smtp_enabled.isChecked()
        username = self._smtp_username.text().strip()
        need_credentials = (
            (enabled and bool(username)) if require_credentials is None else require_credentials
        )
        if self._smtp_credential_editor is not None:
            try:
                credential = self._smtp_credential_editor.credential()
            except ConfigError:
                if need_credentials:
                    raise
                credential = self._loaded_credential
        else:
            credential = self._loaded_credential
        return SmtpConfig(
            enabled=enabled,
            host=self._smtp_host.text().strip(),
            port=self._smtp_port.value(),
            security=self._smtp_security.currentData() or SmtpSecurity.STARTTLS,
            username=username,
            sender=self._smtp_sender.text().strip(),
            recipients=parse_recipients(self._smtp_recipients.text()),
            credential=credential,
            timeout_seconds=float(self._smtp_timeout.value()),
            min_severity=self._smtp_min_severity.currentData() or AnomalySeverity.HIGH,
            include_evidence_lines=self._smtp_include_evidence.isChecked(),
        )

    def _on_test_smtp_clicked(self) -> None:
        if self._on_test_smtp is None:
            return
        try:
            cfg = self._build_smtp_config(
                require_credentials=bool(self._smtp_username.text().strip())
            )
            validate_smtp_config(cfg, require_enabled_fields=True)
        except AppError as exc:
            self._set_test_status("error", str(exc))
            return
        self._smtp_test_btn.setEnabled(False)
        self._set_test_status("pending", "正在异步发送测试邮件…")
        self._on_test_smtp(cfg)

    def _set_test_status(self, state: str, text: str) -> None:
        self._smtp_test_status.setProperty("testState", state)
        self._smtp_test_status.style().unpolish(self._smtp_test_status)
        self._smtp_test_status.style().polish(self._smtp_test_status)
        self._smtp_test_status.setText(text)
        self._smtp_test_status.setVisible(True)

    def _choose_export_dir(self) -> None:
        """选择默认导出目录。"""
        current = self._export_dir.text().strip()
        chosen = QFileDialog.getExistingDirectory(self, "选择默认导出目录", current)
        if chosen:
            self._export_dir.setText(chosen)


def _as_int(value: object, default: int) -> int:
    """把设置存储中的值稳健地转换为整数。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clamp(value: int) -> int:
    """把容量限制在合法范围内。"""
    return max(_MIN_CAPACITY, min(_MAX_CAPACITY, value))
