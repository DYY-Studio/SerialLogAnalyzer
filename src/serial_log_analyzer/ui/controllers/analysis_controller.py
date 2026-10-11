"""分析控制器：把 ``AnalysisService`` 的回调转译为 Qt Signal，并驱动分析面板。

负责组装上下文（经 ``AnalysisContextBuilder``）、发起分析/追问、取消与清空会话。
结果以完整快照推送（日志分析输出很短，快照重绘最简单且不会重复追加）。
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.models.analysis import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisState,
    ContextSelector,
)
from serial_log_analyzer.core.services.analysis import (
    AnalysisContextBuilder,
    AnalysisService,
    AnalysisServiceHandlers,
)

__all__ = ["AnalysisController"]


class AnalysisController(QObject):
    """LLM 分析控制器。

    信号:
        result_updated(object): 结果快照（累积后的完整结果）。
        state_changed(object): 状态变化（:class:`AnalysisState`）。
        error_occurred(str): 错误文本。
        usage_updated(int, int, int): 用量统计更新（输入 / 输出 / 总计）。
    """

    result_updated = Signal(object)
    state_changed = Signal(object)
    error_occurred = Signal(str)
    usage_updated = Signal(int, int, int)

    def __init__(self, service: AnalysisService, context_builder: AnalysisContextBuilder) -> None:
        super().__init__()
        self._service = service
        self._builder = context_builder
        self._selected: list[int] = []
        self._usage: object = None
        service.set_handlers(
            AnalysisServiceHandlers(
                on_result=self._on_result,
                on_state=self.state_changed.emit,
                on_error=self._on_error,
            )
        )

    def selected_sequences(self, selected: list[int]) -> None:
        """记录用户当前在表格中选中的条目序号，供上下文构造使用。"""

        self._selected = list(selected)

    def start_analysis(self, request: AnalysisRequest, selector: ContextSelector) -> None:
        """按界面选择（含上下文选择器）构造上下文并开始一轮分析。"""

        try:
            context = self._builder.build(selector, selected_sequences=self._selected)
            self._service.ask(replace(request, context=context))
        except AppError as exc:
            self.error_occurred.emit(str(exc))

    def follow_up(self, text: str) -> None:
        """在当前会话中追问。"""

        try:
            self._service.follow_up(text)
        except AppError as exc:
            self.error_occurred.emit(str(exc))

    def cancel(self) -> None:
        """取消进行中的请求。"""

        self._service.cancel()

    def reset(self) -> None:
        """清空会话与结果面板。"""

        self._service.reset()
        self.result_updated.emit(AnalysisResult())
        self.state_changed.emit(AnalysisState.IDLE)

    def _on_error(self, error: Exception) -> None:
        self.error_occurred.emit(str(error))

    def _on_result(self, result: AnalysisResult) -> None:
        self.result_updated.emit(result)
        usage = result.usage
        if usage is not None and usage != self._usage:
            self._usage = usage
            self.usage_updated.emit(usage.input_tokens, usage.output_tokens, usage.total_tokens)
