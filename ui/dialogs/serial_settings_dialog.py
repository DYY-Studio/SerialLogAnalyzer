"""
串口设置对话框 - 完整参数设置
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QGridLayout,
    QComboBox,
    QLabel,
    QPushButton,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QDialogButtonBox,
)


# 常用波特率
BAUDRATES = [
    "1200", "2400", "4800", "9600", "14400", "19200",
    "38400", "57600", "115200", "128000", "230400",
    "460800", "500000", "576000", "921600", "1000000",
]

DATA_BITS = ["5", "6", "7", "8"]
STOP_BITS = ["1", "1.5", "2"]
PARITY_OPTIONS = ["NONE", "EVEN", "ODD", "MARK", "SPACE"]


class SerialSettingsDialog(QDialog):
    """
    串口设置对话框
    
    布局：网格排列，和Qt设计师截图一致
    """

    def __init__(self, parent=None, current_settings: dict = None):
        super().__init__(parent)
        self.setWindowTitle("串口设置")
        self.setMinimumWidth(520)
        self._settings = current_settings or {}
        self._setup_ui()
        self._load_defaults()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 串口选项分组
        group = QGroupBox("串口选项")
        grid = QGridLayout(group)
        grid.setSpacing(12)
        grid.setContentsMargins(16, 24, 16, 16)

        # 第一行：波特率、数据位
        grid.addWidget(QLabel("波特率:"), 0, 0)
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(BAUDRATES)
        self.baud_combo.setMinimumWidth(160)
        self.baud_combo.setFixedHeight(32)
        grid.addWidget(self.baud_combo, 0, 1)

        grid.addWidget(QLabel("数据位:"), 0, 2)
        self.databits_combo = QComboBox()
        self.databits_combo.addItems(DATA_BITS)
        self.databits_combo.setMinimumWidth(100)
        self.databits_combo.setFixedHeight(32)
        grid.addWidget(self.databits_combo, 0, 3)

        # 第二行：停止位、校验位
        grid.addWidget(QLabel("停止位:"), 1, 0)
        self.stopbits_combo = QComboBox()
        self.stopbits_combo.addItems(STOP_BITS)
        self.stopbits_combo.setMinimumWidth(100)
        self.stopbits_combo.setFixedHeight(32)
        grid.addWidget(self.stopbits_combo, 1, 1)

        grid.addWidget(QLabel("校验位:"), 1, 2)
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(PARITY_OPTIONS)
        self.parity_combo.setMinimumWidth(120)
        self.parity_combo.setFixedHeight(32)
        grid.addWidget(self.parity_combo, 1, 3)

        layout.addWidget(group)

        # 流控选项分组
        flow_group = QGroupBox("流控选项")
        flow_layout = QVBoxLayout(flow_group)
        flow_layout.setSpacing(10)
        flow_layout.setContentsMargins(16, 24, 16, 16)

        self.flow_group = QButtonGroup(self)

        row1 = QHBoxLayout()
        self.flow_none = QRadioButton("None")
        self.flow_none.setChecked(True)
        self.flow_group.addButton(self.flow_none, 0)
        row1.addWidget(self.flow_none)

        self.flow_hardware = QRadioButton("Hardware (RTS/CTS)")
        self.flow_group.addButton(self.flow_hardware, 1)
        row1.addWidget(self.flow_hardware)

        self.flow_software = QRadioButton("Software (XON/XOFF)")
        self.flow_group.addButton(self.flow_software, 2)
        row1.addWidget(self.flow_software)

        flow_layout.addLayout(row1)
        layout.addWidget(flow_group)

        # 底部按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_defaults(self) -> None:
        """加载默认设置"""
        baud = self._settings.get("baudrate", "115200")
        self.baud_combo.setCurrentText(str(baud))

        databits = str(self._settings.get("data_bits", "8"))
        idx = self.databits_combo.findText(databits)
        if idx >= 0:
            self.databits_combo.setCurrentIndex(idx)

        stopbits = str(self._settings.get("stop_bits", "1"))
        idx = self.stopbits_combo.findText(stopbits)
        if idx >= 0:
            self.stopbits_combo.setCurrentIndex(idx)

        parity = self._settings.get("parity", "NONE")
        idx = self.parity_combo.findText(parity)
        if idx >= 0:
            self.parity_combo.setCurrentIndex(idx)

        flow = self._settings.get("flow_control", "None")
        if flow == "Hardware":
            self.flow_hardware.setChecked(True)
        elif flow == "Software":
            self.flow_software.setChecked(True)
        else:
            self.flow_none.setChecked(True)

    def get_settings(self) -> dict:
        """获取串口参数设置"""
        flow_map = {0: "None", 1: "Hardware", 2: "Software"}
        return {
            "baudrate": int(self.baud_combo.currentText()),
            "data_bits": int(self.databits_combo.currentText()),
            "stop_bits": self.stopbits_combo.currentText(),
            "parity": self.parity_combo.currentText(),
            "flow_control": flow_map[self.flow_group.checkedId()],
        }
