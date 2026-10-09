"""Preset 级别映射测试。"""

from __future__ import annotations

import re

from serial_log_analyzer.core.logs.preset import LogPreset, PresetLineRule
from serial_log_analyzer.core.models.logs import LogLevel


def test_level_from_token_hit_and_miss() -> None:
    rule = PresetLineRule(
        pattern=re.compile(r"\[(?P<level>\w+)\]"), level_map={"I": LogLevel.INFO}
    )
    preset = LogPreset("p", "P", rule)
    assert preset.level_from_token("I") is LogLevel.INFO
    assert preset.level_from_token("Z") is LogLevel.UNKNOWN
