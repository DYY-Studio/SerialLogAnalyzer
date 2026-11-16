"""异常检测控制器：将 ``AnomalyService`` 增量更新与状态流转映射为 Qt Signal。

控制器持有核心服务引用并在单 Qt 事件循环内协调状态变更，面板只消费只读快照。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate
from serial_log_analyzer.core.models.anomaly import AnomalyCluster, ClusterStatus
from serial_log_analyzer.core.services.anomaly import AnomalyService

__all__ = ["AnomalyController"]


class AnomalyController(QObject):
    """异常集群与告警控制器。

    参数:
        service: 异常规则检测与聚合服务。
        parent: 可选父对象。

    信号:
        clusters_changed(list): 异常簇列表变化时发出最新只读快照列表。
        alert_triggered(object): 每产生一条新 :class:`AlertEvent` 发出一次。
        error_occurred(str): 状态操作失败时发出错误提示。
    """

    clusters_changed = Signal(list)
    alert_triggered = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, service: AnomalyService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._last_clusters: list[AnomalyCluster] = list(service.clusters())

    def ingest_update(self, update: PipelineUpdate) -> None:
        """处理一次日志流水线增量，更新异常簇并发出新增告警信号。

        参数:
            update: 来自日志流水线（实时批处理 / 导入 / 容量淘汰）的增量对象。
        """

        try:
            result = self._service.apply_update(update)
        except AppError as exc:
            self.error_occurred.emit(str(exc))
            return

        current = list(result.clusters)
        if current != self._last_clusters:
            self._last_clusters = current
            self.clusters_changed.emit(list(current))
        for alert in result.new_alerts:
            self.alert_triggered.emit(alert)

    def acknowledge(self, cluster_id: str) -> None:
        """将指定异常簇标记为已确认（``ACKNOWLEDGED``）。"""

        self._set_status(cluster_id, ClusterStatus.ACKNOWLEDGED)

    def resolve(self, cluster_id: str) -> None:
        """将指定异常簇标记为已解决（``RESOLVED``）。"""

        self._set_status(cluster_id, ClusterStatus.RESOLVED)

    def reset(self) -> None:
        """清空全部异常簇与冷却计数（清空日志或切换 Preset 时调用）。"""

        self._service.reset()
        self._last_clusters = []
        self.clusters_changed.emit([])

    def clusters(self, *, active_only: bool = False) -> list[AnomalyCluster]:
        """返回当前异常簇快照列表。

        参数:
            active_only: 为 ``True`` 时过滤掉已解决条目。
        """

        return self._service.clusters(active_only=active_only)

    def _set_status(self, cluster_id: str, status: ClusterStatus) -> None:
        try:
            self._service.set_cluster_status(cluster_id, status)
        except AppError as exc:
            self.error_occurred.emit(str(exc))
            return
        self._last_clusters = self._service.clusters()
        self.clusters_changed.emit(list(self._last_clusters))
