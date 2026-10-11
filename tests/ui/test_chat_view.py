"""``ChatView`` 转录渲染测试（离屏）：多轮、流式、失败与折叠默认值。"""

from __future__ import annotations

from serial_log_analyzer.core.models.analysis import (
    AnalysisMessage,
    AnalysisResult,
    AnalysisState,
    MessageRole,
)
from serial_log_analyzer.ui.widgets.chat_view import ChatView

_USER = AnalysisMessage(MessageRole.USER, "目标：定位错误\n\n<日志上下文>", "定位错误 · 看看这条")


def _result(state: AnalysisState, messages: list[AnalysisMessage], **kwargs) -> AnalysisResult:
    return AnalysisResult(state=state, conversation=list(messages), **kwargs)


def test_render_shows_summary_context_thinking_and_answer(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)

    view.render(
        _result(AnalysisState.STREAMING, [_USER], content="结论", reasoning="先看 uart")
    )

    assert view.plain_text() == (
        "【你】\n【参考内容】目标：定位错误\n\n<日志上下文>\n定位错误 · 看看这条\n\n"
        "【LLM】\n【思考】先看 uart\n结论"
    )
    # 默认折叠：思考块收起，但仍可展开
    assert view._cards[1].detail.is_expanded() is False
    assert view._cards[1].detail.text() == "先看 uart"


def test_finalizing_reuses_the_streaming_card(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)

    view.render(_result(AnalysisState.STREAMING, [_USER], content="结", reasoning="想"))
    view.render(_result(AnalysisState.STREAMING, [_USER], content="结论完整", reasoning="想好了"))
    assert len(view._cards) == 2

    finished = _result(
        AnalysisState.DONE,
        [_USER, AnalysisMessage(MessageRole.ASSISTANT, "结论完整")],
        content="结论完整",
    )
    view.render(finished)
    view.render(finished)

    assert len(view._cards) == 2
    assert view._cards[1].body_text() == "结论完整"
    assert view._cards[1].detail.text() == "想好了"  # 思考在定稿后仍留在卡片上


def test_failed_turn_keeps_partial_output_before_next_turn(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)

    view.render(_result(AnalysisState.STREAMING, [_USER], content="半截"))
    view.render(_result(AnalysisState.ERROR, [_USER], content="半截", error="网络失败"))
    assert [card.body_text() for card in view._cards] == ["定位错误 · 看看这条", "半截"]

    second = AnalysisMessage(MessageRole.USER, "第二轮", "第二轮")
    view.render(_result(AnalysisState.STREAMING, [_USER, second], content="新的一轮"))

    assert [card.body_text() for card in view._cards] == [
        "定位错误 · 看看这条",
        "半截",
        "第二轮",
        "新的一轮",
    ]
    # 追问轮的正文与摘要相同，不再多一个「参考内容」块
    assert view._cards[2].detail.text() == ""


def test_details_expanded_setting_applies_to_existing_and_new_cards(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)
    view.render(_result(AnalysisState.STREAMING, [_USER], content="结", reasoning="想"))
    assert view._cards[0].detail.is_expanded() is False

    view.set_details_expanded(True)

    assert view._cards[0].detail.is_expanded() is True
    view.render(
        _result(
            AnalysisState.DONE,
            [_USER, AnalysisMessage(MessageRole.ASSISTANT, "结论")],
            content="结论",
        )
    )
    view.render(
        _result(
            AnalysisState.STREAMING,
            [
                _USER,
                AnalysisMessage(MessageRole.ASSISTANT, "结论"),
                AnalysisMessage(MessageRole.USER, "p2", "第二轮"),
            ],
            content="新一轮结论",
            reasoning="再想",
        )
    )

    live = view._cards[-1]
    assert live.body_text() == "新一轮结论"
    assert live.detail.is_expanded() is True


def test_detail_blocks_hide_when_there_is_nothing_to_show(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)
    view.render(_result(AnalysisState.STREAMING, [_USER], content="结论"))

    assistant_card = view._cards[-1]
    assert assistant_card.detail.text() == ""
    assert assistant_card.detail.isVisibleTo(view) is False  # 没有思考就不出现「思考」表头

    view.render(_result(AnalysisState.STREAMING, [_USER], content="结论", reasoning="想一想"))
    assert assistant_card.detail.isVisibleTo(view) is True


def test_clear_empties_the_transcript(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)
    view.render(_result(AnalysisState.STREAMING, [_USER], content="结论"))

    view.clear()

    assert view._cards == []
    assert view.plain_text() == ""


def test_export_uses_markdown_source_not_rendered_html(qtbot) -> None:
    """「复制结果」要给出 Markdown 原文，不能把渲染后的 HTML 抄出去。"""

    view = ChatView()
    qtbot.addWidget(view)
    answer = "**结论**\n\n```c\nint a;\n```"
    view.render(
        _result(
            AnalysisState.DONE,
            [_USER, AnalysisMessage(MessageRole.ASSISTANT, answer)],
            content=answer,
        )
    )

    assert view.plain_text().endswith(answer)  # 原文原样导出
    assert view._cards[-1].body.text() != answer  # 界面上显示的是渲染后的富文本


def _show(view: ChatView, qtbot) -> None:
    """让结果区真的排过版：滚动条范围要有非零值，滚动行为才测得出。"""

    view.resize(320, 200)
    view.show()
    qtbot.waitExposed(view)


def _lines(count: int) -> str:
    return "内容行\n" * count


def _settle(qtbot) -> None:
    """等布局重算完：滚动条范围要等后续事件循环（走了重排/加滚动条两步）才更新。"""

    for _ in range(3):
        qtbot.wait(10)


def test_streaming_keeps_scrolling_to_bottom(qtbot) -> None:
    """流式追加内容时必须一直贴底（旧实现每次都用重算前的上限，等于停在原地）。"""

    view = ChatView()
    qtbot.addWidget(view)
    _show(view, qtbot)
    bar = view.verticalScrollBar()

    view.render(_result(AnalysisState.STREAMING, [_USER], content=_lines(1)))
    _settle(qtbot)

    for count in (5, 20, 40, 80):
        view.render(_result(AnalysisState.STREAMING, [_USER], content=_lines(count)))
        _settle(qtbot)
        assert bar.maximum() > 0
        assert bar.value() == bar.maximum()


def test_user_scroll_up_stops_following_until_back_at_bottom(qtbot) -> None:
    """用户往上滚后不再被拽回底部；滚回底部或开新一轮时恢复跟随。"""

    view = ChatView()
    qtbot.addWidget(view)
    _show(view, qtbot)
    bar = view.verticalScrollBar()

    view.render(_result(AnalysisState.STREAMING, [_USER], content=_lines(40)))
    _settle(qtbot)
    assert bar.maximum() > 0

    bar.setValue(0)
    view.render(_result(AnalysisState.STREAMING, [_USER], content=_lines(60)))
    _settle(qtbot)
    assert bar.value() == 0

    bar.setValue(bar.maximum())
    view.render(_result(AnalysisState.STREAMING, [_USER], content=_lines(80)))
    _settle(qtbot)
    assert bar.value() == bar.maximum()

    bar.setValue(0)
    second = AnalysisMessage(MessageRole.USER, "第二轮", "第二轮")
    view.render(_result(AnalysisState.STREAMING, [_USER, second], content=_lines(30)))
    _settle(qtbot)
    assert bar.value() == bar.maximum()

