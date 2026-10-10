"""Prompt 模板加载：把 ``prompts/*.md`` 渲染为最终用户消息。

模板使用 :class:`string.Template` 语法（``$context`` / ``$goal`` / ``$language``），
避免引入模板引擎依赖；缺失变量会抛出 :class:`ConfigError` 而不是静默留空。
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["PromptGoal", "PromptLibrary"]

_PROMPT_DIR = "prompts"
_PATTERN = "*.md"
_LANGUAGE = "中文"
_TITLE_PREFIX = "# "
_GOAL_PREFIXES = ("分析目标：", "分析目标:")


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
        self._loader = loader
        self._cache: list[PromptGoal] | None = None

    def goals(self) -> list[PromptGoal]:
        """返回全部可用分析目标（用户目录覆盖同名内置目标）。

        返回:
            按 ``goal_id`` 升序排列的目标列表；单个模板读取失败会被跳过，
            不影响其余目标可用。
        """

        if self._cache is not None:
            return list(self._cache)

        seen: dict[str, PromptGoal] = {}
        for path in self._loader.list_files(_PROMPT_DIR, _PATTERN):
            goal_id = path.rsplit("/", 1)[-1][: -len(".md")]
            if not goal_id or goal_id in seen:
                continue
            try:
                template = self._loader.read_text(path)
            except ConfigError:
                continue
            seen[goal_id] = PromptGoal(
                goal_id=goal_id,
                display_name=_display_name(template, goal_id),
                template=template,
            )

        self._cache = [seen[key] for key in sorted(seen)]
        return list(self._cache)

    def find(self, goal_id: str) -> PromptGoal | None:
        """按标识查找目标；不存在返回 ``None``。"""

        return next((goal for goal in self.goals() if goal.goal_id == goal_id), None)

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

        goal = self.find(goal_id)
        if goal is None:
            available = "、".join(item.goal_id for item in self.goals()) or "（无）"
            raise ConfigError(f"未找到分析目标：{goal_id}；可用目标：{available}")

        values = {"context": context, "goal": goal.display_name, "language": _LANGUAGE}
        try:
            return Template(goal.template).substitute(values)
        except KeyError as exc:
            raise ConfigError(f"Prompt 模板缺少变量：${exc.args[0]}（{goal_id}）") from exc
        except ValueError as exc:
            raise ConfigError(f"Prompt 模板语法非法：{goal_id}（{exc}）") from exc

    def render_freeform(self, text: str) -> str:
        """把自由输入直接作为用户消息（不套模板）。

        异常:
            ConfigError: 输入为空。
        """

        stripped = text.strip()
        if not stripped:
            raise ConfigError("分析内容不能为空")
        return stripped


def _display_name(template: str, fallback: str) -> str:
    """从模板首个 Markdown 标题推导展示名，推导失败时退回 ``goal_id``。"""

    for line in template.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_TITLE_PREFIX):
            title = stripped[len(_TITLE_PREFIX) :].strip()
            for prefix in _GOAL_PREFIXES:
                if title.startswith(prefix):
                    title = title[len(prefix) :].strip()
                    break
            if title:
                return title
        break
    return fallback
