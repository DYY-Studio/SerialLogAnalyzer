"""
设备控制器 - 串口连接与日志流水线的桥接
把 core DeviceSession 的普通回调转成 Qt Signal
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QObject, Signal

from serial_log_analyzer.core.models.device import (
    SerialConfig,
    SerialPortInfo,
    DeviceConnectionState,
)
from serial_log_analyzer.core.models.logs import LogEntry
from serial_log_analyzer.core.services.device_session import (
    DeviceSession,
    DeviceSessionHandlers,
)
from serial_log_analyzer.core.errors import AppError


class DeviceController(QObject):
    """
    设备控制器
    
    Qt Signals:
    - log_entries_received(entries: list)
    - log_entry_updated(entry: LogEntry)
    - log_entries_removed(sequences: list)
    - connection_state_changed(state, message)
    - error_occurred(error: AppError)
    - ports_updated(ports: list)
    """

    log_entries_received = Signal(list)       # List[LogEntry]
    log_entry_updated = Signal(object)        # LogEntry
    log_entries_removed = Signal(list)        # List[int] sequences
    connection_state_changed = Signal(object, str)  # DeviceConnectionState, str
    error_occurred = Signal(object)           # AppError
    ports_updated = Signal(list)              # List[SerialPortInfo]

    def __init__(self, session: DeviceSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """把 core 的普通回调转成 Qt Signal"""
        handlers = DeviceSessionHandlers(
            on_update=self._on_pipeline_update,
            on_state=self._on_state_changed,
            on_error=self._on_error,
        )
        self._session.set_handlers(handlers)

    # ------------------------------------------------------------------
    # 对外操作接口
    # ------------------------------------------------------------------

    def connect(self, port: str, baudrate: int) -> None:
        """连接串口设备"""
        try:
            config = SerialConfig(
                port=port,
                baudrate=baudrate,
                data_bits=8,
                parity=None,
                stop_bits=1,
                flow_control=None,
            )
            self._session.connect(config)
        except AppError as e:
            self.error_occurred.emit(e)

    def disconnect(self) -> None:
        """断开串口"""
        self._session.disconnect()

    def refresh_ports(self) -> None:
        """刷新串口列表"""
        try:
            ports = self._session.list_ports()
            self.ports_updated.emit(ports)
        except AppError as e:
            self.error_occurred.emit(e)

    def send_command(self, command: str) -> None:
        """发送命令到设备"""
        try:
            self._session.send_command(command)
        except AppError as e:
            self.error_occurred.emit(e)

    # ------------------------------------------------------------------
    # core 回调处理
    # ------------------------------------------------------------------

    def _on_pipeline_update(self, update) -> None:
        """Pipeline 更新回调 - 转发给 UI"""
        if update.added:
            self.log_entries_received.emit(update.added)
        if update.updated:
            for entry in update.updated:
                self.log_entry_updated.emit(entry)
        if update.dropped_sequences:
            self.log_entries_removed.emit(update.dropped_sequences)

    def _on_state_changed(self, state: DeviceConnectionState, message: str) -> None:
        self.connection_state_changed.emit(state, message)

    def _on_error(self, error: AppError) -> None:
        self.error_occurred.emit(error)
