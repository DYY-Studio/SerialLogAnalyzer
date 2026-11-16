"""异常规则 YAML 加载与严格校验。

资源位于 ``rules/anomalies/*.yaml``，经 :class:`ResourceLoader` 加载，
支持用户配置目录覆盖内置规则。严格校验 ``schema_version`` 与全部字段，
出现未知字段、非法正则或空匹配条件时直接抛出 :class:`ConfigError`。
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import yaml

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.models.anomaly import (
    AnomalyRule,
    AnomalyRuleSet,
    AnomalySeverity,
    FieldThreshold,
    ThresholdOp,
)
from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["load_rule_set", "load_rule_sets"]

_BUILTIN_DIR = "rules/anomalies"
_SCHEMA_VERSION = 1
_MAX_PATTERN_LENGTH = 256
_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")

_TOP_LEVEL_FIELDS = {"schema_version", "rule_set_id", "display_name", "defaults", "rules"}
_DEFAULT_FIELDS = {"window_seconds", "cooldown_seconds", "max_evidence"}
_RULE_FIELDS = {
    "rule_id",
    "category",
    "severity",
    "enabled",
    "modules",
    "min_level",
    "keywords",
    "pattern",
    "thresholds",
    "immediate_alert",
    "min_occurrences",
    "window_seconds",
    "cooldown_seconds",
}
_THRESHOLD_FIELDS = {"field", "op", "value"}

_DEFAULT_WINDOW_SECONDS = 60.0
_DEFAULT_COOLDOWN_SECONDS = 60.0
_DEFAULT_MAX_EVIDENCE = 20


def load_rule_set(loader: ResourceLoader, rule_set_id: str) -> AnomalyRuleSet:
    """按 ID 加载单个异常规则集。

    参数:
        loader: 资源加载器（用户目录优先于内置目录）。
        rule_set_id: 规则集标识，需满足 ``^[a-z][a-z0-9-]*$``。

    返回:
        已校验并编译的 :class:`AnomalyRuleSet`。

    异常:
        ConfigError: 文件缺失、YAML 非法、未知字段或规则参数不合法。
    """

    if not _ID_RE.match(rule_set_id):
        raise ConfigError(f"非法 rule_set_id：{rule_set_id}")

    path = f"{_BUILTIN_DIR}/{rule_set_id}.yaml"
    try:
        text = loader.read_text(path)
    except ConfigError as exc:
        raise ConfigError(f"未找到异常规则集：{rule_set_id}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"异常规则 YAML 非法：{rule_set_id}（{path}）") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"异常规则顶层必须是对象：{rule_set_id}（{path}）")

    return _validate_rule_set(rule_set_id, data, path)


def load_rule_sets(loader: ResourceLoader) -> list[AnomalyRuleSet]:
    """加载全部可用异常规则集（用户目录覆盖同 ID 内置文件）。

    返回:
        按 ``rule_set_id`` 升序排列的列表；目录为空时返回空列表。
    """

    paths = loader.list_files(_BUILTIN_DIR, "*.yaml")
    ids: dict[str, str] = {}
    for path in paths:
        ids.setdefault(Path(path).stem, path)

    rule_sets = [load_rule_set(loader, rule_set_id) for rule_set_id in ids]
    rule_sets.sort(key=lambda item: item.rule_set_id)
    return rule_sets


def _validate_rule_set(
    expected_id: str, data: dict[str, Any], source_path: str
) -> AnomalyRuleSet:
    unknown = set(data) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ConfigError(f"异常规则集未知顶层字段：{sorted(unknown)}（{source_path}）")
    if data.get("schema_version") != _SCHEMA_VERSION:
        raise ConfigError(f"schema_version 必须为 {_SCHEMA_VERSION}（{source_path}）")

    declared_id = _require_str(data, "rule_set_id", source_path)
    if not _ID_RE.match(declared_id):
        raise ConfigError(f"非法 rule_set_id：{declared_id}（{source_path}）")
    if declared_id != expected_id:
        raise ConfigError(
            f"rule_set_id（{declared_id}）必须与文件名（{expected_id}）一致（{source_path}）"
        )

    display_name = _require_str(data, "display_name", source_path)
    default_window, default_cooldown, max_evidence = _parse_defaults(
        data.get("defaults"), source_path
    )

    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ConfigError(f"rules 必须是非空列表（{source_path}）")

    rules: list[AnomalyRule] = []
    seen_ids: set[str] = set()
    for index, raw_rule in enumerate(raw_rules):
        rule = _parse_rule(
            raw_rule,
            index=index,
            default_window=default_window,
            default_cooldown=default_cooldown,
            source_path=source_path,
        )
        if rule.rule_id in seen_ids:
            raise ConfigError(f"rule_id 重复：{rule.rule_id}（{source_path}）")
        seen_ids.add(rule.rule_id)
        rules.append(rule)

    return AnomalyRuleSet(
        rule_set_id=declared_id,
        display_name=display_name,
        rules=tuple(rules),
        window_seconds=default_window,
        cooldown_seconds=default_cooldown,
        max_evidence=max_evidence,
        schema_version=_SCHEMA_VERSION,
        source_path=source_path,
    )


def _parse_defaults(raw: Any, source_path: str) -> tuple[float, float, int]:
    if raw is None:
        return _DEFAULT_WINDOW_SECONDS, _DEFAULT_COOLDOWN_SECONDS, _DEFAULT_MAX_EVIDENCE
    if not isinstance(raw, dict):
        raise ConfigError(f"defaults 必须是对象（{source_path}）")
    unknown = set(raw) - _DEFAULT_FIELDS
    if unknown:
        raise ConfigError(f"defaults 未知字段：{sorted(unknown)}（{source_path}）")

    window = _parse_positive_number(
        raw.get("window_seconds", _DEFAULT_WINDOW_SECONDS), "defaults.window_seconds", source_path
    )
    cooldown = _parse_non_negative_number(
        raw.get("cooldown_seconds", _DEFAULT_COOLDOWN_SECONDS),
        "defaults.cooldown_seconds",
        source_path,
    )
    max_evidence = _parse_positive_int(
        raw.get("max_evidence", _DEFAULT_MAX_EVIDENCE), "defaults.max_evidence", source_path
    )
    return window, cooldown, max_evidence


def _parse_rule(
    raw: Any,
    *,
    index: int,
    default_window: float,
    default_cooldown: float,
    source_path: str,
) -> AnomalyRule:
    loc = f"rules[{index}]（{source_path}）"
    if not isinstance(raw, dict):
        raise ConfigError(f"{loc} 必须是对象")
    unknown = set(raw) - _RULE_FIELDS
    if unknown:
        raise ConfigError(f"{loc} 出现未知字段：{sorted(unknown)}")

    rule_id = _require_str(raw, "rule_id", source_path)
    if not _ID_RE.match(rule_id):
        raise ConfigError(f"非法 rule_id：{rule_id}（{source_path}）")
    category = _require_str(raw, "category", source_path)
    severity = _parse_severity(raw.get("severity"), loc)
    enabled = _parse_bool(raw.get("enabled", True), f"{loc}.enabled")
    modules = _parse_str_tuple(raw.get("modules"), f"{loc}.modules", lower=True)
    min_level = _parse_log_level(raw.get("min_level", "WARN"), f"{loc}.min_level")
    keywords = _parse_str_tuple(raw.get("keywords"), f"{loc}.keywords", lower=True)
    pattern = _parse_pattern(raw.get("pattern"), f"{loc}.pattern")
    thresholds = _parse_thresholds(raw.get("thresholds"), f"{loc}.thresholds")

    if not keywords and pattern is None and not thresholds:
        raise ConfigError(
            f"规则 {rule_id} 必须至少声明非空 keywords、pattern 或 thresholds 之一（{source_path}）"
        )

    immediate_alert = _parse_bool(raw.get("immediate_alert", False), f"{loc}.immediate_alert")
    min_occurrences = _parse_positive_int(
        raw.get("min_occurrences", 1), f"{loc}.min_occurrences", source_path
    )
    window = _parse_positive_number(
        raw.get("window_seconds", default_window), f"{loc}.window_seconds", source_path
    )
    cooldown = _parse_non_negative_number(
        raw.get("cooldown_seconds", default_cooldown), f"{loc}.cooldown_seconds", source_path
    )

    return AnomalyRule(
        rule_id=rule_id,
        category=category,
        severity=severity,
        keywords=keywords,
        pattern=pattern,
        modules=modules,
        min_level=min_level,
        immediate_alert=immediate_alert,
        min_occurrences=min_occurrences,
        window_seconds=window,
        cooldown_seconds=cooldown,
        enabled=enabled,
        thresholds=thresholds,
    )


def _require_str(data: dict[str, Any], field: str, source_path: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} 必须是非空字符串（{source_path}）")
    return value.strip()


def _parse_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field} 必须是布尔值")
    return value


def _parse_positive_int(value: Any, field: str, source_path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{field} 必须是正整数（{source_path}）")
    return value


def _parse_positive_number(value: Any, field: str, source_path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{field} 必须是大于 0 的数字（{source_path}）")
    return float(value)


def _parse_non_negative_number(value: Any, field: str, source_path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ConfigError(f"{field} 必须是非负数字（{source_path}）")
    return float(value)


def _parse_severity(raw: Any, loc: str) -> AnomalySeverity:
    if not isinstance(raw, str):
        raise ConfigError(f"{loc}.severity 必须是字符串")
    try:
        return AnomalySeverity[raw]
    except KeyError as exc:
        raise ConfigError(f"{loc}.severity 未知：{raw}") from exc


def _parse_log_level(raw: Any, field: str) -> LogLevel:
    if not isinstance(raw, str):
        raise ConfigError(f"{field} 必须是字符串")
    try:
        return LogLevel[raw]
    except KeyError as exc:
        raise ConfigError(f"{field} 未知日志级别：{raw}") from exc


def _parse_str_tuple(raw: Any, field: str, *, lower: bool = False) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{field} 必须是字符串列表")
    items: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{field} 的元素必须是非空字符串")
        text = item.strip()
        items.append(text.lower() if lower else text)
    return tuple(items)


def _parse_pattern(raw: Any, field: str) -> re.Pattern[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        raise ConfigError(f"{field} 必须是非空正则字符串")
    if len(raw) > _MAX_PATTERN_LENGTH:
        raise ConfigError(f"{field} 长度超过限制（最多 {_MAX_PATTERN_LENGTH} 字符）")
    try:
        return re.compile(raw, re.IGNORECASE)
    except re.error as exc:
        raise ConfigError(f"{field} 正则非法：{exc}") from exc


def _parse_finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{field} 必须是有限实数（禁止 bool/NaN/Inf）")
    return float(value)


def _parse_thresholds(raw: Any, field: str) -> tuple[FieldThreshold, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{field} 必须是阈值对象列表")
    items: list[FieldThreshold] = []
    for index, item in enumerate(raw):
        item_loc = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{item_loc} 必须是对象")
        unknown = set(item) - _THRESHOLD_FIELDS
        if unknown:
            raise ConfigError(f"{item_loc} 出现未知字段：{sorted(unknown)}")
        missing = _THRESHOLD_FIELDS - set(item)
        if missing:
            raise ConfigError(f"{item_loc} 缺少必填字段：{sorted(missing)}")

        raw_name = item["field"]
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ConfigError(f"{item_loc}.field 必须是非空字符串")

        raw_op = item["op"]
        if not isinstance(raw_op, str):
            raise ConfigError(f"{item_loc}.op 必须是字符串")
        try:
            op = ThresholdOp(raw_op)
        except ValueError as exc:
            raise ConfigError(
                f"{item_loc}.op 未知（支持 gt/gte/lt/lte/eq/ne）：{raw_op}"
            ) from exc

        value = _parse_finite_number(item["value"], f"{item_loc}.value")
        items.append(FieldThreshold(field=raw_name.strip(), op=op, value=value))
    return tuple(items)
