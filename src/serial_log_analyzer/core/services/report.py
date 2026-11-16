"""结构化诊断报告纯逻辑（无 Qt、无直接文件 IO）。

将本地日志统计与确定性异常规则事实（:class:`AnomalyCluster` + 原始证据引用）
和可选的 LLM 辅助诊断推断（:class:`AnalysisResult`）装配为结构化只读报告，
并提供 Markdown 与 JSON 字典渲染能力，显式区分规则事实与模型推断。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from serial_log_analyzer.core.logs.pipeline import LogPipeline
from serial_log_analyzer.core.models.analysis import (
    AnalysisResult,
    MessageRole,
    TokenUsage,
)
from serial_log_analyzer.core.models.anomaly import (
    AnomalyCluster,
    AnomalySeverity,
    ClusterStatus,
)
from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.core.services.anomaly import AnomalyService

__all__ = [
    "ClusterReportItem",
    "DiagnosticSummaryReport",
    "EvidenceLine",
    "LlmDiagnosisSummary",
    "build_diagnostic_report",
    "render_report_markdown",
    "report_to_dict",
]

_SEVERITY_LABELS: dict[AnomalySeverity, str] = {
    AnomalySeverity.LOW: "低",
    AnomalySeverity.MEDIUM: "中",
    AnomalySeverity.HIGH: "高",
    AnomalySeverity.CRITICAL: "严重",
}

_STATUS_LABELS: dict[ClusterStatus, str] = {
    ClusterStatus.ACTIVE: "活动",
    ClusterStatus.ACKNOWLEDGED: "已确认",
    ClusterStatus.RESOLVED: "已解决",
}

_LLM_DISCLAIMER = "以下内容由大语言模型基于会话上下文推断生成，仅供参考；请结合第 2 节规则事实与原始日志证据复核。"


@dataclass(frozen=True)
class EvidenceLine:
    """报告引用的单条原始日志证据。"""

    sequence: int
    received_at: float
    device_time: str | None
    level: str
    module: str | None
    rendered: str


@dataclass(frozen=True)
class ClusterReportItem:
    """单个异常聚合组的报告明细（含存活证据与已淘汰序号记录）。"""

    cluster: AnomalyCluster
    evidences: tuple[EvidenceLine, ...] = ()
    missing_sequences: tuple[int, ...] = ()


@dataclass(frozen=True)
class LlmDiagnosisSummary:
    """LLM 辅助诊断推断摘要（与规则事实显式隔离，不含凭据信息）。"""

    profile_label: str | None
    content: str
    reasoning: str | None = None
    turns: int = 0
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class DiagnosticSummaryReport:
    """结构化诊断报告只读 DTO。"""

    generated_at: float
    preset_id: str
    log_count: int
    time_range: tuple[float, float] | None
    level_counts: dict[str, int]
    status_counts: dict[str, int]
    clusters: tuple[ClusterReportItem, ...] = ()
    llm_diagnosis: LlmDiagnosisSummary | None = None


def build_diagnostic_report(
    pipeline: LogPipeline,
    anomaly_service: AnomalyService,
    *,
    preset_id: str,
    analysis_result: AnalysisResult | None = None,
    profile_label: str | None = None,
    generated_at: float | None = None,
) -> DiagnosticSummaryReport:
    """从日志流水线、异常服务与可选 LLM 分析结果构建只读诊断报告。

    参数:
        pipeline: 当前日志流水线。
        anomaly_service: 异常规则检测与聚合服务。
        preset_id: 当前日志解析 Preset 标识。
        analysis_result: 可选的 LLM 最近一次有效分析结果。
        profile_label: 可选的模型 Profile 展示标识（不含密钥）。
        generated_at: 可选生成时间戳（默认当前 ``time.time()``）。

    返回:
        :class:`DiagnosticSummaryReport`。
    """

    entries = pipeline.entries()
    entry_by_seq = {entry.sequence: entry for entry in entries}

    level_counts = {level.name: 0 for level in LogLevel}
    for entry in entries:
        level_counts[entry.level.name] = level_counts.get(entry.level.name, 0) + 1

    time_range: tuple[float, float] | None = (
        (entries[0].received_at, entries[-1].received_at) if entries else None
    )

    sorted_clusters = sorted(
        anomaly_service.clusters(),
        key=lambda item: (item.severity.value, item.occurrence_count, item.last_seen),
        reverse=True,
    )
    status_counts = {status.value: 0 for status in ClusterStatus}
    items: list[ClusterReportItem] = []
    for cluster in sorted_clusters:
        status_counts[cluster.status.value] = status_counts.get(cluster.status.value, 0) + 1
        evidences: list[EvidenceLine] = []
        missing: list[int] = []
        for seq in cluster.evidence_sequences:
            entry = entry_by_seq.get(seq)
            if entry is None:
                missing.append(seq)
                continue
            evidences.append(
                EvidenceLine(
                    sequence=entry.sequence,
                    received_at=entry.received_at,
                    device_time=entry.device_time,
                    level=entry.level.name,
                    module=entry.module,
                    rendered=pipeline.render([entry])[0],
                )
            )
        items.append(
            ClusterReportItem(
                cluster=cluster,
                evidences=tuple(evidences),
                missing_sequences=tuple(missing),
            )
        )

    return DiagnosticSummaryReport(
        generated_at=time.time() if generated_at is None else float(generated_at),
        preset_id=preset_id,
        log_count=len(entries),
        time_range=time_range,
        level_counts=level_counts,
        status_counts=status_counts,
        clusters=tuple(items),
        llm_diagnosis=_build_llm_summary(analysis_result, profile_label),
    )


def render_report_markdown(report: DiagnosticSummaryReport) -> str:
    """将诊断报告渲染为可人工复核的中文 Markdown 文本。"""

    lines: list[str] = [
        "# SerialLogAnalyzer 诊断报告",
        "",
        "## 1. 运行概览",
        f"- **生成时间**：{_format_ts(report.generated_at)}",
        f"- **日志 Preset**：`{report.preset_id}`",
        f"- **当前缓冲日志数**：{report.log_count}",
        f"- **时间范围**：{_format_range(report.time_range)}",
        f"- **级别统计**：{_format_level_counts(report.level_counts)}",
        (
            f"- **异常聚合组**：共 {len(report.clusters)} 组"
            f"（活动 {report.status_counts.get(ClusterStatus.ACTIVE.value, 0)} / "
            f"已确认 {report.status_counts.get(ClusterStatus.ACKNOWLEDGED.value, 0)} / "
            f"已解决 {report.status_counts.get(ClusterStatus.RESOLVED.value, 0)}）"
        ),
        "",
        "## 2. 异常聚合事实（本地规则引擎）",
        "> 说明：本节为本地确定性规则匹配与时间窗口聚合事实，不包含大模型推测。",
        "",
    ]

    if not report.clusters:
        lines.append("当前未检测到命中异常规则的日志记录。")
    else:
        for item in report.clusters:
            lines.extend(_render_cluster_markdown(item))

    lines.extend(["", "## 3. LLM 辅助诊断推断（仅供参考）", f"> {_LLM_DISCLAIMER}", ""])
    if report.llm_diagnosis is None:
        lines.append("本次未附带 LLM 辅助诊断结果。")
    else:
        diag = report.llm_diagnosis
        meta: list[str] = []
        if diag.profile_label:
            meta.append(f"模型服务：`{diag.profile_label}`")
        if diag.turns:
            meta.append(f"对话轮数：{diag.turns}")
        if diag.usage is not None:
            meta.append(
                f"用量：输入 {diag.usage.input_tokens} / 输出 {diag.usage.output_tokens} / 总计 {diag.usage.total_tokens} tokens"
            )
        if meta:
            lines.append("- " + " | ".join(meta))
            lines.append("")
        lines.append(diag.content)

    return "\n".join(lines).rstrip() + "\n"


def report_to_dict(report: DiagnosticSummaryReport) -> dict[str, Any]:
    """将诊断报告转换为适合 JSON 序列化的结构化字典。"""

    return {
        "schema_version": 1,
        "generated_at": round(report.generated_at, 6),
        "generated_at_iso": _format_ts(report.generated_at),
        "preset_id": report.preset_id,
        "summary": {
            "log_count": report.log_count,
            "time_range": (
                {
                    "start": round(report.time_range[0], 6),
                    "end": round(report.time_range[1], 6),
                    "start_iso": _format_ts(report.time_range[0]),
                    "end_iso": _format_ts(report.time_range[1]),
                }
                if report.time_range is not None
                else None
            ),
            "level_counts": dict(report.level_counts),
            "cluster_count": len(report.clusters),
            "status_counts": dict(report.status_counts),
        },
        "rule_facts": {
            "clusters": [_cluster_to_dict(item) for item in report.clusters],
        },
        "llm_inference": (
            {
                "disclaimer": _LLM_DISCLAIMER,
                "profile_label": report.llm_diagnosis.profile_label,
                "turns": report.llm_diagnosis.turns,
                "content": report.llm_diagnosis.content,
                "reasoning": report.llm_diagnosis.reasoning,
                "usage": (
                    {
                        "input_tokens": report.llm_diagnosis.usage.input_tokens,
                        "output_tokens": report.llm_diagnosis.usage.output_tokens,
                        "total_tokens": report.llm_diagnosis.usage.total_tokens,
                        "cached_tokens": report.llm_diagnosis.usage.cached_tokens,
                    }
                    if report.llm_diagnosis.usage is not None
                    else None
                ),
            }
            if report.llm_diagnosis is not None
            else None
        ),
    }


def _build_llm_summary(
    result: AnalysisResult | None, profile_label: str | None
) -> LlmDiagnosisSummary | None:
    if result is None:
        return None
    content = result.content.strip()
    if not content:
        for msg in reversed(result.conversation):
            if msg.role is MessageRole.ASSISTANT and msg.content.strip():
                content = msg.content.strip()
                break
    if not content:
        return None
    turns = sum(1 for msg in result.conversation if msg.role is MessageRole.USER)
    if turns == 0:
        turns = 1
    return LlmDiagnosisSummary(
        profile_label=profile_label,
        content=content,
        reasoning=result.reasoning,
        turns=turns,
        usage=result.usage,
    )


def _render_cluster_markdown(item: ClusterReportItem) -> list[str]:
    c = item.cluster
    sev = _SEVERITY_LABELS.get(c.severity, c.severity.name)
    status = _STATUS_LABELS.get(c.status, c.status.value)
    modules = ", ".join(c.modules) if c.modules else "-"
    lines = [
        f"### [{sev}] {c.category}（{c.cluster_id} · {status}）",
        (
            f"- **规则**：`{c.rule_id}` | **模块**：`{modules}` | "
            f"**累计命中**：{c.occurrence_count} 次 | "
            f"**时间**：{_format_ts(c.first_seen)} ~ {_format_ts(c.last_seen)}"
        ),
        f"- **规范化模式**：`{c.normalized_message}`",
    ]
    if item.evidences:
        lines.append("- **原始日志证据**：")
        lines.append("```text")
        for ev in item.evidences:
            ts = _format_ts(ev.received_at)
            dt = f" [board={ev.device_time}]" if ev.device_time else ""
            lines.append(f"#{ev.sequence} [{ts}]{dt} {ev.rendered}")
        lines.append("```")
    if item.missing_sequences:
        missing_text = ", ".join(f"#{seq}" for seq in item.missing_sequences)
        lines.append(f"- **已淘汰/截断证据序号**：{missing_text}（因内存环形缓冲容量上限已移出）")
    lines.append("")
    return lines


def _cluster_to_dict(item: ClusterReportItem) -> dict[str, Any]:
    c = item.cluster
    return {
        "cluster_id": c.cluster_id,
        "rule_id": c.rule_id,
        "category": c.category,
        "severity": c.severity.name,
        "status": c.status.value,
        "modules": list(c.modules),
        "occurrence_count": c.occurrence_count,
        "first_seen": round(c.first_seen, 6),
        "last_seen": round(c.last_seen, 6),
        "first_seen_iso": _format_ts(c.first_seen),
        "last_seen_iso": _format_ts(c.last_seen),
        "normalized_message": c.normalized_message,
        "evidence_sequences": list(c.evidence_sequences),
        "evidences": [
            {
                "sequence": ev.sequence,
                "received_at": round(ev.received_at, 6),
                "received_at_iso": _format_ts(ev.received_at),
                "device_time": ev.device_time,
                "level": ev.level,
                "module": ev.module,
                "rendered": ev.rendered,
            }
            for ev in item.evidences
        ],
        "missing_sequences": list(item.missing_sequences),
    }


def _format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _format_range(time_range: tuple[float, float] | None) -> str:
    if time_range is None:
        return "（无日志）"
    return f"{_format_ts(time_range[0])} ~ {_format_ts(time_range[1])}"


def _format_level_counts(level_counts: dict[str, int]) -> str:
    return " / ".join(f"{name}={count}" for name, count in level_counts.items())
