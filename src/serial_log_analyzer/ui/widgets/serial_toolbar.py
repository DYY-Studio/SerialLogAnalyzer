"""串口工具栏：端口 / 波特率 / 刷新 / 连接 / 清空，以及命令通道（DESIGN §7）。

只发射用户意图信号，不直接操作串口对象；实际动作由 :class:`DeviceController` 执行。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolBar,
    QWidget,
)

from serial_log_analyzer.core.models.device import (
    FlowControl,
    Parity,
    SerialConfig,
    SerialPortInfo,
    StopBits,
)
from serial_log_analyzer.core.models.provider import ProviderProfile

__all__ = ["SerialToolBar"]

_BAUDRATES = ("9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600")


class SerialToolBar(QToolBar):
    """顶部串口操作工具栏。

    信号（由控制器连接）:
        connect_requested(SerialConfig): 请求连接。
        disconnect_requested(): 请求断开。
        refresh_requested(): 请求刷新串口列表。
        clear_requested(): 请求清空日志。
        command_submitted(str): 请求发送一行命令。
        serial_settings_requested(): 请求打开串口高级设置。
        profile_changed(str): 用户切换了 LLM Profile（携带 profile_id）。
    """

    connect_requested = Signal(object)
    disconnect_requested = Signal()
    refresh_requested = Signal()
    clear_requested = Signal()
    command_submitted = Signal(str)
    serial_settings_requested = Signal()
    profile_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._advanced: dict[str, object] = {
            "data_bits": 8,
            "parity": Parity.NONE,
            "stop_bits": StopBits.ONE,
            "flow_control": FlowControl.NONE,
        }
        self._build()

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def set_ports(self, ports: list[SerialPortInfo]) -> None:
        """填充串口下拉列表，尽量保留当前选择。"""

        current = self.port_combo.currentData()
        self.port_combo.clear()
        for info in ports:
            label = f"{info.name} - {info.description}" if info.description else info.name
            self.port_combo.addItem(label, info.name)
        if current:
            index = self.port_combo.findData(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def set_connected(self, connected: bool) -> None:
        """按连接状态切换按钮与控件可用性。"""

        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.port_combo.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)

    def current_config(self) -> SerialConfig:
        """按当前界面选择构造 :class:`SerialConfig`。"""

        port = self.port_combo.currentData() or self.port_combo.currentText().strip()
        if not port:
            raise ValueError("请选择串口")
        return SerialConfig(
            port=str(port),
            baudrate=int(self.baud_combo.currentText()),
            **self._advanced,
        )

    def serial_values(self) -> dict[str, object]:
        """返回当前串口参数（供高级设置对话框初始化）。"""

        return {"baudrate": self.baud_combo.currentText(), **self._advanced}

    def apply_serial_settings(self, values: dict[str, object]) -> None:
        """应用高级设置对话框的结果。"""

        baudrate = str(values.get("baudrate", "") or "")
        if baudrate:
            index = self.baud_combo.findText(baudrate)
            if index >= 0:
                self.baud_combo.setCurrentIndex(index)
            else:
                self.baud_combo.setEditText(baudrate)
        for key in ("data_bits", "parity", "stop_bits", "flow_control"):
            if key in values:
                self._advanced[key] = values[key]

    def set_command_reply(self, text: str) -> None:
        """显示最近一条命令响应（DESIGN §7 的命令回复区）。"""

        self.reply_label.setText(text)

    def set_profiles(self, profiles: list[ProviderProfile], current: str = "") -> None:
        """填充 LLM Profile 下拉列表并选中 ``current``（不存在时选第一个）。"""

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in profiles:
            self.profile_combo.addItem(f"{profile.profile_id} · {profile.model}", profile.profile_id)
        index = self.profile_combo.findData(current)
        self.profile_combo.setCurrentIndex(index if index >= 0 else 0)
        self.profile_combo.blockSignals(False)

    def current_profile(self) -> str:
        """返回当前选中的 Profile 标识。"""

        return str(self.profile_combo.currentData() or "")

    def set_current_profile(self, profile_id: str) -> None:
        """在不触发信号的前提下把下拉框切到指定 Profile。"""

        index = self.profile_combo.findData(profile_id)
        if index < 0:
            return
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)

    def restore(self, port: str, baudrate: str) -> None:
        """按上次设置恢复端口与波特率选择。"""

        if baudrate:
            index = self.baud_combo.findText(str(baudrate))
            if index >= 0:
                self.baud_combo.setCurrentIndex(index)
        if port:
            index = self.port_combo.findData(port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # 构建与槽函数
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.addWidget(QLabel(" 串口 "))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        self.addWidget(self.port_combo)

        self.addWidget(QLabel(" 波特率 "))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(_BAUDRATES)
        self.baud_combo.setCurrentText("115200")
        self.addWidget(self.baud_combo)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        self.addWidget(self.refresh_btn)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(lambda: self.connect_requested.emit(self.current_config()))
        self.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self.disconnect_requested.emit)
        self.addWidget(self.disconnect_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        self.addWidget(self.clear_btn)

        self.settings_btn = QPushButton("串口设置…")
        self.settings_btn.clicked.connect(self.serial_settings_requested.emit)
        self.addWidget(self.settings_btn)

        self.addSeparator()
        self.addWidget(QLabel(" Profile "))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.currentIndexChanged.connect(
            lambda _index: self.profile_changed.emit(self.current_profile())
        )
        self.addWidget(self.profile_combo)

        self.addSeparator()
        self.addWidget(QLabel(" 命令 "))
        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText("PING / VERSION / HELP / TEST <name>")
        self.command_edit.setMinimumWidth(220)
        self.command_edit.returnPressed.connect(self._on_command)
        self.addWidget(self.command_edit)
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._on_command)
        self.addWidget(self.send_btn)

        self.reply_label = QLabel("")
        self.addWidget(self.reply_label)

    def _on_command(self) -> None:
        command = self.command_edit.text().strip()
        if command:
            self.command_edit.clear()
            self.command_submitted.emit(command)
