"""分析控制器：把分析服务的回调转译为 Qt Signal，并驱动分析面板。

负责：
- 收集界面上的上下文选择（选中行、最近 N 条、仅 ERROR、手动输入）；
- 调用 :class:`AnalysisService` 开始分析或追问；
- 把结果增量、状态变化与错误转译为 Qt Signal。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

__all__ = ["AnalysisController"]


class AnalysisController(QObject):
    """LLM 分析控制器。

    信号:
        result_updated: 结果快照更新（累积后的完整结果）。
        state_changed: 状态变化，携带 :class:`AnalysisState`。
        error_occurred: 错误文本。
        usage_updated: 用量统计更新。
    """

    result_updated = Signal(object)
    state_changed = Signal(object)
    error_occurred = Signal(str)
    usage_updated = Signal(int, int, int)

    def __init__(self, service: object, context_builder: object) -> None:
        """参数: service — :class:`AnalysisService`；context_builder — 上下文构造器。"""

        super().__init__()
        raise NotImplementedError

    def start_analysis(self, request: object) -> None:
        """开始一轮分析；单次模式会清空既有会话。"""

        raise NotImplementedError

    def follow_up(self, text: str) -> None:
        """在当前会话中追问。"""

        raise NotImplementedError

    def cancel(self) -> None:
        """取消进行中的请求。"""

        raise NotImplementedError

    def reset(self) -> None:
        """清空会话与结果面板。"""

        raise NotImplementedError

    def selected_sequences(self, selected: list[int]) -> None:
        """记录用户当前在表格中选中的条目序号，供上下文构造使用。"""

        raise NotImplementedError
