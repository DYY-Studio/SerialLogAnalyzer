"""日志领域模型：日志级别与日志条目。

设计要点：
- :class:`LogLevel` 为固定级别集，保证过滤、排序、颜色与 LLM 上下文选择具有一致语义；
  Preset 只负责把板上的级别标识映射到该集合，未识别值映射为 ``UNKNOWN``。
- :class:`LogEntry` 保留原始行 ``raw``，即使解析失败也允许生成记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = ["LogEntry", "LogLevel"]


class LogLevel(Enum):
    """固定日志级别集，``value`` 为可比较的严重度序号（越大越严重）。"""

    VERBOSE = 0
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    UNKNOWN = 5


@dataclass
class LogEntry:
    """单条日志记录。

    参数:
        sequence: 递增序号，由日志流水线分配，用于稳定排序与去重。
        received_at: PC 端接收该行的时间戳（``time.time()`` 秒）。
        level: 解析出的日志级别；无法识别时为 ``LogLevel.UNKNOWN``。
        message: 解析出的消息正文；多行合并时会在末尾追加后续行。
        raw: 原始文本（多行合并时包含所有并入的行），用于导出与人工核对。
        device_time: 板上时间戳原文；v1 默认无，使用该字段的 Preset 才会填充。
        module: 模块 / tag 名；日志格式未提供时为 ``None``。
        continuation: 该条是否由多行合并产生（即自身或后续存在 continuation 行）。
        extra: 预留的结构化字段（如 Preset 捕获的 ``key=value``）；当前恒为空，
            带默认值以维持构造兼容，后续扩展无需改动调用方。
    """

    sequence: int
    received_at: float
    level: LogLevel
    message: str
    raw: str
    device_time: str | None = None
    module: str | None = None
    continuation: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    def display_time(self) -> str:
        """返回用于表格展示的时间文本。

        优先使用板上时间戳；缺失时由 UI 层按 ``received_at`` 格式化，本方法只提供
        秒级字符串以保证 core 不依赖任何本地化 / Qt 时间格式化。
        """

        if self.device_time:
            return self.device_time
        return f"{self.received_at:.3f}"
