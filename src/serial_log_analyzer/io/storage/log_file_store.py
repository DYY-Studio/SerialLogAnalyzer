"""日志导入 / 导出。

v1 仅支持手动导入与导出：导出把当前表格内容写入文本文件，导入把文本文件按当前
Preset 解析后追加到日志流水线。不实现自动录制与 Session 概念。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from serial_log_analyzer.core.models.logs import LogEntry

__all__ = ["LogFileStore"]


class LogFileStore:
    """日志文件的读写。

    参数:
        default_dir: 默认导出目录，由调用方传入（``core`` 不感知用户目录规则）。
    """

    def __init__(self, default_dir: Path) -> None:
        raise NotImplementedError

    def export_entries(self, entries: list[LogEntry], path: Path) -> int:
        """把条目导出为文本文件。

        每行保留原始文本（``raw``），以便与设备侧日志逐行对照。

        参数:
            entries: 待导出的条目。
            path: 目标文件路径。

        返回:
            写入的行数。

        异常:
            AppError: 路径不可写。
        """

        raise NotImplementedError

    def import_entries(
        self,
        path: Path,
        on_line: Callable[[str, float], None],
    ) -> int:
        """读取文本文件并逐行回调（时间戳按导入顺序递增模拟）。

        参数:
            path: 源文件路径。
            on_line: ``(文本, received_at)`` 回调，通常直接喂给 ``DeviceSession`` 的
                解析路径，以复用同一套 Preset 解析逻辑。

        返回:
            读取的行数。

        异常:
            AppError: 文件不存在或不可读。
        """

        raise NotImplementedError
