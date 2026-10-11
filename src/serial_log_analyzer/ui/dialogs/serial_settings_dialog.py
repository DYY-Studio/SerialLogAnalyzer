"""串口参数对话框：数据位 / 停止位 / 校验位 / 流控。

波特率在工具栏下拉里设置（可编辑），此处不重复提供。
取自 ``origin/feature/ui-improvement`` 的实现，改为使用 core 的枚举值，
避免界面层再定义一套字符串映射。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from serial_log_analyzer.core.models.device import FlowControl, Parity, StopBits

__all__ = ["SerialSettingsDialog"]

_DATA_BITS = ("5", "6", "7", "8")
_STOP_BITS: tuple[tuple[str, StopBits], ...] = (
    ("1", StopBits.ONE),
    ("1.5", StopBits.ONE_POINT_FIVE),
    ("2", StopBits.TWO),
)
_PARITY: tuple[tuple[str, Parity], ...] = (
    ("无", Parity.NONE),
    ("偶校验", Parity.EVEN),
    ("奇校验", Parity.ODD),
    ("标记", Parity.MARK),
    ("空格", Parity.SPACE),
)
_FLOW: tuple[tuple[str, FlowControl], ...] = (
    ("无", FlowControl.NONE),
    ("硬件 (RTS/CTS)", FlowControl.HARDWARE),
    ("软件 (XON/XOFF)", FlowControl.SOFTWARE),
)


class SerialSettingsDialog(QDialog):
    """串口参数对话框。

    参数:
        parent: 可选父窗口。
        current: 当前参数（``data_bits`` / ``parity`` / ``stop_bits`` / ``flow_control``），
            缺省用 8-N-1 无流控。
    """

    def __init__(self, parent: QWidget | None = None, current: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("串口设置")
        self.setMinimumWidth(460)
        self._build()
        self._load(current or {})

    def values(self) -> dict[str, object]:
        """返回对话框中的串口参数（不含波特率）。"""

        return {
            "data_bits": int(self.data_bits.currentText()),
            "parity": self.parity_combo.currentData(),
            "stop_bits": self.stop_bits.currentData(),
            "flow_control": self._checked_flow(),
        }

    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        group = QGroupBox("串口参数")
        grid = QGridLayout(group)

        grid.addWidget(QLabel("数据位"), 0, 0)
        self.data_bits = QComboBox()
        self.data_bits.addItems(_DATA_BITS)
        grid.addWidget(self.data_bits, 0, 1)

        grid.addWidget(QLabel("停止位"), 0, 2)
        self.stop_bits = QComboBox()
        for label, value in _STOP_BITS:
            self.stop_bits.addItem(label, value)
        grid.addWidget(self.stop_bits, 0, 3)

        grid.addWidget(QLabel("校验位"), 1, 0)
        self.parity_combo = QComboBox()
        for label, value in _PARITY:
            self.parity_combo.addItem(label, value)
        grid.addWidget(self.parity_combo, 1, 1)
        layout.addWidget(group)

        flow_group = QGroupBox("流控")
        flow_layout = QHBoxLayout(flow_group)
        self._flow_buttons = QButtonGroup(self)
        for index, (label, value) in enumerate(_FLOW):
            button = QRadioButton(label)
            button.setProperty("flow", value)
            self._flow_buttons.addButton(button, index)
            flow_layout.addWidget(button)
        layout.addWidget(flow_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self, current: dict) -> None:
        self.data_bits.setCurrentText(str(current.get("data_bits", 8)))
        self._select(self.stop_bits, current.get("stop_bits", StopBits.ONE))
        self._select(self.parity_combo, current.get("parity", Parity.NONE))
        wanted = current.get("flow_control", FlowControl.NONE)
        for index, (_, value) in enumerate(_FLOW):
            if value is wanted:
                self._flow_buttons.button(index).setChecked(True)
                return

    @staticmethod
    def _select(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _checked_flow(self) -> FlowControl:
        button = self._flow_buttons.checkedButton()
        if button is None:  # pragma: no cover - 默认已勾选“无”
            return FlowControl.NONE
        return button.property("flow")
