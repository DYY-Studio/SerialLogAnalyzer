"""异常检测、时间窗口归并与本地冷却告警服务（纯 Python）。

职责：
- 接收 ``LogPipeline`` 产出的 :class:`PipelineUpdate`（``added`` / ``updated`` / ``dropped_sequences``）；
- 按规则匹配筛选候选，规范化动态地址与数值后按时间窗口归并到 :class:`AnomalyCluster`；
- 按 ``immediate_alert`` / ``min_occurrences`` + 冷却间隔产出瞬态 :class:`AlertEvent`；
- 维护有界证据、有界簇总量与淘汰序列清理，避免长时运行内存泄漏。
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.models.anomaly import (
    AlertEvent,
    AnomalyCluster,
    AnomalyRule,
    AnomalyRuleSet,
    AnomalySeverity,
    AnomalyUpdate,
    ClusterStatus,
)
from serial_log_analyzer.core.models.logs import LogEntry, LogLevel

__all__ = ["AnomalyService", "normalize_message"]

_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_NUM_RE = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])")
_SPACE_RE = re.compile(r"\s+")
_MAX_NORMALIZED_LEN = 160

# 显式严重度序：UNKNOWN 不得被当作 >= ERROR，仅在 min_level=VERBOSE 或 UNKNOWN 时参与匹配。
_KNOWN_LEVEL_RANK: dict[LogLevel, int] = {
    LogLevel.VERBOSE: 0,
    LogLevel.DEBUG: 1,
    LogLevel.INFO: 2,
    LogLevel.WARN: 3,
    LogLevel.ERROR: 4,
}


def normalize_message(message: str) -> str:
    """规范化消息首行以便同类异常归并：脱去十六进制地址与动态数值。"""

    first_line = ""
    for line in message.splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break
    if not first_line:
        return ""
    text = _HEX_RE.sub("<HEX>", first_line)
    text = _NUM_RE.sub("<NUM>", text)
    text = _SPACE_RE.sub(" ", text).strip()
    if len(text) > _MAX_NORMALIZED_LEN:
        return text[:_MAX_NORMALIZED_LEN] + "..."
    return text


def _level_passes(entry_level: LogLevel, min_level: LogLevel) -> bool:
    """判断日志级别是否达到规则门槛，防止 ``UNKNOWN`` 误当 ``ERROR``。"""

    if min_level is LogLevel.VERBOSE:
        return True
    if min_level is LogLevel.UNKNOWN:
        return entry_level is LogLevel.UNKNOWN
    entry_rank = _KNOWN_LEVEL_RANK.get(entry_level)
    if entry_rank is None:
        return False
    return entry_rank >= _KNOWN_LEVEL_RANK[min_level]


@dataclass
class _ClusterState:
    """服务内部可变聚合状态；对外总是转为冻结的 :class:`AnomalyCluster`。"""

    cluster_id: str
    key: tuple[str, str, str]
    rule_id: str
    category: str
    severity: AnomalySeverity
    normalized_message: str
    modules: list[str]
    first_seen: float
    last_seen: float
    occurrence_count: int = 0
    evidence_sequences: list[int] = field(default_factory=list)
    recent_hits: deque[float] = field(default_factory=deque)
    status: ClusterStatus = ClusterStatus.ACTIVE
    last_alerted_at: float | None = None

    def to_snapshot(self) -> AnomalyCluster:
        return AnomalyCluster(
            cluster_id=self.cluster_id,
            rule_id=self.rule_id,
            category=self.category,
            severity=self.severity,
            normalized_message=self.normalized_message,
            modules=tuple(self.modules),
            first_seen=self.first_seen,
            last_seen=self.last_seen,
            occurrence_count=self.occurrence_count,
            evidence_sequences=tuple(self.evidence_sequences),
            status=self.status,
        )


class AnomalyService:
    """异常规则检测、窗口归并与冷却告警服务。

    参数:
        rules: 规则集或规则列表（按顺序优先级匹配）。
        max_evidence: 单簇最多保留的证据 ``sequence`` 条数（默认 20）。
        max_clusters: 内存中最多保留的聚合簇总数，超出时淘汰最旧条目（默认 500）。
        max_tracked_sequences: 序列幂等索引容量上限（默认 200000）。
    """

    def __init__(
        self,
        rules: AnomalyRuleSet | Sequence[AnomalyRule] = (),
        *,
        max_evidence: int | None = None,
        max_clusters: int = 500,
        max_tracked_sequences: int = 200_000,
    ) -> None:
        if isinstance(rules, AnomalyRuleSet):
            self._rules: tuple[AnomalyRule, ...] = rules.rules
            default_evidence = rules.max_evidence
        else:
            self._rules = tuple(rules)
            default_evidence = 20
        self._max_evidence = max(1, max_evidence if max_evidence is not None else default_evidence)
        self._max_clusters = max(1, int(max_clusters))
        self._max_tracked_sequences = max(1, int(max_tracked_sequences))

        self._clusters: dict[str, _ClusterState] = {}
        self._active_by_key: dict[tuple[str, str, str], str] = {}
        self._matched_sequences: set[int] = set()
        self._matched_order: deque[int] = deque()
        self._next_cluster_num = 1
        self._next_alert_num = 1

    def set_rules(self, rules: AnomalyRuleSet | Sequence[AnomalyRule]) -> None:
        """替换当前生效的规则列表（仅影响后续到达日志）。"""

        if isinstance(rules, AnomalyRuleSet):
            self._rules = rules.rules
            self._max_evidence = max(1, rules.max_evidence)
        else:
            self._rules = tuple(rules)

    def reset(self) -> None:
        """清空全部聚合簇与去重索引（切换 Preset 或清空日志时调用）。"""

        self._clusters.clear()
        self._active_by_key.clear()
        self._matched_sequences.clear()
        self._matched_order.clear()
        self._next_cluster_num = 1
        self._next_alert_num = 1

    def clusters(self, *, active_only: bool = False) -> list[AnomalyCluster]:
        """返回聚合簇只读快照列表（按最近命中时间倒序）。"""

        items = [
            state.to_snapshot()
            for state in self._clusters.values()
            if not active_only or state.status is ClusterStatus.ACTIVE
        ]
        items.sort(key=lambda item: (item.last_seen, item.cluster_id), reverse=True)
        return items

    def set_cluster_status(self, cluster_id: str, status: ClusterStatus) -> AnomalyCluster:
        """更新指定聚合组的状态（如「已确认」「已解决」）。

        异常:
            ConfigError: 指定的 ``cluster_id`` 不存在。
        """

        state = self._clusters.get(cluster_id)
        if state is None:
            raise ConfigError(f"未找到异常聚合组：{cluster_id}")
        state.status = status
        if status is ClusterStatus.RESOLVED and self._active_by_key.get(state.key) == cluster_id:
            self._active_by_key.pop(state.key, None)
        return state.to_snapshot()

    def apply_update(self, update: PipelineUpdate) -> AnomalyUpdate:
        """处理一次日志流水线增量，返回最新聚合快照与本轮新告警。"""

        if update.dropped_sequences:
            self._purge_dropped(update.dropped_sequences)

        alerts: list[AlertEvent] = []
        for entry in (*update.added, *update.updated):
            if entry.sequence in self._matched_sequences:
                continue
            rule = self._match_rule(entry)
            if rule is None:
                continue
            self._record_matched_sequence(entry.sequence)
            alert = self._ingest_hit(entry, rule)
            if alert is not None:
                alerts.append(alert)

        return AnomalyUpdate(
            clusters=tuple(self.clusters()),
            new_alerts=tuple(alerts),
        )

    # ------------------------------------------------------------------
    # 内部匹配、归并、冷却与淘汰
    # ------------------------------------------------------------------

    def _match_rule(self, entry: LogEntry) -> AnomalyRule | None:
        msg_lower = entry.message.lower()
        module_lower = (entry.module or "").lower()
        for rule in self._rules:
            if not rule.enabled:
                continue
            if not _level_passes(entry.level, rule.min_level):
                continue
            if rule.modules and (not entry.module or module_lower not in rule.modules):
                continue
            keyword_hit = any(kw in msg_lower for kw in rule.keywords)
            pattern_hit = rule.pattern is not None and rule.pattern.search(entry.message) is not None
            if keyword_hit or pattern_hit:
                return rule
        return None

    def _ingest_hit(self, entry: LogEntry, rule: AnomalyRule) -> AlertEvent | None:
        normalized = normalize_message(entry.message) or f"<{entry.level.name}>"
        module_label = entry.module or "-"
        key = (rule.rule_id, module_label, normalized)
        now = entry.received_at

        state = self._resolve_or_create_cluster(key, rule, normalized, module_label, now)
        state.occurrence_count += 1
        state.last_seen = max(state.last_seen, now)
        if module_label not in state.modules:
            state.modules.append(module_label)
        self._append_evidence(state.evidence_sequences, entry.sequence)

        state.recent_hits.append(now)
        cutoff = now - rule.window_seconds
        while state.recent_hits and state.recent_hits[0] < cutoff:
            state.recent_hits.popleft()

        return self._maybe_trigger_alert(state, rule, now)

    def _resolve_or_create_cluster(
        self,
        key: tuple[str, str, str],
        rule: AnomalyRule,
        normalized: str,
        module_label: str,
        now: float,
    ) -> _ClusterState:
        existing_id = self._active_by_key.get(key)
        if existing_id is not None:
            existing = self._clusters.get(existing_id)
            if (
                existing is not None
                and existing.status is not ClusterStatus.RESOLVED
                and (now - existing.last_seen) <= rule.window_seconds
            ):
                return existing

        self._evict_clusters_if_needed()
        cluster_id = f"C-{self._next_cluster_num:04d}"
        self._next_cluster_num += 1
        state = _ClusterState(
            cluster_id=cluster_id,
            key=key,
            rule_id=rule.rule_id,
            category=rule.category,
            severity=rule.severity,
            normalized_message=normalized,
            modules=[module_label],
            first_seen=now,
            last_seen=now,
        )
        self._clusters[cluster_id] = state
        self._active_by_key[key] = cluster_id
        return state

    def _maybe_trigger_alert(
        self, state: _ClusterState, rule: AnomalyRule, now: float
    ) -> AlertEvent | None:
        if state.status is not ClusterStatus.ACTIVE:
            return None

        hits_in_window = len(state.recent_hits)
        if rule.immediate_alert:
            reason = f"规则 {rule.rule_id} 立即触发"
        elif hits_in_window >= rule.min_occurrences:
            reason = f"{int(rule.window_seconds)} 秒内命中 {hits_in_window} 次（阈值 {rule.min_occurrences}）"
        else:
            return None

        if state.last_alerted_at is not None and (now - state.last_alerted_at) < rule.cooldown_seconds:
            return None

        state.last_alerted_at = now
        alert_id = f"A-{self._next_alert_num:04d}"
        self._next_alert_num += 1
        return AlertEvent(
            alert_id=alert_id,
            cluster_id=state.cluster_id,
            rule_id=rule.rule_id,
            severity=state.severity,
            category=state.category,
            title=f"[{state.category}] {state.normalized_message}",
            reason=reason,
            occurrence_count=state.occurrence_count,
            triggered_at=now,
            evidence_sequences=tuple(state.evidence_sequences),
        )

    def _append_evidence(self, sequences: list[int], seq: int) -> None:
        if seq in sequences:
            return
        if len(sequences) < self._max_evidence:
            sequences.append(seq)
            return
        head_keep = max(1, self._max_evidence // 4)
        tail_keep = self._max_evidence - head_keep
        if tail_keep <= 1:
            sequences[:] = [*sequences[: max(0, self._max_evidence - 1)], seq]
            return
        sequences[:] = [*sequences[:head_keep], *sequences[-(tail_keep - 1) :], seq]

    def _record_matched_sequence(self, seq: int) -> None:
        self._matched_sequences.add(seq)
        self._matched_order.append(seq)
        while len(self._matched_order) > self._max_tracked_sequences:
            oldest = self._matched_order.popleft()
            self._matched_sequences.discard(oldest)

    def _purge_dropped(self, dropped_sequences: tuple[int, ...]) -> None:
        dropped = set(dropped_sequences)
        self._matched_sequences.difference_update(dropped)
        if not self._matched_sequences and self._matched_order:
            self._matched_order.clear()
        for state in self._clusters.values():
            if state.evidence_sequences:
                state.evidence_sequences = [
                    seq for seq in state.evidence_sequences if seq not in dropped
                ]

    def _evict_clusters_if_needed(self) -> None:
        while len(self._clusters) >= self._max_clusters:
            resolved = [
                state for state in self._clusters.values() if state.status is ClusterStatus.RESOLVED
            ]
            pool = resolved if resolved else list(self._clusters.values())
            victim = min(pool, key=lambda item: (item.last_seen, item.cluster_id))
            self._clusters.pop(victim.cluster_id, None)
            if self._active_by_key.get(victim.key) == victim.cluster_id:
                self._active_by_key.pop(victim.key, None)
