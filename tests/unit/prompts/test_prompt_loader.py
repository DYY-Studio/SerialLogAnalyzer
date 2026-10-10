"""``core/prompts/loader.py`` 的 Prompt 模板加载与渲染测试。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.prompts.loader import PromptLibrary


class ExplodingLoader:
    """``list_files`` 列出了模板但读取必定失败的加载器。"""

    def read_text(self, relative_path: str) -> str:
        raise ConfigError(relative_path)

    def list_files(self, relative_dir: str, pattern: str) -> list[str]:
        return ["prompts/broken.md"]


def test_goals_are_sorted_and_use_title_as_display_name(make_loader):
    library = PromptLibrary(
        make_loader(
            {
                "prompts/zzz.md": "# 分析目标：定位错误\n\n$context\n",
                "prompts/aaa.md": "# 分析目标：解释日志含义\n\n$context\n",
                "prompts/readme.txt": "忽略",
            }
        )
    )

    goals = library.goals()

    assert [goal.goal_id for goal in goals] == ["aaa", "zzz"]
    assert goals[0].display_name == "解释日志含义"
    assert goals[1].display_name == "定位错误"


def test_goal_without_title_falls_back_to_id(make_loader):
    library = PromptLibrary(make_loader({"prompts/plain.md": "请分析：$context\n"}))

    goal = library.find("plain")

    assert goal is not None
    assert goal.display_name == "plain"


def test_unreadable_template_is_skipped(make_loader):
    library = PromptLibrary(ExplodingLoader())

    assert library.goals() == []


def test_render_substitutes_context_goal_and_language(make_loader):
    library = PromptLibrary(
        make_loader(
            {
                "prompts/explain.md": (
                    "# 分析目标：解释日志含义\n\n目标：$goal\n语言：$language\n日志：\n$context\n"
                )
            }
        )
    )

    text = library.render("explain", context="[INFO] boot")

    assert "目标：解释日志含义" in text
    assert "语言：中文" in text
    assert "[INFO] boot" in text
    assert "$" not in text


def test_render_unknown_goal_lists_available_ids(make_loader):
    library = PromptLibrary(make_loader({"prompts/explain.md": "$context\n"}))

    with pytest.raises(ConfigError) as excinfo:
        library.render("absent", context="x")

    assert "explain" in str(excinfo.value)


def test_render_rejects_unknown_variable(make_loader):
    library = PromptLibrary(make_loader({"prompts/bad.md": "$context $mystery\n"}))

    with pytest.raises(ConfigError) as excinfo:
        library.render("bad", context="x")

    assert "mystery" in str(excinfo.value)


def test_render_rejects_invalid_template_syntax(make_loader):
    library = PromptLibrary(make_loader({"prompts/bad.md": "$context $ 1\n"}))

    with pytest.raises(ConfigError):
        library.render("bad", context="x")


def test_render_freeform_strips_input(make_loader):
    library = PromptLibrary(make_loader({}))

    assert library.render_freeform("  帮我看看  \n") == "帮我看看"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_render_freeform_rejects_blank_input(make_loader, text):
    library = PromptLibrary(make_loader({}))

    with pytest.raises(ConfigError):
        library.render_freeform(text)


def test_goals_are_cached_between_calls(make_loader):
    counting = make_loader({"prompts/a.md": "$context\n"})
    library = PromptLibrary(counting)

    first = library.goals()
    first.clear()
    second = library.goals()

    assert [goal.goal_id for goal in second] == ["a"]
