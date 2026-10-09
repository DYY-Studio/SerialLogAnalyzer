"""行解析器测试。"""

from __future__ import annotations

import re

import pytest

from serial_log_analyzer.core.logs.parser import LogParser, ParseOutcome
from serial_log_analyzer.core.logs.preset import LogPreset, PresetLineRule
from serial_log_analyzer.core.models.logs import LogLevel


@pytest.mark.parametrize(
    ("line", "level", "module", "message"),
    [
        ("[I] [main] system ready", LogLevel.INFO, "main", "system ready"),
        ("[W] [wifi] retry 2/5", LogLevel.WARN, "wifi", "retry 2/5"),
        ("[E] [uart] rx overflow", LogLevel.ERROR, "uart", "rx overflow"),
    ],
)
def test_parse_matched(parser, line, level, module, message) -> None:
    result = parser.parse(line, 1, 0.0)
    assert (result.outcome, result.entry.level, result.entry.module, result.entry.message) == (
        ParseOutcome.MATCHED,
        level,
        module,
        message,
    )
    assert result.entry.raw == line


def test_module_dash_becomes_none(parser) -> None:
    assert parser.parse("[I] [-] boot", 1, 0.0).entry.module is None


def test_unmatched_boot_line_falls_back(parser) -> None:
    result = parser.parse("wifi init success!", 1, 0.0)
    assert (
        result.outcome,
        result.entry.level,
        result.entry.module,
        result.entry.message,
    ) == (ParseOutcome.FALLBACK, LogLevel.UNKNOWN, None, "wifi init success!")


def test_continuation_indented_line(parser) -> None:
    result = parser.parse("    at app_main (main.c:57)", 1, 0.0)
    assert result.outcome == ParseOutcome.CONTINUATION
    assert result.continuation_text == "    at app_main (main.c:57)"


def test_blank_line_ignored(parser) -> None:
    assert parser.parse("", 1, 0.0).outcome == ParseOutcome.IGNORED


def test_unmapped_level_is_unknown(parser) -> None:
    assert parser.parse("[Z] [t] x", 1, 0.0).entry.level is LogLevel.UNKNOWN


def test_render_for_llm(parser) -> None:
    entry = parser.parse("[I] [main] hi", 1, 0.0).entry
    assert parser.render_for_llm(entry) == "[INFO] [main] hi"


def test_fields_extracted_into_extra(parser) -> None:
    line = (
        "[I] [sensor] led=1 fan=0 temperature=29.7 humidity=43.6 "
        "light=122 proximity=62 infrared=8"
    )
    entry = parser.parse(line, 1, 0.0).entry
    assert entry.extra == {
        "led": "1",
        "fan": "0",
        "temperature": "29.7",
        "humidity": "43.6",
        "light": "122",
        "proximity": "62",
        "infrared": "8",
    }


def test_fields_absent_when_message_has_none(parser) -> None:
    assert parser.parse("[I] [main] system ready", 1, 0.0).entry.extra == {}


def test_field_with_unmatched_optional_group_is_omitted() -> None:
    rule = PresetLineRule(
        pattern=re.compile(r"^\[(?P<level>\w+)\] (?P<message>.*)$"),
        level_map={"I": LogLevel.INFO},
        fields={"opt": re.compile(r"foo(?:=(?P<value>\w+))?")},
    )
    parser = LogParser(LogPreset("p", "P", rule))
    assert parser.parse("[I] foo", 1, 0.0).entry.extra == {}
