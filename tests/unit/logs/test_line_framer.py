"""LineFramer 字节分帧测试。"""

from __future__ import annotations

from serial_log_analyzer.core.logs.line_framer import LineFramer


def test_feed_handles_split_crlf() -> None:
    f = LineFramer()
    assert f.feed(b"[I] [main] hel") == []
    assert f.feed(b"lo\r\n[I] [app] x\r\n") == ["[I] [main] hello", "[I] [app] x"]


def test_feed_strips_lone_cr_and_lf() -> None:
    assert LineFramer().feed(b"a\rb\nc\r\n") == ["a", "b", "c"]


def test_finalize_returns_residual_once() -> None:
    f = LineFramer()
    f.feed(b"tail-without-newline")
    assert f.finalize() == "tail-without-newline"
    assert f.finalize() is None


def test_max_line_bytes_forces_emit() -> None:
    f = LineFramer(max_line_bytes=4)
    assert f.feed(b"abcdefgh") == ["abcd", "efgh"]


def test_utf8_split_across_chunks() -> None:
    f = LineFramer()
    data = "[I] [tag] 中文\n".encode()
    assert f.feed(data[:5]) == []
    assert f.feed(data[5:]) == ["[I] [tag] 中文"]


def test_reset_clears_buffer() -> None:
    f = LineFramer()
    f.feed(b"partial")
    f.reset()
    assert f.finalize() is None
