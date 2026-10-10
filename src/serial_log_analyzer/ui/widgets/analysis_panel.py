"""分析面板：上下文选择、目标选择、结果展示与追问输入。

流式输出时增量追加正文；提供“停止”“新会话”“复制结果”等操作。
只与 :class:`AnalysisController` 交互。
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from serial_log_analyzer.core.models.analysis import AnalysisResult

__all__ = ["AnalysisPanel"]


class AnalysisPanel(QWidget):
    """LLM 分析结果与输入面板。

    信号（由控制器连接）:
        analyze_requested(object): 携带 :class:`AnalysisRequest`。
        follow_up_requested(str): 追问文本。
        cancel_requested(): 请求取消。
        reset_requested(): 请求清空会话。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def set_result(self, result: AnalysisResult) -> None:
        """更新结果展示（累积后的快照）。"""

        raise NotImplementedError

    def append_delta(self, text: str) -> None:
        """流式追加正文增量。"""

        raise NotImplementedError

    def set_state(self, state: object) -> None:
        """根据分析状态切换按钮可用性与进度提示。"""

        raise NotImplementedError

    def set_goals(self, goals: list[object]) -> None:
        """填充预设分析目标下拉列表。"""

        raise NotImplementedError
