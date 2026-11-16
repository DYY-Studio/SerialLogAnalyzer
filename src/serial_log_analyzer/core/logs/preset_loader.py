"""日志 Preset 加载与校验。

负责读取 YAML 声明、校验字段、编译正则并构造 :class:`LogPreset`。
资源路径规则：
- 内置资源位于仓库 / 包内 ``presets/logs/``；
- 用户资源位于用户配置目录下的 ``presets/logs/``；
- 同 ``preset_id`` 时用户资源覆盖内置资源。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from serial_log_analyzer.core.errors import ConfigError, PresetError
from serial_log_analyzer.core.logs.preset import (
    ContinuationMode,
    FallbackRule,
    LogPreset,
    PresetCommand,
    PresetCommandMode,
    PresetLineRule,
)
from serial_log_analyzer.core.models.logs import LogLevel
from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["load_preset", "load_presets"]

_BUILTIN_DIR = "presets/logs"

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "preset_id",
    "display_name",
    "line",
    "fallback",
    "commands",
}
_LINE_FIELDS = {"pattern", "level_map", "continuation_pattern", "fields"}
_FALLBACK_FIELDS = {"enabled", "level"}
_COMMAND_FIELDS = {"label", "command", "mode", "tooltip"}
_PRESET_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def load_preset(loader: ResourceLoader, preset_id: str) -> LogPreset:
    """按 ID 加载单个 Preset。

    参数:
        loader: 资源加载器，按优先级实现内置与用户资源的查找。
        preset_id: Preset 标识，需满足 ``[a-z][a-z0-9-]*``。

    返回:
        校验完成的 :class:`LogPreset`。

    异常:
        PresetError: 文件缺失、YAML 非法、字段不合法或正则编译失败。
    """

    if not _PRESET_ID_RE.match(preset_id):
        raise PresetError(f"非法 preset_id：{preset_id}")

    path = f"{_BUILTIN_DIR}/{preset_id}.yaml"
    try:
        text = loader.read_text(path)
    except ConfigError as exc:
        raise PresetError(f"未找到 Preset：{preset_id}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PresetError(f"Preset YAML 非法：{preset_id}") from exc
    if not isinstance(data, dict):
        raise PresetError(f"Preset 顶层必须是对象：{preset_id}")

    return _validate_and_build(preset_id, data, path)


def load_presets(loader: ResourceLoader) -> list[LogPreset]:
    """加载全部可用 Preset（内置 + 用户，按 ID 去重，用户优先）。

    返回:
        已校验的 Preset 列表，按 ``display_name`` 排序。
    """

    paths = loader.list_files(_BUILTIN_DIR, "*.yaml")
    ids: dict[str, str] = {}
    for path in paths:
        ids.setdefault(Path(path).stem, path)

    presets = [load_preset(loader, preset_id) for preset_id in ids]
    presets.sort(key=lambda preset: preset.display_name)
    return presets


def _validate_and_build(
    preset_id: str, data: dict[str, object], source_path: str
) -> LogPreset:
    """校验 YAML 结构并构造 :class:`LogPreset`。

    异常:
        PresetError: 缺少必填字段、字段类型错误或正则编译失败。
    """

    unknown = set(data) - _TOP_LEVEL_FIELDS
    if unknown:
        raise PresetError(f"未知顶层字段：{sorted(unknown)}")
    if data.get("schema_version") != 1:
        raise PresetError("schema_version 必须为 1")

    declared_id = data.get("preset_id")
    if not isinstance(declared_id, str) or not _PRESET_ID_RE.match(declared_id):
        raise PresetError("preset_id 非法")
    if declared_id != preset_id:
        raise PresetError(f"preset_id 与文件名不一致：声明 {declared_id!r}，请求 {preset_id!r}")

    display_name = data.get("display_name")
    if not isinstance(display_name, str) or not display_name:
        raise PresetError("display_name 必填且为非空字符串")

    line_data = data.get("line")
    if not isinstance(line_data, dict):
        raise PresetError("line 必填")
    unknown_line = set(line_data) - _LINE_FIELDS
    if unknown_line:
        raise PresetError(f"line 出现未知字段：{sorted(unknown_line)}")

    pattern_text = line_data.get("pattern")
    if not isinstance(pattern_text, str):
        raise PresetError("line.pattern 必填")
    pattern = _compile_pattern(pattern_text, required_groups=("level", "module", "message"))
    level_map = _parse_level_map(line_data.get("level_map"))
    time_group = "time" if "time" in pattern.groupindex else None

    continuation_pattern = None
    raw_continuation = line_data.get("continuation_pattern")
    if raw_continuation is not None:
        if not isinstance(raw_continuation, str):
            raise PresetError("continuation_pattern 必须是字符串")
        continuation_pattern = _compile_regex(raw_continuation)
    continuation_mode = (
        ContinuationMode.MERGE_PREVIOUS
        if continuation_pattern is not None
        else ContinuationMode.NONE
    )
    fields = _parse_fields(line_data.get("fields"))

    line_rule = PresetLineRule(
        pattern=pattern,
        time_group=time_group,
        level_map=level_map,
        continuation_mode=continuation_mode,
        continuation_pattern=continuation_pattern,
        fields=fields,
    )

    fallback = FallbackRule()
    fallback_data = data.get("fallback")
    if fallback_data is not None:
        if not isinstance(fallback_data, dict):
            raise PresetError("fallback 必须是对象")
        unknown_fallback = set(fallback_data) - _FALLBACK_FIELDS
        if unknown_fallback:
            raise PresetError(f"fallback 出现未知字段：{sorted(unknown_fallback)}")
        enabled = fallback_data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise PresetError("fallback.enabled 必须是布尔值")
        fallback = FallbackRule(
            enabled=enabled,
            level=_level_from_name(fallback_data.get("level", "UNKNOWN")),
        )

    commands = _parse_commands(data.get("commands"))

    return LogPreset(
        preset_id=declared_id,
        display_name=display_name,
        line=line_rule,
        fallback=fallback,
        source_path=source_path,
        commands=commands,
    )


def _compile_pattern(pattern: str, *, required_groups: tuple[str, ...]) -> re.Pattern[str]:
    """编译正则并校验必需命名组是否存在。

    异常:
        PresetError: 正则非法或缺少必需命名组。
    """

    compiled = _compile_regex(pattern)
    missing = [group for group in required_groups if group not in compiled.groupindex]
    if missing:
        raise PresetError(f"pattern 缺少命名组：{missing}")
    return compiled


def _compile_regex(pattern: str) -> re.Pattern[str]:
    """编译正则，失败时翻译为 :class:`PresetError`。"""

    try:
        return re.compile(pattern)
    except re.error as exc:
        raise PresetError(f"正则非法：{exc}") from exc


def _parse_fields(raw: object) -> dict[str, re.Pattern[str]]:
    """解析 ``fields``：字段名 → 已编译正则。

    异常:
        PresetError: 不是对象、字段名为空或正则非法。
    """

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PresetError("fields 必须是对象")
    result: dict[str, re.Pattern[str]] = {}
    for name, pattern in raw.items():
        if not isinstance(name, str) or not name:
            raise PresetError("fields 的字段名必须是非空字符串")
        if not isinstance(pattern, str):
            raise PresetError(f"fields.{name} 必须是正则字符串")
        result[name] = _compile_regex(pattern)
    return result


def _parse_level_map(raw: object) -> dict[str, LogLevel]:
    """解析 ``level_map`` 并校验目标级别合法。

    异常:
        PresetError: 映射不是字符串到字符串的对象，或目标级别不在固定级别集内。
    """

    if not isinstance(raw, dict) or not raw:
        raise PresetError("level_map 必填且非空")
    result: dict[str, LogLevel] = {}
    for token, name in raw.items():
        if not isinstance(token, str) or not isinstance(name, str):
            raise PresetError("level_map 必须是字符串到字符串的对象")
        result[token] = _level_from_name(name)
    return result


def _level_from_name(name: object) -> LogLevel:
    """把级别名转换为 :class:`LogLevel`；未知时抛 :class:`PresetError`。"""

    if not isinstance(name, str):
        raise PresetError("级别名必须是字符串")
    try:
        return LogLevel[name]
    except KeyError as exc:
        raise PresetError(f"未知级别：{name}") from exc


def _parse_commands(raw: object) -> tuple[PresetCommand, ...]:
    """解析可选 ``commands`` 快捷命令列表并严格校验字段。

    异常:
        PresetError: 非列表、存在未知字段、字段类型错误或 ``mode`` 非法。
    """

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PresetError("commands 必须是列表")

    commands: list[PresetCommand] = []
    for index, item in enumerate(raw):
        loc = f"commands[{index}]"
        if not isinstance(item, dict):
            raise PresetError(f"{loc} 必须是对象")
        unknown = set(item) - _COMMAND_FIELDS
        if unknown:
            raise PresetError(f"{loc} 出现未知字段：{sorted(unknown)}")

        raw_label = item.get("label")
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise PresetError(f"{loc}.label 必填且为非空字符串")
        label = raw_label.strip()

        raw_mode = item.get("mode", PresetCommandMode.SEND.value)
        if not isinstance(raw_mode, str):
            raise PresetError(f"{loc}.mode 必须是字符串")
        try:
            mode = PresetCommandMode(raw_mode)
        except ValueError as exc:
            raise PresetError(f"{loc}.mode 非法：{raw_mode}") from exc

        raw_command = item.get("command")
        if not isinstance(raw_command, str) or not raw_command.strip():
            raise PresetError(f"{loc}.command 必填且为非空字符串")
        command = raw_command.strip() if mode is PresetCommandMode.SEND else raw_command.lstrip()

        raw_tooltip = item.get("tooltip", "")
        if not isinstance(raw_tooltip, str):
            raise PresetError(f"{loc}.tooltip 必须是字符串")
        tooltip = raw_tooltip.strip()

        commands.append(
            PresetCommand(
                label=label,
                command=command,
                mode=mode,
                tooltip=tooltip,
            )
        )
    return tuple(commands)
