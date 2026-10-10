"""通过资源接口加载并严格渲染日志分析提示词。"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.config import identifier
from serial_log_analyzer.core.ports import ResourceLoader


@dataclass(frozen=True)
class PromptGoal:
    """预设分析目标：goal_id 标识、display_name 名称、template 原文。"""

    goal_id: str
    display_name: str
    template: str


class PromptLibrary:
    """用 loader 读取 Prompt 资源，资源覆盖优先级由 loader 决定。"""

    def __init__(self, loader: ResourceLoader) -> None:
        self._loader = loader

    def goals(self) -> list[PromptGoal]:
        """列出预设目标；缺失、重复或非法模板抛出 ConfigError。"""
        goals = []
        for path in sorted(set(self._loader.list_files("prompts", "*.md"))):
            goal_id = identifier(path.rsplit("/", 1)[-1].removesuffix(".md"))
            template = self._loader.read_text(f"prompts/{goal_id}.md")
            parsed = Template(template)
            if (
                not parsed.is_valid()
                or "context" not in parsed.get_identifiers()
                or set(parsed.get_identifiers()) - {"context", "goal", "language"}
            ):
                raise ConfigError(f"提示词变量非法或缺少 context：{goal_id}")
            title = template.splitlines()[0].lstrip("# ").removeprefix("分析目标：").strip()
            goals.append(PromptGoal(goal_id, title or goal_id, template))
        return goals

    def render(self, goal_id: str, *, context: str) -> str:
        """将 context 代入目标模板；目标缺失或变量非法抛出 ConfigError。"""
        identifier(goal_id)
        for goal in self.goals():
            if goal.goal_id == goal_id:
                return Template(goal.template).substitute(
                    context=context, goal=goal.display_name, language="中文"
                )
        raise ConfigError(f"分析目标不存在：{goal_id}")

    def render_freeform(self, text: str) -> str:
        """返回自由输入文本，不将输入里的美元符号当作模板变量。"""
        return text
