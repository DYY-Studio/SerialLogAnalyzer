"""异常筛选、窗口聚合、冷却告警与淘汰测试（不启动 Qt）。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from serial_log_analyzer.core.anomalies.rule_loader import load_rule_set
from serial_log_analyzer.core.device import command as device_command
from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.logs.line_framer import LineFramer
from serial_log_analyzer.core.logs.parser import LogParser
from serial_log_analyzer.core.logs.pipeline import LogPipeline, PipelineUpdate
from serial_log_analyzer.core.logs.preset_loader import load_preset
from serial_log_analyzer.core.models.anomaly import (
    AnomalyRule,
    AnomalySeverity,
    ClusterStatus,
    FieldThreshold,
    ThresholdOp,
)
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel
from serial_log_analyzer.core.services.anomaly import AnomalyService, normalize_message

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _entry(
    seq: int,
    t: float,
    level: LogLevel,
    message: str,
    *,
    module: str | None = "app",
    extra: dict[str, str] | None = None,
) -> LogEntry:
    return LogEntry(
        sequence=seq,
        received_at=t,
        level=level,
        message=message,
        raw=f"[{level.name}] [{module or '-'}] {message}",
        module=module,
        extra=dict(extra) if extra is not None else {},
    )


def test_rule_matching_respects_level_module_enabled_and_unknown_guard() -> None:
    rules = [
        AnomalyRule(
            rule_id="disabled-rule",
            category="已禁用",
            severity=AnomalySeverity.CRITICAL,
            keywords=("malloc",),
            enabled=False,
        ),
        AnomalyRule(
            rule_id="mem-rule",
            category="内存分配失败",
            severity=AnomalySeverity.CRITICAL,
            keywords=("malloc failed",),
            modules=("memory",),
            min_level=LogLevel.WARN,
            immediate_alert=True,
        ),
        AnomalyRule(
            rule_id="uart-regex",
            category="通信异常",
            severity=AnomalySeverity.HIGH,
            pattern=re.compile(r"rx\s+overflow", re.IGNORECASE),
            min_level=LogLevel.ERROR,
        ),
    ]
    service = AnomalyService(rules)

    # UNKNOWN 不可误判为 >= WARN/ERROR；模块不匹配与禁用规则均忽略。
    update = service.apply_update(
        PipelineUpdate(
            added=(
                _entry(0, 1.0, LogLevel.UNKNOWN, "malloc failed raw line", module=None),
                _entry(1, 2.0, LogLevel.ERROR, "malloc failed wrong mod", module="other"),
                _entry(2, 3.0, LogLevel.WARN, "rx overflow warn only", module="uart"),
                _entry(3, 4.0, LogLevel.ERROR, "MALLOC FAILED size=128", module="memory"),
                _entry(4, 5.0, LogLevel.ERROR, "UART RX overflow", module="uart"),
            )
        )
    )

    assert [(c.rule_id, c.occurrence_count) for c in update.clusters] == [
        ("uart-regex", 1),
        ("mem-rule", 1),
    ]
    assert [a.rule_id for a in update.new_alerts] == ["mem-rule", "uart-regex"]


def test_normalization_and_window_clustering() -> None:
    assert (
        normalize_message("i2c read failed addr=0x38 errno=-5\n    at drv.c:12")
        == "i2c read failed addr=<HEX> errno=<NUM>"
    )
    assert len(normalize_message("x=" + ("A" * 300))) == 163

    rule = AnomalyRule(
        rule_id="uart-overflow",
        category="通信异常",
        severity=AnomalySeverity.HIGH,
        keywords=("rx overflow",),
        min_level=LogLevel.ERROR,
        min_occurrences=3,
        window_seconds=60.0,
        cooldown_seconds=60.0,
    )
    service = AnomalyService([rule])

    # 同窗口内动态数字变化应归并为同一簇，并在第 3 次触发 1 条告警。
    u1 = service.apply_update(
        PipelineUpdate(added=(_entry(0, 10.0, LogLevel.ERROR, "rx overflow dropped=16", module="uart"),))
    )
    u2 = service.apply_update(
        PipelineUpdate(added=(_entry(1, 20.0, LogLevel.ERROR, "rx overflow dropped=24", module="uart"),))
    )
    u3 = service.apply_update(
        PipelineUpdate(added=(_entry(2, 30.0, LogLevel.ERROR, "rx overflow dropped=32", module="uart"),))
    )
    assert u1.new_alerts == () and u2.new_alerts == ()
    assert len(u3.new_alerts) == 1
    assert len(u3.clusters) == 1
    assert u3.clusters[0].occurrence_count == 3
    assert u3.clusters[0].evidence_sequences == (0, 1, 2)

    # 超过 window_seconds 的命中切分为新簇。
    u4 = service.apply_update(
        PipelineUpdate(added=(_entry(3, 100.0, LogLevel.ERROR, "rx overflow dropped=40", module="uart"),))
    )
    assert len(u4.clusters) == 2
    assert u4.new_alerts == ()


def test_sliding_window_prevents_stale_threshold_trigger() -> None:
    rule = AnomalyRule(
        rule_id="retry",
        category="通信异常",
        severity=AnomalySeverity.MEDIUM,
        keywords=("retry",),
        min_level=LogLevel.WARN,
        min_occurrences=3,
        window_seconds=60.0,
        cooldown_seconds=60.0,
    )
    service = AnomalyService([rule])

    # 每次间隔 50s：都在同一连续活跃簇内，但任意 60s 滑动窗口内最多只有 2 次命中，不应误告警。
    assert service.apply_update(PipelineUpdate(added=(_entry(0, 0.0, LogLevel.WARN, "retry 1"),))).new_alerts == ()
    assert service.apply_update(PipelineUpdate(added=(_entry(1, 50.0, LogLevel.WARN, "retry 2"),))).new_alerts == ()
    res = service.apply_update(PipelineUpdate(added=(_entry(2, 100.0, LogLevel.WARN, "retry 3"),)))
    assert res.new_alerts == ()
    assert len(res.clusters) == 1 and res.clusters[0].occurrence_count == 3

    # 第 4 次在 120s 到达：窗口 [60, 120] 仍仅 2 次（100, 120），第 5 次在 140s 到达 -> [80, 140] 达 3 次，触发告警。
    assert service.apply_update(PipelineUpdate(added=(_entry(3, 120.0, LogLevel.WARN, "retry 4"),))).new_alerts == ()
    fired = service.apply_update(PipelineUpdate(added=(_entry(4, 140.0, LogLevel.WARN, "retry 5"),)))
    assert len(fired.new_alerts) == 1


def test_continuation_updates_are_idempotent(parser) -> None:
    rule = AnomalyRule(
        rule_id="mem",
        category="内存分配失败",
        severity=AnomalySeverity.CRITICAL,
        keywords=("malloc failed",),
        min_level=LogLevel.ERROR,
        immediate_alert=True,
    )
    pipeline = LogPipeline(parser)
    service = AnomalyService([rule])

    # 首行已命中 -> 后续 LOG_CONT update 不重复计数。
    u1 = service.apply_update(pipeline.feed("[E] [memory] malloc failed size=4096", 1.0))
    u2 = service.apply_update(pipeline.feed("    at pvPortMalloc (heap.c:184)", 1.1))
    assert u1.clusters[0].occurrence_count == 1
    assert u2.clusters[0].occurrence_count == 1
    assert len(u1.new_alerts) == 1 and u2.new_alerts == ()

    # 首行未命中、续行出现关键词 -> 在 update 时捕获且仅计 1 次。
    u3 = service.apply_update(pipeline.feed("[E] [demo] panic trace", 2.0))
    u4 = service.apply_update(pipeline.feed("    cause: malloc failed in isr", 2.1))
    u5 = service.apply_update(pipeline.feed("    at extra_frame (x.c:1)", 2.2))
    assert len(u3.clusters) == 1
    assert len(u4.clusters) == 2
    assert u5.clusters[0].occurrence_count == 1


def test_cooldown_and_cluster_status_transitions() -> None:
    rule = AnomalyRule(
        rule_id="mem",
        category="内存分配失败",
        severity=AnomalySeverity.CRITICAL,
        keywords=("malloc failed",),
        min_level=LogLevel.ERROR,
        immediate_alert=True,
        cooldown_seconds=60.0,
    )
    service = AnomalyService([rule])

    a1 = service.apply_update(PipelineUpdate(added=(_entry(0, 10.0, LogLevel.ERROR, "malloc failed"),)))
    cid = a1.clusters[0].cluster_id
    assert len(a1.new_alerts) == 1

    # 冷却期内抑制弹窗但继续计数。
    a2 = service.apply_update(PipelineUpdate(added=(_entry(1, 30.0, LogLevel.ERROR, "malloc failed"),)))
    assert a2.new_alerts == () and a2.clusters[0].occurrence_count == 2

    # 过冷却期重新触发。
    a3 = service.apply_update(PipelineUpdate(added=(_entry(2, 71.0, LogLevel.ERROR, "malloc failed"),)))
    assert len(a3.new_alerts) == 1

    # 已确认后在同一窗口内抑制新告警，但仍累计次数。
    ack = service.set_cluster_status(cid, ClusterStatus.ACKNOWLEDGED)
    assert ack.status is ClusterStatus.ACKNOWLEDGED
    a4 = service.apply_update(PipelineUpdate(added=(_entry(3, 80.0, LogLevel.ERROR, "malloc failed"),)))
    assert a4.new_alerts == ()
    assert len(a4.clusters) == 1 and a4.clusters[0].occurrence_count == 4

    # 已解决后即便仍在原窗口内，再次命中也应新建活动簇并恢复告警。
    service.set_cluster_status(cid, ClusterStatus.RESOLVED)
    a5 = service.apply_update(PipelineUpdate(added=(_entry(4, 90.0, LogLevel.ERROR, "malloc failed"),)))
    assert len(a5.clusters) == 2
    assert len(a5.new_alerts) == 1
    assert a5.new_alerts[0].cluster_id != cid

    with pytest.raises(ConfigError):
        service.set_cluster_status("C-9999", ClusterStatus.RESOLVED)


def test_hi3861_anomalies_fixture_recall_with_default_rules(make_loader, parser) -> None:
    yaml_text = (_REPO_ROOT / "rules" / "anomalies" / "default.yaml").read_text(encoding="utf-8")
    rule_set = load_rule_set(make_loader({"rules/anomalies/default.yaml": yaml_text}), "default")

    raw = (_REPO_ROOT / "tests" / "fixtures" / "serial" / "hi3861-anomalies.txt").read_bytes()
    framer = LineFramer()
    pipeline = LogPipeline(parser)
    service = AnomalyService(rule_set)

    timestamp = 1.0
    triggered = []
    for line in framer.feed(raw):
        if device_command.is_response_line(line):
            continue
        timestamp += 0.01
        res = service.apply_update(pipeline.feed(line, timestamp))
        triggered.extend(res.new_alerts)

    clusters = service.clusters()
    categories = {c.category for c in clusters}
    assert categories == {"内存分配失败", "任务/调度超时", "驱动/外设错误", "通信异常"}
    assert not any(c.rule_id == "unclassified-error" for c in clusters)
    # B-01 边界/正常采样零误报
    assert not any("RAW_BSP_MSG" in c.normalized_message for c in clusters)
    assert not any("overlong_payload" in c.normalized_message for c in clusters)

    uart = next(c for c in clusters if c.rule_id == "uart-rx-overflow")
    assert uart.occurrence_count == 4
    # R-01 第 3 次触发 1 次，X-01 第 4 次处于 60s 冷却期内不重复触发
    assert sum(1 for a in triggered if a.rule_id == "uart-rx-overflow") == 1
    assert any(a.rule_id == "memory-alloc-failed" for a in triggered)
    assert any(a.rule_id == "watchdog-or-task-timeout" for a in triggered)


def test_long_run_eviction_and_pipeline_capacity_sync(parser) -> None:
    rule = AnomalyRule(
        rule_id="err",
        category="通信异常",
        severity=AnomalySeverity.HIGH,
        keywords=("fail",),
        min_level=LogLevel.ERROR,
    )
    pipeline = LogPipeline(parser, capacity=500)
    service = AnomalyService([rule], max_evidence=6, max_clusters=40, max_tracked_sequences=500)

    # 快进注入 12,000 条（跨不同模板与同一模板交替），验证集群上限、证据上限与流水线同步淘汰。
    for index in range(12_000):
        bucket = index % 60
        line = f"[E] [net] fail_code_{chr(65 + (bucket % 26))}_{bucket // 26} seq={index}"
        service.apply_update(pipeline.feed(line, float(index) * 0.1))

    clusters = service.clusters()
    assert len(clusters) <= 40
    live_sequences = {entry.sequence for entry in pipeline.entries()}
    assert len(live_sequences) == 500
    assert len(service._matched_sequences) <= 500
    for cluster in clusters:
        assert len(cluster.evidence_sequences) <= 6
        assert set(cluster.evidence_sequences).issubset(live_sequences)

    service.reset()
    assert service.clusters() == []


@pytest.mark.parametrize(
    ("op", "threshold", "matching_raw", "non_matching_raw"),
    [
        (ThresholdOp.GT, 80.0, "80.01", "80.0"),
        (ThresholdOp.GTE, 80.0, "80.0", "79.99"),
        (ThresholdOp.LT, -10.0, "-10.5", "-10.0"),
        (ThresholdOp.LTE, -10.0, "-10.0", "-9.99"),
        (ThresholdOp.EQ, 0.3, "0.30000000000000004", "0.3001"),
        (ThresholdOp.NE, 0.3, "0.31", "0.30000000000000004"),
    ],
)
def test_threshold_operators_and_float_tolerance(
    op: ThresholdOp,
    threshold: float,
    matching_raw: str,
    non_matching_raw: str,
) -> None:
    rule = AnomalyRule(
        rule_id=f"op-{op.value}",
        category="阈值告警",
        severity=AnomalySeverity.HIGH,
        min_level=LogLevel.INFO,
        thresholds=(FieldThreshold("val", op, threshold),),
    )
    service = AnomalyService([rule])

    res = service.apply_update(
        PipelineUpdate(
            added=(
                _entry(0, 1.0, LogLevel.INFO, "sample a", extra={"val": non_matching_raw}),
                _entry(1, 2.0, LogLevel.INFO, "sample b", extra={"val": matching_raw}),
            )
        )
    )

    assert len(res.clusters) == 1
    assert res.clusters[0].evidence_sequences == (1,)


def test_threshold_skips_missing_non_numeric_and_non_finite_extra() -> None:
    rule = AnomalyRule(
        rule_id="temp-check",
        category="传感器过温",
        severity=AnomalySeverity.HIGH,
        min_level=LogLevel.INFO,
        thresholds=(FieldThreshold("temp", ThresholdOp.NE, 0.0),),
    )
    service = AnomalyService([rule])

    entries = (
        _entry(0, 1.0, LogLevel.INFO, "missing", extra={}),
        _entry(1, 2.0, LogLevel.INFO, "blank", extra={"temp": "   "}),
        _entry(2, 3.0, LogLevel.INFO, "text", extra={"temp": "N/A"}),
        _entry(3, 4.0, LogLevel.INFO, "nan", extra={"temp": "nan"}),
        _entry(4, 5.0, LogLevel.INFO, "inf", extra={"temp": "inf"}),
        _entry(5, 6.0, LogLevel.INFO, "ninf", extra={"temp": "-inf"}),
        LogEntry(
            sequence=6,
            received_at=7.0,
            level=LogLevel.INFO,
            message="bool value",
            raw="[I] [app] bool value",
            module="app",
            extra={"temp": True},  # type: ignore[dict-item]
        ),
        _entry(7, 8.0, LogLevel.INFO, "valid", extra={"temp": " 85.5 "}),
    )
    res = service.apply_update(PipelineUpdate(added=entries))

    assert len(res.clusters) == 1
    assert res.clusters[0].evidence_sequences == (7,)


def test_threshold_and_logic_and_text_combination() -> None:
    rules = [
        # 防御性边界：无任何条件的规则不得误匹配全部日志
        AnomalyRule(
            rule_id="empty-rule",
            category="空规则",
            severity=AnomalySeverity.LOW,
            min_level=LogLevel.VERBOSE,
        ),
        AnomalyRule(
            rule_id="text-and-range",
            category="传感器复合告警",
            severity=AnomalySeverity.CRITICAL,
            keywords=("overheat",),
            modules=("sensor",),
            min_level=LogLevel.WARN,
            thresholds=(
                FieldThreshold("temp", ThresholdOp.GTE, 80.0),
                FieldThreshold("voltage", ThresholdOp.LT, 3.3),
            ),
            immediate_alert=True,
        ),
    ]
    service = AnomalyService(rules)

    res = service.apply_update(
        PipelineUpdate(
            added=(
                _entry(0, 1.0, LogLevel.WARN, "overheat", module="sensor", extra={"temp": "85"}),
                _entry(
                    1,
                    2.0,
                    LogLevel.WARN,
                    "overheat",
                    module="sensor",
                    extra={"temp": "85", "voltage": "3.3"},
                ),
                _entry(
                    2,
                    3.0,
                    LogLevel.WARN,
                    "normal reading",
                    module="sensor",
                    extra={"temp": "85", "voltage": "3.1"},
                ),
                _entry(
                    3,
                    4.0,
                    LogLevel.WARN,
                    "overheat",
                    module="other",
                    extra={"temp": "85", "voltage": "3.1"},
                ),
                _entry(
                    4,
                    5.0,
                    LogLevel.WARN,
                    "OVERHEAT alarm",
                    module="sensor",
                    extra={"temp": "85.2", "voltage": "3.15"},
                ),
            )
        )
    )

    assert len(res.clusters) == 1
    assert res.clusters[0].rule_id == "text-and-range"
    assert res.clusters[0].evidence_sequences == (4,)
    assert len(res.new_alerts) == 1


def test_threshold_entries_cluster_via_normalize_message(make_loader) -> None:
    preset_yaml = """
schema_version: 1
preset_id: sensor-test
display_name: Sensor Test
line:
  pattern: '^\\[(?P<level>[A-Z]+)\\] \\[(?P<module>[^\\]]+)\\] (?P<message>.*)$'
  level_map:
    I: INFO
    W: WARN
    E: ERROR
  fields:
    temp: 'temp=([\\d.-]+)'
"""
    rules_yaml = """
schema_version: 1
rule_set_id: sensor-rules
display_name: 传感器规则
rules:
  - rule_id: temp-high
    category: 传感器过温
    severity: HIGH
    min_level: INFO
    modules: ["sensor"]
    thresholds:
      - field: temp
        op: gt
        value: 80.0
    min_occurrences: 3
    window_seconds: 60
    cooldown_seconds: 60
"""
    loader = make_loader(
        {
            "presets/logs/sensor-test.yaml": preset_yaml,
            "rules/anomalies/sensor-rules.yaml": rules_yaml,
        }
    )
    preset = load_preset(loader, "sensor-test")
    rule_set = load_rule_set(loader, "sensor-rules")
    pipeline = LogPipeline(LogParser(preset))
    service = AnomalyService(rule_set)

    lines = [
        ("[I] [sensor] temp=25.0 state=hot", 1.0),
        ("[W] [sensor] temp=81.2 state=hot", 2.0),
        ("[W] [sensor] temp=85.6 state=hot", 3.0),
        ("[W] [sensor] temp=90.0 state=hot", 4.0),
    ]
    alerts = []
    for text, ts in lines:
        res = service.apply_update(pipeline.feed(text, ts))
        alerts.extend(res.new_alerts)

    clusters = service.clusters()
    assert len(clusters) == 1
    assert clusters[0].rule_id == "temp-high"
    assert clusters[0].normalized_message == "temp=<NUM> state=hot"
    assert clusters[0].occurrence_count == 3
    assert clusters[0].evidence_sequences == (1, 2, 3)
    assert len(alerts) == 1
