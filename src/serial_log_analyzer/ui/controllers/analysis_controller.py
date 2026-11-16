"""分析控制器：把 ``AnalysisService`` 的回调转译为 Qt Signal，并驱动分析面板。

负责组装上下文（经 ``AnalysisContextBuilder``）、发起分析/追问、取消与清空会话。
结果以完整快照推送（日志分析输出很短，快照重绘最简单且不会重复追加）。
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.models.analysis import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisState,
    ContextSelector,
)
from serial_log_analyzer.core.models.anomaly import AnomalyCluster
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
        usage_cleared(): 会话重置时通知清空状态栏用量摘要。
    """

    result_updated = Signal(object)
    state_changed = Signal(object)
    error_occurred = Signal(str)
    usage_updated = Signal(int, int, int)
    usage_cleared = Signal()

    def __init__(self, service: AnalysisService, context_builder: AnalysisContextBuilder) -> None:
        super().__init__()
        self._service = service
        self._builder = context_builder
        self._selected: list[int] = []
        self._usage: object = None
        self._streaming = False
        service.set_handlers(
            AnalysisServiceHandlers(
                on_result=self._on_result,
                on_state=self._on_state,
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

    def analyze_cluster(self, cluster: AnomalyCluster) -> bool:
        """围绕指定异常簇的证据序号构造上下文并发起聚合根因分析。

        参数:
            cluster: 待诊断的只读异常簇快照。

        返回:
            分析成功发起时返回 ``True``；因正忙、证据缺失或凭据错误失败时发出
            :attr:`error_occurred` 并返回 ``False``。
        """

        try:
            if self._streaming:
                raise ConfigError("已有进行中的分析，请先取消或等待完成")
            sequences = list(cluster.evidence_sequences)
            if not sequences:
                raise ConfigError("该异常簇没有可用于分析的日志证据")
            context = self._builder.build(
                ContextSelector.SELECTED_WITH_NEIGHBORS,
                selected_sequences=sequences,
            )
            if self._service.conversation:
                self.reset()
            request = AnalysisRequest(
                goal_id="aggregate-anomalies",
                user_input=(
                    f"请重点分析异常簇 {cluster.cluster_id}（规则 {cluster.rule_id}，"
                    f"类别 {cluster.category}，严重度 {cluster.severity.name}，"
                    f"累计 {cluster.occurrence_count} 次）：{cluster.normalized_message}"
                ),
                context=context,
            )
            self._service.ask(request)
        except AppError as exc:
            self.error_occurred.emit(str(exc))
            return False
        return True

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
        self._usage = None
        self.usage_cleared.emit()
        self.result_updated.emit(AnalysisResult())
        self.state_changed.emit(AnalysisState.IDLE)

    def _on_state(self, state: AnalysisState) -> None:
        self._streaming = state is AnalysisState.STREAMING
        self.state_changed.emit(state)

    def _on_error(self, error: Exception) -> None:
        self.error_occurred.emit(str(error))

    def _on_result(self, result: AnalysisResult) -> None:
        self.result_updated.emit(result)
        usage = result.usage
        if usage is not None and usage != self._usage:
            self._usage = usage
            self.usage_updated.emit(usage.input_tokens, usage.output_tokens, usage.total_tokens)
