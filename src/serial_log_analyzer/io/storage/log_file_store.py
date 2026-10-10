"""日志导入 / 导出。

v1 仅支持手动导入与导出：导出把当前表格内容写入文本文件，导入把文本文件按当前
Preset 解析后追加到日志流水线。不实现自动录制与 Session 概念。
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TextIO

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.core.models.logs import LogEntry

__all__ = ["ExportFormat", "LogFileStore"]

_CSV_HEADER = ("sequence", "received_at", "level", "module", "device_time", "message", "extra")
_IMPORT_STEP_SECONDS = 0.001
_DEFAULT_STEM = "serial-log"


class ExportFormat(StrEnum):
    """日志导出格式。"""

    TEXT = "text"
    CSV = "csv"
    JSONL = "jsonl"

    @property
    def suffix(self) -> str:
        """该格式的建议文件扩展名。"""
        return {ExportFormat.TEXT: ".log", ExportFormat.CSV: ".csv", ExportFormat.JSONL: ".jsonl"}[
            self
        ]

    @property
    def display_name(self) -> str:
        """界面上展示的中文名称。"""
        return {
            ExportFormat.TEXT: "文本（设备原始行）",
            ExportFormat.CSV: "CSV 表格",
            ExportFormat.JSONL: "JSON Lines",
        }[self]


def _safe_stem(stem: str) -> str:
    """把用户提供的文件名主干清洗为安全的 ASCII 形式。"""
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", str(stem).strip()).strip("-")
    return cleaned or _DEFAULT_STEM


def _extra_text(extra: dict[str, str]) -> str:
    """把 ``extra`` 渲染为紧凑 JSON，便于在 CSV 单元格中往返。"""
    if not extra:
        return ""
    return json.dumps(extra, ensure_ascii=False, sort_keys=True)


class LogFileStore:
    """日志文件的读写。

    参数:
        default_dir: 默认导出目录，由调用方传入（``core`` 不感知用户目录规则）。
    """

    def __init__(self, default_dir: Path) -> None:
        self._default_dir = Path(default_dir)

    @property
    def default_dir(self) -> Path:
        """默认导出目录。"""
        return self._default_dir

    def suggested_path(self, stem: str = _DEFAULT_STEM, *, fmt: ExportFormat = ExportFormat.TEXT) -> Path:
        """返回默认目录下带时间戳的建议文件名（不创建文件）。

        参数:
            stem: 文件名主干，非法字符会被替换为 ``-``。
            fmt: 导出格式，决定扩展名。
        """
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return self._default_dir / f"{_safe_stem(stem)}-{stamp}{fmt.suffix}"

    def export_entries(
        self,
        entries: Sequence[LogEntry],
        path: Path,
        *,
        fmt: ExportFormat = ExportFormat.TEXT,
    ) -> int:
        """把条目导出到文件。

        参数:
            entries: 待导出的条目，按流水线顺序排列。
            path: 目标文件路径；父目录不存在时会自动创建。
            fmt: 导出格式，默认文本（每行保留 ``raw``，便于与设备日志逐行对照）。

        返回:
            写入量：``TEXT`` 返回物理行数（多行原文会占多行），``CSV`` / ``JSONL``
            返回记录数。

        异常:
            AppError: 路径不可写。
        """
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="") as handle:
                if fmt is ExportFormat.CSV:
                    return self._write_csv(handle, entries)
                if fmt is ExportFormat.JSONL:
                    return self._write_jsonl(handle, entries)
                return self._write_text(handle, entries)
        except OSError as exc:
            raise AppError(f"导出日志失败：{target}（{exc}）") from exc

    def import_entries(
        self,
        path: Path,
        on_line: Callable[[str, float], None],
    ) -> int:
        """读取文本文件并逐行回调（时间戳按导入顺序递增模拟）。

        参数:
            path: 源文件路径。
            on_line: ``(文本, received_at)`` 回调，通常直接喂给 ``DeviceSession`` 的
                解析路径，以复用同一套 Preset 解析逻辑。空行会被跳过。

        返回:
            读取并回调的行数。

        异常:
            AppError: 文件不存在或不可读。
        """
        source = Path(path)
        if not source.is_file():
            raise AppError(f"日志文件不存在：{source}")
        base = time.time()
        count = 0
        try:
            with source.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    text = line.rstrip("\r\n")
                    if not text.strip():
                        continue
                    on_line(text, base + count * _IMPORT_STEP_SECONDS)
                    count += 1
        except OSError as exc:
            raise AppError(f"读取日志文件失败：{source}（{exc}）") from exc
        return count

    @staticmethod
    def _write_text(handle: TextIO, entries: Sequence[LogEntry]) -> int:
        """写入设备原始行，返回物理行数。"""
        lines = 0
        for entry in entries:
            text = entry.raw.rstrip("\r\n")
            handle.write(f"{text}\n")
            lines += text.count("\n") + 1
        return lines

    @staticmethod
    def _write_csv(handle: TextIO, entries: Sequence[LogEntry]) -> int:
        """写入 CSV 表格，返回记录数。"""
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(_CSV_HEADER)
        count = 0
        for entry in entries:
            writer.writerow(
                [
                    entry.sequence,
                    f"{entry.received_at:.6f}",
                    entry.level.name,
                    entry.module or "",
                    entry.device_time or "",
                    entry.message,
                    _extra_text(entry.extra),
                ]
            )
            count += 1
        return count

    @staticmethod
    def _write_jsonl(handle: TextIO, entries: Sequence[LogEntry]) -> int:
        """写入 JSON Lines，每行一个条目对象，返回记录数。"""
        count = 0
        for entry in entries:
            payload = {
                "sequence": entry.sequence,
                "received_at": round(entry.received_at, 6),
                "level": entry.level.name,
                "module": entry.module,
                "device_time": entry.device_time,
                "continuation": entry.continuation,
                "message": entry.message,
                "extra": entry.extra,
                "raw": entry.raw,
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            count += 1
        return count
