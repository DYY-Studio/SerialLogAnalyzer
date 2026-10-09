"""日志流水线测试。"""

from __future__ import annotations

from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.logs import LogLevel


def test_feed_matched_adds_entry_and_increments_sequence(parser) -> None:
    pipe = LogPipeline(parser)
    up = pipe.feed("[I] [a] one", 1.0)
    assert len(up.added) == 1 and up.added[0].sequence == 0
    assert pipe.feed("[I] [a] two", 2.0).added[0].sequence == 1


def test_continuation_merges_into_previous(parser) -> None:
    pipe = LogPipeline(parser)
    pipe.feed("[E] [main] assert failed", 1.0)
    up = pipe.feed("    at app_main (main.c:57)", 2.0)
    assert up.added == ()
    assert up.updated[0].message.endswith("    at app_main (main.c:57)")
    assert up.updated[0].continuation is True
    assert len(pipe.entries()) == 1


def test_orphan_continuation_becomes_entry(parser) -> None:
    pipe = LogPipeline(parser)
    up = pipe.feed("    orphan", 1.0)
    assert len(up.added) == 1


def test_capacity_drops_oldest(parser) -> None:
    pipe = LogPipeline(parser, capacity=2)
    for i in range(3):
        up = pipe.feed(f"[I] [a] {i}", float(i))
    assert len(pipe.entries()) == 2
    assert pipe.entries()[0].sequence == 1
    assert up.dropped_sequences == (0,)


def test_recent_filters_min_level(parser) -> None:
    pipe = LogPipeline(parser)
    pipe.feed("[I] [a] i", 1.0)
    pipe.feed("[E] [a] e", 2.0)
    assert [e.level for e in pipe.recent(10, min_level=LogLevel.ERROR)] == [LogLevel.ERROR]


def test_recent_returns_latest_in_order(parser) -> None:
    pipe = LogPipeline(parser)
    for i in range(5):
        pipe.feed(f"[I] [a] {i}", float(i))
    assert [e.message for e in pipe.recent(2)] == ["3", "4"]
    assert len(pipe.recent(99)) == 5


def test_selected_with_neighbors(parser) -> None:
    pipe = LogPipeline(parser)
    for i in range(5):
        pipe.feed(f"[I] [a] {i}", float(i))
    seqs = [e.sequence for e in pipe.selected_with_neighbors([2], 1)]
    assert seqs == [1, 2, 3]


def test_clear_resets(parser) -> None:
    pipe = LogPipeline(parser)
    pipe.feed("[I] [a] x", 1.0)
    pipe.clear()
    assert pipe.entries() == []
    assert pipe.feed("[I] [a] y", 2.0).added[0].sequence == 0
