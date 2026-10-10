"""诊断报告：汇总版本、路径、资源加载结果与配置错误，供“一键复制”与缺陷提交。

职责：
    纯 Python 实现，依赖全部由调用方注入（``ResourceLoader`` 与可选的外部探测结果），
    不 import 任何 Qt 相关模块，因此可在无图形环境下运行，也可作为 CI 的资源校验入口。

异常：
    :func:`collect` 不抛异常，加载失败的信息会逐条收集到 ``config_errors``；
    :func:`export` 写文件失败时抛 ``AppError``。
"""

from __future__ import annotations

import json
import platform
import sys
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from serial_log_analyzer import __version__
from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.llm.adapter_loader import load_adapters
from serial_log_analyzer.core.llm.profile_loader import load_profiles
from serial_log_analyzer.core.logs.preset import LogPreset
from serial_log_analyzer.core.logs.preset_loader import load_presets
from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["DiagnosticsReport", "collect", "export"]


@dataclass(frozen=True)
class DiagnosticsReport:
    """一次诊断快照；所有字段都是可直接展示的字符串或布尔量。

    参数：
        app_version: 应用版本号。
        python_version: Python 解释器版本。
        executable: 解释器可执行文件路径。
        platform: 操作系统描述。
        config_dir: 用户配置根目录。
        log_file: 应用日志文件路径（未启用时为空串）。
        resource_roots: 参与查找的资源根目录，按优先级排列。
        presets: 已加载的 Preset 摘要。
        adapters: 已加载的 Adapter 摘要。
        profiles: 已加载的 Provider Profile 摘要。
        config_errors: 配置/资源加载错误（逐条中文描述）。
        keyring_available: 系统钥匙串可用性；未探测时为 ``None``。
        log_tail: 应用日志末尾若干行。
    """

    app_version: str
    python_version: str
    executable: str
    platform: str
    config_dir: str
    log_file: str
    resource_roots: tuple[str, ...]
    presets: tuple[str, ...] = ()
    adapters: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    config_errors: tuple[str, ...] = ()
    keyring_available: bool | None = None
    log_tail: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """配置是否全部加载成功（无 ``config_errors``）。"""
        return not self.config_errors

    def to_dict(self) -> dict[str, Any]:
        """返回适合 JSON 序列化的字典。"""
        return {
            "app_version": self.app_version,
            "python_version": self.python_version,
            "executable": self.executable,
            "platform": self.platform,
            "config_dir": self.config_dir,
            "log_file": self.log_file or None,
            "resource_roots": list(self.resource_roots),
            "presets": list(self.presets),
            "adapters": list(self.adapters),
            "profiles": list(self.profiles),
            "config_errors": list(self.config_errors),
            "keyring_available": self.keyring_available,
            "log_tail": list(self.log_tail),
        }

    def render(self) -> str:
        """渲染为可直接粘贴到 issue 的中文文本报告。"""
        lines = [
            "SerialLogAnalyzer 诊断报告",
            "=" * 40,
            f"生成时间    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"应用版本    : {self.app_version}",
            f"Python      : {self.python_version}",
            f"可执行文件  : {self.executable}",
            f"操作系统    : {self.platform}",
            f"配置目录    : {self.config_dir}",
            f"日志文件    : {self.log_file or '（未启用文件日志）'}",
            f"系统钥匙串  : {_keyring_text(self.keyring_available)}",
            "资源根目录  :",
        ]
        lines.extend(f"  - {root}" for root in self.resource_roots)
        lines.extend(_section("Preset", self.presets))
        lines.extend(_section("Adapter", self.adapters))
        lines.extend(_section("Profile", self.profiles))
        if self.config_errors:
            lines.append(f"配置错误（{len(self.config_errors)}）：")
            lines.extend(f"  - {item}" for item in self.config_errors)
        else:
            lines.append("配置错误    : 无")
        if self.log_tail:
            lines.append(f"日志末尾（{len(self.log_tail)} 行）:")
            lines.extend(f"  {line}" for line in self.log_tail)
        return "\n".join(lines)


def _keyring_text(available: bool | None) -> str:
    """把钥匙串可用性渲染为中文文本。"""
    if available is None:
        return "未探测"
    return "可用" if available else "不可用（将回退环境变量）"


def _section(title: str, items: tuple[str, ...]) -> list[str]:
    """渲染一个“资源清单”小节。"""
    if not items:
        return [f"{title}      : 无"]
    lines = [f"{title}（{len(items)}）:"]
    lines.extend(f"  - {item}" for item in items)
    return lines


def _preset_label(preset: LogPreset) -> str:
    """把 Preset 渲染成 ``id（展示名）``。"""
    return f"{preset.preset_id}（{preset.display_name}）"


def _read_log_tail(log_file: Path | None, line_count: int) -> tuple[str, ...]:
    """读取日志文件末尾若干行，失败时返回空元组（诊断本身不应因此失败）。"""
    if log_file is None or line_count <= 0 or not log_file.is_file():
        return ()
    try:
        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            tail = deque((line.rstrip("\n") for line in handle), maxlen=line_count)
    except OSError:
        return ()
    return tuple(tail)


def collect(
    loader: ResourceLoader,
    *,
    keyring_available: bool | None = None,
    log_file: Path | str | None = None,
    resource_roots: Sequence[Path | str] | None = None,
    log_tail_lines: int = 20,
    config_dir: Path | str | None = None,
) -> DiagnosticsReport:
    """采集一次诊断快照。

    加载 Preset / Adapter / Profile 时的失败会被记录进 ``config_errors`` 而不向外抛出，
    这样即使配置损坏，用户依然能拿到一份可粘贴的诊断报告。

    参数：
        loader: 资源加载器（通常为 ``CompositeResourceLoader``）。
        keyring_available: 钥匙串探测结果；``None`` 表示未探测。
        log_file: 应用日志文件路径。
        resource_roots: 资源根目录；为 ``None`` 时尝试读取 ``loader.roots``。
        log_tail_lines: 日志末尾采集行数。
        config_dir: 用户配置目录；为 ``None`` 时按运行环境推断。

    返回：
        :class:`DiagnosticsReport`。
    """
    errors: list[str] = []

    presets: tuple[str, ...] = ()
    try:
        presets = tuple(_preset_label(item) for item in load_presets(loader))
    except AppError as exc:
        errors.append(f"Preset：{exc}")

    adapters: tuple[str, ...] = ()
    try:
        adapters = tuple(item.adapter_id for item in load_adapters(loader))
    except AppError as exc:
        errors.append(f"Adapter：{exc}")

    profiles: tuple[str, ...] = ()
    try:
        profiles = tuple(f"{item.profile_id}（{item.model}）" for item in load_profiles(loader))
    except AppError as exc:
        errors.append(f"Profile：{exc}")

    if resource_roots is None:
        detected = getattr(loader, "roots", ())
        resource_roots = list(detected)
    if config_dir is None:
        from serial_log_analyzer.io.paths import user_config_dir

        config_dir = user_config_dir()

    log_path = Path(log_file) if log_file is not None else None
    return DiagnosticsReport(
        app_version=__version__,
        python_version=platform.python_version(),
        executable=sys.executable or "（未知）",
        platform=platform.platform(),
        config_dir=str(config_dir),
        log_file=str(log_path) if log_path is not None else "",
        resource_roots=tuple(str(root) for root in resource_roots),
        presets=presets,
        adapters=adapters,
        profiles=profiles,
        config_errors=tuple(errors),
        keyring_available=keyring_available,
        log_tail=_read_log_tail(log_path, log_tail_lines),
    )


def export(report: DiagnosticsReport, path: Path | str) -> Path:
    """把诊断报告写入文本文件。

    参数：
        report: 要导出的报告。
        path: 目标文件路径；若传入已存在的目录，则自动在其中生成带时间戳的文件名。

    返回：
        实际写入的文件路径。

    异常：
        AppError: 目标不可写（权限、路径非法、磁盘错误等）。
    """
    target = Path(path)
    if target.is_dir():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = target / f"diagnostics-{stamp}.txt"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report.render() + "\n", encoding="utf-8")
    except OSError as exc:
        raise AppError(f"诊断报告写入失败：{target}（{exc}）") from exc
    return target


def to_json(report: DiagnosticsReport) -> str:
    """把诊断报告序列化为 JSON 文本（``--json`` 输出用）。"""
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
