"""纯 Python 设备遥测时序缓存（从 ``LogEntry.extra`` 抽取有限实数，无 Qt/pyqtgraph/numpy 依赖）。

职责：
- 安全解析 ``LogEntry.extra`` 中的有限数值字段（拒绝空串、布尔语义与 ``NaN``/``Inf``）；
- 维护按 Preset 声明顺序优先、运行期新字段顺序追加的去重字段列表；
- 响应 :class:`PipelineUpdate` 的 ``dropped_sequences`` 与 ``added``，以首条有效数值日志为 ``t=0.0``
  基准记录有界相对时间序列，供图表展示层读取。
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.logs.pipeline import PipelineUpdate

__all__ = [
    "TelemetryBuffer",
    "TelemetrySample",
    "extract_numeric_extra",
    "parse_finite_float",
]


def parse_finite_float(raw: str) -> float | None:
    """将文本字段解析为有限浮点数；非字符串、空串、布尔文本或 ``NaN``/``Inf`` 返回 ``None``。"""

    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def extract_numeric_extra(extra: Mapping[str, str]) -> dict[str, float]:
    """从 ``LogEntry.extra`` 中按出现顺序抽取全部有限数值字段。"""

    numeric: dict[str, float] = {}
    for name, raw in extra.items():
        value = parse_finite_float(raw)
        if value is not None:
            numeric[name] = value
    return numeric


@dataclass(frozen=True)
class TelemetrySample:
    """单个数值字段的一条时序采样点。

    参数:
        sequence: 来源日志条目序号。
        time_s: 相对首条有效数值日志接收时刻的秒数。
        value: 有限浮点数值。
    """

    sequence: int
    time_s: float
    value: float


class TelemetryBuffer:
    """有界遥测时序缓冲。

    参数:
        preset_fields: Preset 声明的字段名顺序；查询 ``field_names()`` 时始终排在前面。
        max_points: 单字段保留的最大采样点数（正整数）。

    异常:
        ConfigError: ``max_points`` 不是正整数。
    """

    def __init__(
        self,
        preset_fields: Sequence[str] = (),
        *,
        max_points: int = 2000,
    ) -> None:
        if isinstance(max_points, bool) or not isinstance(max_points, int) or max_points <= 0:
            raise ConfigError(f"遥测缓存点数上限必须为正整数：{max_points}")
        self._max_points = max_points
        self._preset_fields: tuple[str, ...] = ()
        self._fields: list[str] = []
        self._field_set: set[str] = set()
        self._series: dict[str, deque[TelemetrySample]] = {}
        self._origin_time: float | None = None
        self.reset(preset_fields)

    def field_names(self) -> tuple[str, ...]:
        """返回有序且去重的全部字段名（Preset 字段优先，后跟运行期发现字段）。"""

        return tuple(self._fields)

    def samples(self, field: str) -> tuple[TelemetrySample, ...]:
        """返回指定字段当前保留的采样点元组；未知字段返回空元组。"""

        dq = self._series.get(field)
        return tuple(dq) if dq is not None else ()

    def clear_samples(self) -> None:
        """清空全部采样点并重置时间基准，保留当前已登记的字段列表。"""

        for dq in self._series.values():
            dq.clear()
        self._origin_time = None

    def reset(self, preset_fields: Sequence[str] | None = None) -> None:
        """清空采样点并恢复字段列表至 Preset 预设字段（可选更新 Preset 字段定义）。"""

        if preset_fields is not None:
            deduped: list[str] = []
            seen: set[str] = set()
            for name in preset_fields:
                if name and name not in seen:
                    seen.add(name)
                    deduped.append(name)
            self._preset_fields = tuple(deduped)

        self._fields = list(self._preset_fields)
        self._field_set = set(self._fields)
        self._series = {name: deque(maxlen=self._max_points) for name in self._fields}
        self._origin_time = None

    def apply_update(self, update: PipelineUpdate) -> bool:
        """同步流水线增量（先移除淘汰序号，再追加新增有效数值），返回数据或字段集是否变化。"""

        changed = False
        if update.dropped_sequences:
            dropped = set(update.dropped_sequences)
            for field_name, dq in self._series.items():
                if not dq:
                    continue
                before = len(dq)
                while dq and dq[0].sequence in dropped:
                    dq.popleft()
                if any(sample.sequence in dropped for sample in dq):
                    self._series[field_name] = deque(
                        (sample for sample in dq if sample.sequence not in dropped),
                        maxlen=self._max_points,
                    )
                if len(self._series[field_name]) != before:
                    changed = True

        for entry in update.added:
            numeric = extract_numeric_extra(entry.extra)
            if not numeric:
                continue
            if self._origin_time is None:
                self._origin_time = entry.received_at
            time_s = entry.received_at - self._origin_time
            for field_name, value in numeric.items():
                if field_name not in self._field_set:
                    self._field_set.add(field_name)
                    self._fields.append(field_name)
                    self._series[field_name] = deque(maxlen=self._max_points)
                self._series[field_name].append(
                    TelemetrySample(sequence=entry.sequence, time_s=time_s, value=value)
                )
            changed = True

        return changed
