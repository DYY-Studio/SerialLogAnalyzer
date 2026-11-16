"""结构化诊断报告文件导出（原子写入 Markdown / JSON）。"""

from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.services.report import (
    DiagnosticSummaryReport,
    render_report_markdown,
    report_to_dict,
)

__all__ = ["ReportFileStore", "ReportFormat"]

_DEFAULT_STEM = "diagnostic-report"


class ReportFormat(StrEnum):
    """诊断报告导出格式。"""

    MARKDOWN = "markdown"
    JSON = "json"

    @property
    def suffix(self) -> str:
        """该格式的建议文件扩展名。"""

        return {ReportFormat.MARKDOWN: ".md", ReportFormat.JSON: ".json"}[self]

    @property
    def display_name(self) -> str:
        """界面展示的中文名称。"""

        return {
            ReportFormat.MARKDOWN: "Markdown 诊断报告",
            ReportFormat.JSON: "JSON 结构化诊断报告",
        }[self]


def _safe_stem(stem: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", str(stem).strip()).strip("-")
    return cleaned or _DEFAULT_STEM


def _remove_quietly(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


class ReportFileStore:
    """诊断报告的原子文件写出器。

    参数:
        default_dir: 默认导出目录。
    """

    def __init__(self, default_dir: Path) -> None:
        self._default_dir = Path(default_dir)

    @property
    def default_dir(self) -> Path:
        """默认导出目录。"""

        return self._default_dir

    def suggested_path(
        self, stem: str = _DEFAULT_STEM, *, fmt: ReportFormat = ReportFormat.MARKDOWN
    ) -> Path:
        """返回默认目录下带时间戳的建议报告文件名（不创建文件）。"""

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return self._default_dir / f"{_safe_stem(stem)}-{stamp}{fmt.suffix}"

    def export_report(
        self,
        report: DiagnosticSummaryReport,
        path: Path,
        *,
        fmt: ReportFormat | None = None,
    ) -> Path:
        """将结构化诊断报告以 UTF-8 原子写入目标路径。

        参数:
            report: 由 :func:`build_diagnostic_report` 生成的报告 DTO。
            path: 目标文件路径；父目录缺失时自动创建。
            fmt: 导出格式；``None`` 时按 ``path`` 后缀推断（``.json`` → JSON，其余 → Markdown）。

        返回:
            实际写入的文件路径。

        异常:
            ConfigError: 指定了不支持的 ``fmt``。
            AppError: 目录创建或磁盘写入失败。
        """

        target = Path(path)
        resolved_fmt = self._resolve_format(target, fmt)
        if resolved_fmt is ReportFormat.JSON:
            content = json.dumps(report_to_dict(report), ensure_ascii=False, indent=2) + "\n"
        else:
            content = render_report_markdown(report)

        tmp_path = target.with_name(f"{target.name}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(content, encoding="utf-8", newline="\n")
            os.replace(tmp_path, target)
        except OSError as exc:
            _remove_quietly(tmp_path)
            raise AppError(f"导出诊断报告失败：{target}（{exc.strerror or exc}）") from exc
        return target

    @staticmethod
    def _resolve_format(path: Path, fmt: ReportFormat | None) -> ReportFormat:
        if fmt is None:
            return ReportFormat.JSON if path.suffix.lower() == ".json" else ReportFormat.MARKDOWN
        if not isinstance(fmt, ReportFormat):
            raise ConfigError(f"不支持的报告导出格式：{fmt}")
        return fmt
