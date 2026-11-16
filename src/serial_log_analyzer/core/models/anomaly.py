"""异常检测、窗口聚合与本地告警的领域模型（纯 Python）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from serial_log_analyzer.core.models.logs import LogLevel

__all__ = [
    "AlertEvent",
    "AnomalyCluster",
    "AnomalyRule",
    "AnomalyRuleSet",
    "AnomalySeverity",
    "AnomalyUpdate",
    "ClusterStatus",
]


class AnomalySeverity(Enum):
    """异常严重程度，``value`` 为可比较的严重度序号。"""

    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, AnomalySeverity):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other: object) -> bool:
        if not isinstance(other, AnomalySeverity):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, AnomalySeverity):
            return NotImplemented
        return self.value > other.value

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, AnomalySeverity):
            return NotImplemented
        return self.value >= other.value


class ClusterStatus(Enum):
    """异常聚合组状态。"""

    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class AnomalyRule:
    """单条声明式异常筛选与触发规则。

    参数:
        rule_id: 规则唯一标识。
        category: 异常分类名称（如「内存分配失败」）。
        severity: 命中所生成簇的严重程度。
        keywords: 大小写不敏感子串列表（已转小写）。
        pattern: 可选已编译正则；与 ``keywords`` 为或关系。
        modules: 限定模块列表（已转小写）；为空表示不限模块。
        min_level: 最低日志级别门限。
        immediate_alert: 是否在首次命中时立即触发告警（仍受冷却约束）。
        min_occurrences: 时间窗口内触发告警的最低累计次数。
        window_seconds: 聚合与计数滑动时间窗口（秒）。
        cooldown_seconds: 同一簇两次告警之间的最小冷却间隔（秒）。
        enabled: 是否启用。
    """

    rule_id: str
    category: str
    severity: AnomalySeverity
    keywords: tuple[str, ...] = ()
    pattern: re.Pattern[str] | None = None
    modules: tuple[str, ...] = ()
    min_level: LogLevel = LogLevel.WARN
    immediate_alert: bool = False
    min_occurrences: int = 1
    window_seconds: float = 60.0
    cooldown_seconds: float = 60.0
    enabled: bool = True


@dataclass(frozen=True)
class AnomalyRuleSet:
    """一份完整的异常规则集 YAML 声明。

    参数:
        rule_set_id: 规则集标识，必须与文件名主名一致。
        display_name: 展示名称。
        rules: 规则列表（按声明顺序优先级匹配）。
        window_seconds: 默认聚合窗口（秒）。
        cooldown_seconds: 默认告警冷却（秒）。
        max_evidence: 单簇保留的证据序号上限。
        schema_version: 声明版本号，当前固定为 ``1``。
        source_path: 加载来源路径，用于错误提示。
    """

    rule_set_id: str
    display_name: str
    rules: tuple[AnomalyRule, ...]
    window_seconds: float = 60.0
    cooldown_seconds: float = 60.0
    max_evidence: int = 20
    schema_version: int = 1
    source_path: str = ""


@dataclass(frozen=True)
class AnomalyCluster:
    """时间窗口内归并后的异常聚合组只读快照。

    参数:
        cluster_id: 聚合组唯一标识。
        rule_id: 命中的规则标识（单一规则匹配）。
        category: 异常分类。
        severity: 严重程度。
        normalized_message: 去除动态数值/十六进制地址后的消息模板。
        modules: 关联模块集合。
        first_seen: 首次命中时间（``LogEntry.received_at``）。
        last_seen: 最近一次命中时间（``LogEntry.received_at``）。
        occurrence_count: 累计命中条数。
        evidence_sequences: 代表性的原始日志 ``sequence`` 列表（有界）。
        status: 当前状态（活动 / 已确认 / 已解决）。
    """

    cluster_id: str
    rule_id: str
    category: str
    severity: AnomalySeverity
    normalized_message: str
    modules: tuple[str, ...]
    first_seen: float
    last_seen: float
    occurrence_count: int
    evidence_sequences: tuple[int, ...]
    status: ClusterStatus = ClusterStatus.ACTIVE


@dataclass(frozen=True)
class AlertEvent:
    """本地规则告警事件快照（瞬态通知载荷，不单独持久历史表）。

    参数:
        alert_id: 告警事件标识。
        cluster_id: 关联聚合组标识。
        rule_id: 触发规则标识。
        severity: 告警级别。
        category: 异常分类。
        title: 简明告警标题。
        reason: 触发原因说明（如「立即触发」或「窗口内命中 N 次」）。
        occurrence_count: 触发时聚合组累计次数。
        triggered_at: 触发时间戳。
        evidence_sequences: 关联证据日志序号。
    """

    alert_id: str
    cluster_id: str
    rule_id: str
    severity: AnomalySeverity
    category: str
    title: str
    reason: str
    occurrence_count: int
    triggered_at: float
    evidence_sequences: tuple[int, ...]


@dataclass(frozen=True)
class AnomalyUpdate:
    """一次异常流水线更新的输出：最新聚合快照与本轮新触发的告警。"""

    clusters: tuple[AnomalyCluster, ...] = ()
    new_alerts: tuple[AlertEvent, ...] = ()
