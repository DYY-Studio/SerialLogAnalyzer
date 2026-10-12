"""``MarkdownRenderer`` 测试：ASCII/中文分段（决定代码字体是否会触发系统回退）。"""

from __future__ import annotations

from serial_log_analyzer.ui.markdown import split_font_runs


def test_ascii_only_text_is_one_run() -> None:
    assert split_font_runs("int a = 1;") == [(0, 10, False)]


def test_cjk_only_text_is_one_run() -> None:
    assert split_font_runs("阻塞") == [(0, 2, True)]


def test_mixed_code_comment_splits_into_three_runs() -> None:
    """`// 阻塞 100ms` 要切成 ASCII/中文/ASCII 三段，中文那段才能换字体。"""

    assert split_font_runs("// 阻塞 100ms") == [(0, 3, False), (3, 5, True), (5, 11, False)]


def test_empty_text_has_no_runs() -> None:
    assert split_font_runs("") == []
