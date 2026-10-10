"""Prompt 模板加载：把 ``prompts/*.md`` 渲染为最终用户消息。

模板使用 :class:`string.Template` 语法（``$context`` / ``$goal`` / ``$language``），
避免引入模板引擎依赖；缺失变量会抛出 :class:`ConfigError` 而不是静默留空。
"""

from __future__ import annotations

from dataclasses import dataclass

from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["PromptGoal", "PromptLibrary"]

_PROMPT_DIR = "prompts"


@dataclass(frozen=True)
class PromptGoal:
    """一个预设分析目标。

    参数:
        goal_id: 唯一标识（文件名去掉扩展名）。
        display_name: 界面展示名。
        template: 模板原文。
    """

    goal_id: str
    display_name: str
    template: str


class PromptLibrary:
    """加载并渲染内置 / 用户 Prompt 模板。

    参数:
        loader: 资源加载器。
    """

    def __init__(self, loader: ResourceLoader) -> None:
        raise NotImplementedError

    def goals(self) -> list[PromptGoal]:
        """返回全部可用分析目标（用户目录覆盖同名内置目标）。"""

        raise NotImplementedError

    def render(self, goal_id: str, *, context: str) -> str:
        """渲染指定目标的模板。

        参数:
            goal_id: 目标标识。
            context: 已渲染的日志上下文文本。

        返回:
            最终用户消息文本。

        异常:
            ConfigError: 目标不存在或模板缺少必需变量。
        """

        raise NotImplementedError

    def render_freeform(self, text: str) -> str:
        """把自由输入直接作为用户消息（不套模板）。"""

        raise NotImplementedError
