"""遥测时序缓冲纯单元测试（无 Qt / pyqtgraph / numpy 依赖）。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.logs.telemetry import (
    TelemetryBuffer,
    TelemetrySample,
    extract_numeric_extra,
    parse_finite_float,
)
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel


def _entry(
    sequence: int,
    received_at: float,
    extra: dict[str, str] | None = None,
) -> LogEntry:
    return LogEntry(
        sequence=sequence,
        received_at=received_at,
        level=LogLevel.INFO,
        message="telemetry",
        raw=f"[I] [sensor] seq={sequence}",
        module="sensor",
        extra=extra or {},
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("29.7", 29.7),
        (" -12 ", -12.0),
        ("0", 0.0),
        ("1e-3", 1e-3),
        ("", None),
        ("   ", None),
        ("true", None),
        ("false", None),
        ("nan", None),
        ("NaN", None),
        ("inf", None),
        ("-inf", None),
        ("Infinity", None),
        ("abc", None),
    ],
)
def test_parse_finite_float_and_extract_numeric_extra(raw: str, expected: float | None) -> None:
    assert parse_finite_float(raw) == expected
    assert parse_finite_float(True) is None  # type: ignore[arg-type]

    extracted = extract_numeric_extra(
        {"temperature": "26.5", "status": "ok", "bad": "nan", "led": "1"}
    )
    assert extracted == {"temperature": 26.5, "led": 1.0}


def test_telemetry_buffer_orders_fields_anchors_time_and_skips_non_numeric() -> None:
    buf = TelemetryBuffer(preset_fields=("temperature", "humidity", "temperature"))
    assert buf.field_names() == ("temperature", "humidity")

    # 首条无数值字段不得提前锚定 t=0.0
    assert buf.apply_update(PipelineUpdate(added=(_entry(0, 100.0, {"state": "boot"}),))) is False
    assert buf.field_names() == ("temperature", "humidity")

    # 首条有效数值日志锚定 t=0.0，运行期新字段 voltage 按顺序追加到 Preset 字段之后
    assert (
        buf.apply_update(
            PipelineUpdate(
                added=(
                    _entry(1, 105.0, {"temperature": "25.0", "voltage": "3.3"}),
                    _entry(2, 107.5, {"temperature": "26.5", "humidity": "44.0", "note": "nan"}),
                )
            )
        )
        is True
    )
    assert buf.field_names() == ("temperature", "humidity", "voltage")
    assert buf.samples("temperature") == (
        TelemetrySample(sequence=1, time_s=0.0, value=25.0),
        TelemetrySample(sequence=2, time_s=2.5, value=26.5),
    )
    assert buf.samples("humidity") == (TelemetrySample(sequence=2, time_s=2.5, value=44.0),)
    assert buf.samples("voltage") == (TelemetrySample(sequence=1, time_s=0.0, value=3.3),)
    assert buf.samples("unknown") == ()


def test_telemetry_buffer_handles_dropped_sequences_and_max_points() -> None:
    buf = TelemetryBuffer(max_points=3)
    buf.apply_update(
        PipelineUpdate(
            added=tuple(_entry(seq, 10.0 + seq, {"temp": str(20 + seq)}) for seq in range(5))
        )
    )
    assert [s.sequence for s in buf.samples("temp")] == [2, 3, 4]

    # 连续头部淘汰 + 任意非头部序号集合均能准确剔除
    assert buf.apply_update(PipelineUpdate(dropped_sequences=(2, 4))) is True
    assert [s.sequence for s in buf.samples("temp")] == [3]

    # 剔除不存在的序号应返回 False
    assert buf.apply_update(PipelineUpdate(dropped_sequences=(999,))) is False


def test_telemetry_buffer_clear_samples_and_reset_preset() -> None:
    buf = TelemetryBuffer(preset_fields=("temperature",))
    buf.apply_update(PipelineUpdate(added=(_entry(0, 50.0, {"temperature": "22.0", "rssi": "-40"}),)))
    assert buf.field_names() == ("temperature", "rssi")

    buf.clear_samples()
    assert buf.samples("temperature") == ()
    assert buf.samples("rssi") == ()
    assert buf.field_names() == ("temperature", "rssi")

    # 清空后下一条有效数值日志重新锚定 t=0.0
    buf.apply_update(PipelineUpdate(added=(_entry(1, 200.0, {"temperature": "23.0"}),)))
    assert buf.samples("temperature") == (TelemetrySample(sequence=1, time_s=0.0, value=23.0),)

    # reset 可清理运行期字段并切换到新 Preset 字段集合
    buf.reset(preset_fields=("voltage", "current"))
    assert buf.field_names() == ("voltage", "current")
    assert buf.samples("temperature") == ()
    assert buf.samples("rssi") == ()


def test_telemetry_buffer_rejects_invalid_max_points() -> None:
    with pytest.raises(ConfigError):
        TelemetryBuffer(max_points=0)
    with pytest.raises(ConfigError):
        TelemetryBuffer(max_points=True)  # type: ignore[arg-type]
