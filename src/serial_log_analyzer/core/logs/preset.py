"""日志 Preset：声明式解析规则的数据结构与校验。

Preset 只描述规则，不允许执行任意 Python 表达式、``eval`` 或嵌入脚本。
复杂逻辑通过预定义的有限字段提供（正则捕获组、级别映射、continuation 规则）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from serial_log_analyzer.core.models.logs import LogLevel

__all__ = ["ContinuationMode", "FallbackRule", "LogPreset", "PresetLineRule"]


class ContinuationMode(Enum):
    """多行日志合并策略。"""

    MERGE_PREVIOUS = "merge_previous"
    """匹配 ``continuation_pattern`` 的行并入上一条。"""

    NONE = "none"
    """不做合并，每行独立成条。"""


@dataclass(frozen=True)
class PresetLineRule:
    """单条日志行的匹配与字段提取规则。

    参数:
        pattern: 已编译的正则；应包含 ``level`` / ``module`` / ``message`` 命名组，
            可选 ``time`` 组；其余命名组会被忽略。
        level_group: 级别所在的捕获组名。
        module_group: 模块 / tag 所在的捕获组名。
        message_group: 消息正文所在的捕获组名。
        time_group: 板上时间戳所在的捕获组名；无则为 ``None``。
        level_map: 板上级别标识到 :class:`LogLevel` 的映射；未命中时使用 fallback。
        continuation_mode: 多行合并策略。
        continuation_pattern: 已编译的 continuation 正则；``MERGE_PREVIOUS`` 时必需。
    """

    pattern: re.Pattern[str]
    level_group: str = "level"
    module_group: str = "module"
    message_group: str = "message"
    time_group: str | None = None
    level_map: dict[str, LogLevel] = field(default_factory=dict)
    continuation_mode: ContinuationMode = ContinuationMode.MERGE_PREVIOUS
    continuation_pattern: re.Pattern[str] | None = None


@dataclass(frozen=True)
class FallbackRule:
    """无法匹配任何行规则时的降级处理规则。

    参数:
        enabled: 是否启用；关闭时不匹配的行会被忽略。
        level: 降级条目的级别。
    """

    enabled: bool = True
    level: LogLevel = LogLevel.UNKNOWN


@dataclass(frozen=True)
class LogPreset:
    """一份完整的日志解析 Preset。

    参数:
        preset_id: 唯一标识。
        display_name: 界面展示名。
        schema_version: 声明文件版本，当前为 ``1``。
        line: 行规则。
        fallback: 降级规则。
        source_path: 加载来源路径，用于错误提示。
    """

    preset_id: str
    display_name: str
    line: PresetLineRule
    fallback: FallbackRule = field(default_factory=FallbackRule)
    schema_version: int = 1
    source_path: str = ""

    def level_from_token(self, token: str) -> LogLevel:
        """把板上级别标识映射为 :class:`LogLevel`。

        未命中映射时返回 ``LogLevel.UNKNOWN``，不抛异常（日志仍需保留）。
        """

        raise NotImplementedError
