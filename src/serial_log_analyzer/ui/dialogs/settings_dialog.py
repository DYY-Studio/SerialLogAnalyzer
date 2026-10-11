"""设置对话框：界面偏好与日志容量等。

只读写 :class:`SettingsStore`，不触碰凭据与 Provider 配置。
键名与 :mod:`serial_log_analyzer.io.settings.qt_settings_store` 共享，避免出现两份字符串常量。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.ports import SettingsStore
from serial_log_analyzer.io.settings.qt_settings_store import SETTINGS_KEYS

__all__ = ["SettingsDialog"]

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_DEFAULT_LOG_LEVEL = "INFO"
_MIN_CAPACITY = 1_000
_MAX_CAPACITY = 1_000_000
_MAX_HISTORY_ROUNDS = 50


class SettingsDialog(QDialog):
    """应用设置对话框。

    参数:
        settings: 设置存储。
        parent: 可选父窗口。
    """

    def __init__(self, settings: SettingsStore, parent: QDialog | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("设置")
        self.setMinimumWidth(440)

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

        log_group = QGroupBox("日志")
        log_form = QFormLayout(log_group)
        log_form.addRow("容量", self._capacity)
        log_form.addRow("自动滚动", self._autoscroll)
        log_form.addRow("应用日志级别", self._log_level)
        log_form.addRow("导出目录", export_row)

        llm_group = QGroupBox("LLM 分析")
        llm_form = QFormLayout(llm_group)
        llm_form.addRow("默认展开", self._details_expanded)
        llm_form.addRow("携带历史", self._history_rounds)

        hint = QLabel("偏好保存在本机系统配置；模型服务与 API Key 由各自对话框管理。")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(log_group)
        layout.addWidget(llm_group)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self._load()

    def accept(self) -> None:
        """保存设置并关闭。

        异常不会外抛：保存失败时提示用户并保持对话框打开，避免静默丢失输入。
        """

        try:
            self._settings.set(SETTINGS_KEYS.AUTOSCROLL, self._autoscroll.isChecked())
            self._settings.set(SETTINGS_KEYS.LOG_CAPACITY, self._capacity.value())
            self._settings.set(SETTINGS_KEYS.LOG_LEVEL, self._log_level.currentText())
            self._settings.set(
                SETTINGS_KEYS.CHAT_DETAILS_EXPANDED, self._details_expanded.isChecked()
            )
            self._settings.set(SETTINGS_KEYS.LLM_HISTORY_ROUNDS, self._history_rounds.value())
            self._settings.set(SETTINGS_KEYS.EXPORT_DIR, self._export_dir.text().strip())
            sync = getattr(self._settings, "sync", None)
            if callable(sync):
                sync()
        except AppError as exc:
            QMessageBox.critical(self, "保存设置失败", str(exc))
            return
        super().accept()

    def _load(self) -> None:
        """从设置存储读入当前值。"""
        self._autoscroll.setChecked(
            _as_bool(self._settings.get(SETTINGS_KEYS.AUTOSCROLL), True)
        )
        self._capacity.setValue(
            _clamp(_as_int(self._settings.get(SETTINGS_KEYS.LOG_CAPACITY), 100_000))
        )
        level = str(self._settings.get(SETTINGS_KEYS.LOG_LEVEL) or _DEFAULT_LOG_LEVEL).upper()
        if level not in _LOG_LEVELS:
            level = _DEFAULT_LOG_LEVEL
        self._log_level.setCurrentText(level)
        self._details_expanded.setChecked(
            _as_bool(self._settings.get(SETTINGS_KEYS.CHAT_DETAILS_EXPANDED), False)
        )
        self._history_rounds.setValue(
            _as_int(self._settings.get(SETTINGS_KEYS.LLM_HISTORY_ROUNDS), 0)
        )
        self._export_dir.setText(str(self._settings.get(SETTINGS_KEYS.EXPORT_DIR) or ""))

    def _choose_export_dir(self) -> None:
        """选择默认导出目录。"""
        current = self._export_dir.text().strip()
        chosen = QFileDialog.getExistingDirectory(self, "选择默认导出目录", current)
        if chosen:
            self._export_dir.setText(chosen)


def _as_bool(value: object, default: bool) -> bool:
    """把设置存储中的值稳健地转换为布尔（QSettings 可能是字符串）。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def _as_int(value: object, default: int) -> int:
    """把设置存储中的值稳健地转换为整数。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clamp(value: int) -> int:
    """把容量限制在合法范围内。"""
    return max(_MIN_CAPACITY, min(_MAX_CAPACITY, value))
