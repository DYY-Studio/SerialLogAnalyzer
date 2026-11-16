"""结构化诊断报告纯逻辑测试（不启动 Qt）。"""

from __future__ import annotations

from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.analysis import (
    AnalysisMessage,
    AnalysisResult,
    AnalysisState,
    MessageRole,
    TokenUsage,
)
from serial_log_analyzer.core.models.anomaly import AnomalyRule, AnomalySeverity, ClusterStatus
from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.core.services.anomaly import AnomalyService
from serial_log_analyzer.core.services.report import (
    build_diagnostic_report,
    render_report_markdown,
    report_to_dict,
)


def _rules() -> list[AnomalyRule]:
    return [
        AnomalyRule(
            rule_id="mem-oom",
            category="内存分配失败",
            severity=AnomalySeverity.CRITICAL,
            keywords=("malloc failed",),
            min_level=LogLevel.ERROR,
            immediate_alert=True,
        ),
        AnomalyRule(
            rule_id="uart-overflow",
            category="通信异常",
            severity=AnomalySeverity.HIGH,
            keywords=("rx overflow",),
            min_level=LogLevel.WARN,
        ),
    ]


def test_build_report_on_empty_pipeline(parser) -> None:
    pipeline = LogPipeline(parser)
    anomaly_service = AnomalyService(_rules())

    report = build_diagnostic_report(
        pipeline, anomaly_service, preset_id="hi3861-default", generated_at=1_700_000_000.0
    )

    assert report.log_count == 0
    assert report.time_range is None
    assert report.clusters == ()
    assert report.llm_diagnosis is None

    md = render_report_markdown(report)
    assert "当前缓冲日志数**：0" in md
    assert "未检测到命中异常规则的日志记录" in md
    assert "本次未附带 LLM 辅助诊断结果" in md

    data = report_to_dict(report)
    assert data["summary"]["log_count"] == 0
    assert data["summary"]["time_range"] is None
    assert data["rule_facts"]["clusters"] == []
    assert data["llm_inference"] is None


def test_build_report_orders_clusters_extracts_evidences_and_separates_llm(parser) -> None:
    pipeline = LogPipeline(parser, capacity=10)
    anomaly_service = AnomalyService(_rules())

    lines = [
        (1_700_000_010.0, "[W] [uart] rx overflow 1"),
        (1_700_000_011.0, "[W] [uart] rx overflow 2"),
        (1_700_000_012.0, "[I] [sensor] temperature=26.5"),
        (1_700_000_013.0, "[E] [memory] malloc failed size=1024"),
    ]
    for ts, line in lines:
        anomaly_service.apply_update(pipeline.feed(line, ts))

    # 把其中一簇标记为已确认
    uart_cluster = next(c for c in anomaly_service.clusters() if c.rule_id == "uart-overflow")
    anomaly_service.set_cluster_status(uart_cluster.cluster_id, ClusterStatus.ACKNOWLEDGED)

    analysis = AnalysisResult(
        content="根因推测：堆内存碎片导致分配失败。",
        reasoning="思考过程略",
        usage=TokenUsage(input_tokens=100, output_tokens=40, total_tokens=140, cached_tokens=20),
        state=AnalysisState.DONE,
        conversation=[
            AnalysisMessage(MessageRole.USER, "prompt", summary="定位错误"),
            AnalysisMessage(MessageRole.ASSISTANT, "根因推测：堆内存碎片导致分配失败。"),
        ],
    )

    report = build_diagnostic_report(
        pipeline,
        anomaly_service,
        preset_id="hi3861-default",
        analysis_result=analysis,
        profile_label="deepseek · deepseek-chat",
        generated_at=1_700_000_020.0,
    )

    assert report.log_count == 4
    assert report.time_range == (1_700_000_010.0, 1_700_000_013.0)
    assert report.level_counts["ERROR"] == 1
    assert report.level_counts["WARN"] == 2
    assert report.level_counts["INFO"] == 1
    assert report.status_counts["active"] == 1
    assert report.status_counts["acknowledged"] == 1

    # CRITICAL 优先于 HIGH
    assert [item.cluster.rule_id for item in report.clusters] == ["mem-oom", "uart-overflow"]
    assert [ev.sequence for ev in report.clusters[0].evidences] == [3]
    assert "malloc failed size=1024" in report.clusters[0].evidences[0].rendered
    assert report.clusters[0].evidences[0].extra == {}
    assert report.clusters[0].missing_sequences == ()

    md = render_report_markdown(report)
    assert "## 2. 异常聚合事实（本地规则引擎）" in md
    assert "## 3. LLM 辅助诊断推断（仅供参考）" in md
    assert "#3 [" in md
    assert "deepseek · deepseek-chat" in md
    assert "根因推测：堆内存碎片导致分配失败。" in md

    data = report_to_dict(report)
    assert data["rule_facts"]["clusters"][0]["rule_id"] == "mem-oom"
    assert data["llm_inference"]["profile_label"] == "deepseek · deepseek-chat"
    assert data["llm_inference"]["usage"]["total_tokens"] == 140
    assert "仅供参考" in data["llm_inference"]["disclaimer"]


def test_build_report_marks_evicted_evidence_sequences(parser) -> None:
    pipeline = LogPipeline(parser, capacity=2)
    anomaly_service = AnomalyService(_rules())

    anomaly_service.apply_update(pipeline.feed("[E] [memory] malloc failed old", 1_700_000_001.0))
    anomaly_service.apply_update(pipeline.feed("[I] [app] tick 1", 1_700_000_002.0))
    anomaly_service.apply_update(pipeline.feed("[I] [app] tick 2", 1_700_000_003.0))

    # 人工模拟外部残留或未清理时的序号缺失兜底场景：强制查看未触发 purge 的情况
    report = build_diagnostic_report(pipeline, anomaly_service, preset_id="hi3861-default")
    # 经过 apply_update 的 dropped_sequences 同步清理后，missing_sequences 应为空；
    # 若直接使用未同步清理的旧序号（例如 capacity 被直接缩减前已记录的序号），report 亦需安全标注截断。
    assert len(report.clusters) == 1
    assert report.clusters[0].evidences == ()

    # 若 pipeline 在未触发 apply_update 的情况下缩容淘汰，report 应把缺失序号记入 missing_sequences。
    pipe2 = LogPipeline(parser, capacity=5)
    svc2 = AnomalyService(_rules())
    svc2.apply_update(pipe2.feed("[E] [memory] malloc failed keep-check", 1_700_000_010.0))
    pipe2.feed("[I] [app] filler 1", 1_700_000_011.0)
    pipe2.feed("[I] [app] filler 2", 1_700_000_012.0)
    pipe2.capacity = 1
    pipe2.enforce_capacity()

    report2 = build_diagnostic_report(pipe2, svc2, preset_id="hi3861-default")
    assert report2.clusters[0].evidences == ()
    assert report2.clusters[0].missing_sequences == (0,)
    assert "已淘汰/截断证据序号**：#0" in render_report_markdown(report2)


def test_report_includes_structured_extra_in_evidence_and_json(parser) -> None:
    """命中带结构化 extra 字段的证据应在 Markdown 与 JSON 报告中完整保留。"""

    pipeline = LogPipeline(parser, capacity=10)
    rule = AnomalyRule(
        rule_id="sensor-overheat",
        category="温度异常",
        severity=AnomalySeverity.HIGH,
        keywords=("overheat",),
        min_level=LogLevel.WARN,
    )
    anomaly_service = AnomalyService([rule])
    anomaly_service.apply_update(
        pipeline.feed("[W] [sensor] overheat temperature=82.5 humidity=45.0", 1_700_000_100.0)
    )

    report = build_diagnostic_report(
        pipeline,
        anomaly_service,
        preset_id="hi3861-default",
        generated_at=1_700_000_101.0,
    )
    ev = report.clusters[0].evidences[0]
    assert ev.extra == {"temperature": "82.5", "humidity": "45.0"}
    assert "[extra: temperature=82.5 humidity=45.0]" in ev.rendered
    assert "[extra: temperature=82.5 humidity=45.0]" in render_report_markdown(report)

    payload = report_to_dict(report)
    assert payload["rule_facts"]["clusters"][0]["evidences"][0]["extra"] == {
        "temperature": "82.5",
        "humidity": "45.0",
    }
