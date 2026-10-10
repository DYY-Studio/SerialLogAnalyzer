"""应用自身日志配置（与设备日志严格分离）。

设备日志进入 :class:`LogPipeline` 与表格；本模块只处理工具自身的诊断日志，
统一使用标准库 ``logging``，默认输出到 stderr，可通过 ``SLA_LOG_LEVEL`` 调整级别。
"""

from __future__ import annotations

import logging
from pathlib import Path

__all__ = ["configure_logging", "get_logger"]

_LOGGER_NAME = "serial_log_analyzer"


def configure_logging(
    *,
    level: str = "INFO",
    log_file: Path | None = None,
) -> None:
    """配置根日志器。

    参数:
        level: 日志级别名称（``DEBUG`` / ``INFO`` / ``WARNING`` / ``ERROR``）。
        log_file: 可选日志文件路径；为 ``None`` 时仅输出到 stderr。
    """

    raise NotImplementedError


def get_logger(name: str) -> logging.Logger:
    """获取带统一前缀的子日志器。

    参数:
        name: 模块名，通常是 ``__name__``。
    """

    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
