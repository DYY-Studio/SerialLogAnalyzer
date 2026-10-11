"""
串口工具栏 - 串口选择、波特率、连接控制
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QLineEdit,
)

from serial_log_analyzer.core.models.device import SerialPortInfo, DeviceConnectionState


BAUDRATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]


class SerialToolbar(QWidget):
    """
    串口连接工具栏
    
    信号：
    - connect_clicked(port: str, baudrate: int)
    - disconnect_clicked()
    - refresh_clicked()
    - send_command_clicked(command: str)
    """

    connect_clicked = Signal(str, int)
    disconnect_clicked = Signal()
    refresh_clicked = Signal()
    send_command_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = {}
        self._setup_ui()
        self._state = DeviceConnectionState.DISCONNECTED

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        # 串口选择
        layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        self.port_combo.setFixedHeight(32)
        layout.addWidget(self.port_combo)

        # 刷新按钮
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedHeight(32)
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        layout.addWidget(self.refresh_btn)

        # 波特率
        layout.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUDRATES)
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setMinimumWidth(110)
        self.baud_combo.setFixedHeight(32)
        layout.addWidget(self.baud_combo)

        # 高级设置按钮
        self.settings_btn = QPushButton("⚙ 设置")
        self.settings_btn.setFixedHeight(32)
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        layout.addWidget(self.settings_btn)

        # 连接/断开按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setCheckable(True)
        self.connect_btn.setFixedHeight(32)
        self.connect_btn.setMinimumWidth(80)
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        layout.addWidget(self.connect_btn)

        layout.addStretch()

        # 命令输入
        layout.addWidget(QLabel("命令:"))
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("输入命令...")
        self.command_input.setMaximumWidth(220)
        self.command_input.setFixedHeight(32)
        self.command_input.returnPressed.connect(self._on_send_command)
        layout.addWidget(self.command_input)

        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedHeight(32)
        self.send_btn.clicked.connect(self._on_send_command)
        layout.addWidget(self.send_btn)

    # ------------------------------------------------------------------
    # 外部接口
    # ------------------------------------------------------------------

    def update_ports(self, ports: List[SerialPortInfo]) -> None:
        """更新串口列表"""
        current = self.port_combo.currentText()
        self.port_combo.clear()
        for port in ports:
            label = f"{port.name} - {port.description}" if port.description else port.name
            self.port_combo.addItem(label, port.name)

        if current:
            idx = self.port_combo.findData(current.split(" - ")[0])
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def set_state(self, state: DeviceConnectionState, message: str = "") -> None:
        """更新连接状态显示"""
        self._state = state
        is_connected = state == DeviceConnectionState.CONNECTED
        is_connecting = state == DeviceConnectionState.CONNECTING

        self.connect_btn.blockSignals(True)
        self.connect_btn.setChecked(is_connected or is_connecting)
        if is_connected:
            self.connect_btn.setText("断开")
        elif is_connecting:
            self.connect_btn.setText("连接中...")
        else:
            self.connect_btn.setText("连接")
        self.connect_btn.blockSignals(False)

        self.port_combo.setEnabled(not is_connected)
        self.baud_combo.setEnabled(not is_connected)
        self.refresh_btn.setEnabled(not is_connected)

    # ------------------------------------------------------------------
    # 内部槽函数
    # ------------------------------------------------------------------

    def _on_connect_clicked(self, checked: bool) -> None:
        if checked:
            port = self.port_combo.currentData() or self.port_combo.currentText().split(" - ")[0]
            baudrate = int(self.baud_combo.currentText())
            self.connect_clicked.emit(port, baudrate)
        else:
            self.disconnect_clicked.emit()

    def _on_send_command(self) -> None:
        cmd = self.command_input.text().strip()
        if cmd:
            self.send_command_clicked.emit(cmd)
            self.command_input.clear()

    def _open_settings_dialog(self) -> None:
        """打开串口设置对话框"""
        try:
            from ..dialogs.serial_settings_dialog import SerialSettingsDialog
        except ImportError:
            # demo环境下回退：直接导入
            import sys
            sys.path.insert(0, r"C:\Users\Administrator\Doubao\chats\2026-10-10\new-chat\SerialLogAnalyzer")
            from ui.dialogs.serial_settings_dialog import SerialSettingsDialog

        dialog = SerialSettingsDialog(self, current_settings=self._settings)
        if dialog.exec():
            self._settings = dialog.get_settings()
            # 同步波特率到工具栏
            self.baud_combo.setCurrentText(str(self._settings["baudrate"]))
