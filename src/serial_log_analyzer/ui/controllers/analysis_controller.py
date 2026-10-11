"""
分析控制器 - LLM 分析服务的桥接
把 core AnalysisService 的回调转成 Qt Signal
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from serial_log_analyzer.core.models.analysis import (
    AnalysisMode,
    ContextSelector,
    AnalysisState,
)
from serial_log_analyzer.core.services.analysis import AnalysisService
from serial_log_analyzer.core.errors import AppError


class AnalysisController(QObject):
    """
    分析控制器
    
    Qt Signals:
    - stream_chunk_received(chunk: str)
    - analysis_state_changed(state, message)
    - error_occurred(error: AppError)
    """

    stream_chunk_received = Signal(str)
    analysis_state_changed = Signal(object, str)  # AnalysisState, str
    error_occurred = Signal(object)               # AppError

    def __init__(self, service: AnalysisService, parent=None):
        super().__init__(parent)
        self._service = service
        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        """设置 core 服务的回调"""
        self._service.on_stream_chunk = self._on_stream_chunk
        self._service.on_state_changed = self._on_state_changed
        self._service.on_error = self._on_error

    # ------------------------------------------------------------------
    # 对外操作接口
    # ------------------------------------------------------------------

    def start_analysis(
        self,
        mode: AnalysisMode,
        selector: ContextSelector,
        user_input: str,
        selected_sequences: list[int] | None = None,
    ) -> None:
        """启动分析"""
        try:
            self._service.analyze(
                mode=mode,
                selector=selector,
                user_input=user_input,
                selected_sequences=selected_sequences or [],
            )
        except AppError as e:
            self.error_occurred.emit(e)

    def send_followup(self, message: str) -> None:
        """发送多轮追问"""
        try:
            self._service.send_followup(message)
        except AppError as e:
            self.error_occurred.emit(e)

    def new_session(self) -> None:
        """开启新会话"""
        self._service.reset_session()
        self.analysis_state_changed.emit(AnalysisState.IDLE, "")

    # ------------------------------------------------------------------
    # core 回调处理
    # ------------------------------------------------------------------

    def _on_stream_chunk(self, chunk: str) -> None:
        self.stream_chunk_received.emit(chunk)

    def _on_state_changed(self, state: AnalysisState, message: str) -> None:
        self.analysis_state_changed.emit(state, message)

    def _on_error(self, error: AppError) -> None:
        self.error_occurred.emit(error)
