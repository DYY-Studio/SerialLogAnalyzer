"""设备控制器：把 ``DeviceSession`` 的普通回调转译为 Qt Signal。

串口刷新/连接/断开/命令与清空全部委托给 core 服务；控制器负责：
- 约 40ms 批量聚合 ``PipelineUpdate`` 后推送给界面，并在断开/退出前同步 flush；
- 基于单次 ``QTimer`` 的命令响应超时检测（默认 2000ms），不修改核心协议。
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Sequence

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from serial_log_analyzer.core.device.command import CommandReply
from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.models.device import DeviceConnectionState, SerialConfig
from serial_log_analyzer.core.models.logs import LogEntry
from serial_log_analyzer.core.services.device_session import DeviceSession, DeviceSessionHandlers

__all__ = ["DeviceController", "coalesce_updates"]


def coalesce_updates(updates: Sequence[PipelineUpdate]) -> PipelineUpdate:
    """把一批 :class:`PipelineUpdate` 合并为单次增量载荷。

    同一批次内先新增后被 continuation 合并的条目只保留最新内容在 ``added`` 中；
    同一批次内先新增又被容量淘汰的条目直接抵消，避免界面无意义地插入后立即删除。
    """

    added_by_seq: dict[int, LogEntry] = {}
    updated_by_seq: dict[int, LogEntry] = {}
    dropped: list[int] = []
    dropped_set: set[int] = set()

    for update in updates:
        for entry in update.added:
            added_by_seq[entry.sequence] = entry
        for entry in update.updated:
            if entry.sequence in added_by_seq:
                added_by_seq[entry.sequence] = entry
            else:
                updated_by_seq[entry.sequence] = entry
        for sequence in update.dropped_sequences:
            if sequence in added_by_seq:
                added_by_seq.pop(sequence, None)
                continue
            updated_by_seq.pop(sequence, None)
            if sequence not in dropped_set:
                dropped_set.add(sequence)
                dropped.append(sequence)

    return PipelineUpdate(
        added=tuple(added_by_seq.values()),
        updated=tuple(updated_by_seq.values()),
        dropped_sequences=tuple(dropped),
    )


class DeviceController(QObject):
    """串口设备控制器。

    参数:
        session: 设备会话服务。
        batch_interval_ms: 日志批量刷新间隔（毫秒），默认 40ms。
        command_timeout_ms: 命令等待回复超时（毫秒），默认 2000ms。

    信号:
        ports_refreshed(list): 串口列表刷新完成。
        connection_changed(object, str): 连接状态与说明文本。
        log_update(object): 经批处理聚合后的日志增量载荷（:class:`PipelineUpdate`）。
        error_occurred(str): 错误文本，供状态栏展示。
        command_reply(object): 命令响应（:class:`CommandReply`）。
        command_timed_out(str): 超时未收到响应的命令文本。
    """

    ports_refreshed = Signal(list)
    connection_changed = Signal(object, str)
    log_update = Signal(object)
    error_occurred = Signal(str)
    command_reply = Signal(object)
    command_timed_out = Signal(str)

    def __init__(
        self,
        session: DeviceSession,
        *,
        batch_interval_ms: int = 40,
        command_timeout_ms: int = 2000,
    ) -> None:
        super().__init__()
        if batch_interval_ms <= 0:
            raise ValueError(f"批处理间隔必须为正整数：{batch_interval_ms}")
        if command_timeout_ms <= 0:
            raise ValueError(f"命令超时时间必须为正整数：{command_timeout_ms}")
        self._session = session
        self._command_timeout_ms = command_timeout_ms
        self._pending_updates: list[PipelineUpdate] = []
        self._pending_commands: deque[tuple[str, float]] = deque()

        self._batch_timer = QTimer(self)
        self._batch_timer.setSingleShot(True)
        self._batch_timer.setInterval(batch_interval_ms)
        self._batch_timer.timeout.connect(self.flush_updates)

        self._command_timer = QTimer(self)
        self._command_timer.setSingleShot(True)
        self._command_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._command_timer.timeout.connect(self._on_command_timeout)

        session.set_handlers(
            DeviceSessionHandlers(
                on_update=self._on_pipeline_update,
                on_state=self._on_session_state,
                on_error=self._on_error,
                on_command_reply=self._on_command_reply,
            )
        )

    def refresh_ports(self) -> None:
        """刷新串口列表并通过 ``ports_refreshed`` 通知界面。"""

        try:
            ports = self._session.list_ports()
        except AppError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.ports_refreshed.emit(ports)

    def connect(self, config: SerialConfig) -> None:
        """按配置连接设备；失败时状态与错误由会话回调上报。"""

        try:
            self._session.connect(config)
        except AppError as exc:
            self.error_occurred.emit(str(exc))

    def disconnect(self) -> None:
        """断开设备并同步刷新缓冲日志、取消待回复命令计时。"""

        try:
            self._session.disconnect()
        except AppError as exc:
            self.error_occurred.emit(str(exc))
        finally:
            self.flush_updates()
            self._clear_command_timeouts()

    def send_command(self, command: str) -> None:
        """发送一行文本命令并启动回复超时计时。"""

        try:
            self._session.send_command(command)
        except AppError as exc:
            self.error_occurred.emit(str(exc))
            return
        now = time.monotonic()
        self._pending_commands.append((command, now))
        self._arm_command_timer(now)

    def clear_logs(self) -> None:
        """丢弃尚未发射的批处理缓冲并清空日志流水线。"""

        self._batch_timer.stop()
        self._pending_updates.clear()
        self._session.pipeline.clear()

    def flush_updates(self) -> None:
        """立即把累积的日志增量合并后发射给界面。"""

        self._batch_timer.stop()
        if not self._pending_updates:
            return
        merged = coalesce_updates(self._pending_updates)
        self._pending_updates.clear()
        if merged.added or merged.updated or merged.dropped_sequences:
            self.log_update.emit(merged)

    def shutdown(self) -> None:
        """退出前刷出剩余日志并停止全部内部定时器。"""

        self.flush_updates()
        self._clear_command_timeouts()

    @property
    def state(self) -> DeviceConnectionState:
        """当前连接状态（供界面初始化）。"""

        return self._session.state

    def _on_pipeline_update(self, update: PipelineUpdate) -> None:
        if not (update.added or update.updated or update.dropped_sequences):
            return
        self._pending_updates.append(update)
        if not self._batch_timer.isActive():
            self._batch_timer.start()

    def _on_session_state(self, state: DeviceConnectionState, message: str) -> None:
        if state in (DeviceConnectionState.DISCONNECTED, DeviceConnectionState.ERROR):
            self.flush_updates()
            self._clear_command_timeouts()
        self.connection_changed.emit(state, message)

    def _on_command_reply(self, reply: CommandReply) -> None:
        if self._pending_commands:
            self._pending_commands.popleft()
            self._arm_command_timer(time.monotonic())
        self.command_reply.emit(reply)

    def _on_command_timeout(self) -> None:
        now = time.monotonic()
        timeout_s = self._command_timeout_ms / 1000.0
        while self._pending_commands and (now - self._pending_commands[0][1]) >= timeout_s - 0.001:
            command, _ = self._pending_commands.popleft()
            self.command_timed_out.emit(command)
        self._arm_command_timer(now)

    def _arm_command_timer(self, now: float) -> None:
        if not self._pending_commands:
            self._command_timer.stop()
            return
        _, sent_at = self._pending_commands[0]
        remaining_ms = max(1, math.ceil(self._command_timeout_ms - (now - sent_at) * 1000.0))
        self._command_timer.start(remaining_ms)

    def _clear_command_timeouts(self) -> None:
        self._command_timer.stop()
        self._pending_commands.clear()

    def _on_error(self, error: AppError) -> None:
        self.error_occurred.emit(str(error))
