"""应用日志：标准库 ``logging`` 的集中配置（本仓库唯一允许写文件日志的模块）。

职责：
    配置名为 ``serial_log_analyzer`` 的 logger（stderr + 可选轮转文件），由 ``bootstrap``
    在启动时调用一次；其余模块通过 :func:`get_logger` 获取子 logger。
    设备日志（``core/logs`` 的解析结果）与应用日志严格分离，不共用这套 handler。

环境变量：
    ``SLA_LOG_LEVEL``  应用日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL），默认 ``INFO``。
    ``SLA_LOG_FILE``   应用日志文件路径；设置后启用文件日志（1 MB × 3 轮转）。

异常：
    本模块不抛业务异常：级别非法时退回 ``INFO``，日志文件不可用时退回 stderr 并给出告警。
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from serial_log_analyzer.io.paths import user_log_dir

__all__ = [
    "LOGGER_NAME",
    "configure_logging",
    "current_log_file",
    "get_logger",
    "log_file_path",
    "read_tail",
]

LOGGER_NAME = "serial_log_analyzer"
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3
_VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_log_file: Path | None = None


def _resolve_level(text: str) -> tuple[int, str | None]:
    """把级别文本解析为 ``logging`` 数值级别。

    参数：
        text: 级别名称，大小写不敏感。

    返回：
        ``(数值级别, 告警文本)``；级别无法识别时返回 ``INFO`` 与告警文本。
    """
    name = text.strip().upper()
    if name in _VALID_LEVELS:
        return getattr(logging, name), None
    return logging.INFO, f"无法识别的日志级别 {text!r}，已退回 INFO"


def log_file_path() -> Path:
    """返回默认应用日志文件路径：``<用户日志目录>/serial-log-analyzer.log``。"""
    return user_log_dir() / "serial-log-analyzer.log"


def configure_logging(
    *, level: str = "INFO", log_file: Path | str | None = None, reset: bool = False
) -> None:
    """配置应用日志输出；重复调用是幂等的（先移除旧 handler）。

    参数：
        level: 默认级别，可被 ``SLA_LOG_LEVEL`` 覆盖。
        log_file: 启用文件日志时写入的路径，可被 ``SLA_LOG_FILE`` 覆盖；
            为 ``None`` 且环境变量未设置时只输出到 stderr。
        reset: 启用文件日志时先清空已有内容（只在启动那一次用，否则会中途抹掉本次运行记录）。
    """
    global _log_file

    numeric_level, warning = _resolve_level(os.environ.get("SLA_LOG_LEVEL") or level)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(numeric_level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    override = os.environ.get("SLA_LOG_FILE")
    if override:
        target: Path | None = Path(override).expanduser()
    elif log_file is not None:
        target = Path(log_file).expanduser()
    else:
        target = None

    _log_file = None
    if target is not None:
        if reset and target.exists():
            try:
                target.write_text("", encoding="utf-8")
            except OSError as exc:
                logger.warning("无法清空日志文件，沿用已有内容：%s（%s）", target, exc)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                target,
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            _log_file = target
        except OSError as exc:
            logger.warning("日志文件不可用，仅输出到 stderr：%s（%s）", target, exc)

    if warning:
        logger.warning(warning)


def get_logger(name: str) -> logging.Logger:
    """返回应用日志命名空间下的 logger。

    参数：
        name: 模块名（如 ``settings``）或已带 ``serial_log_analyzer`` 前缀的完整名称。
    """
    if name == LOGGER_NAME or name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def read_tail(line_count: int = 200) -> list[str]:
    """读取当前应用日志文件的末尾若干行。

    参数:
        line_count: 最多返回的行数。

    返回:
        末尾若干行；未启用文件日志、文件不存在或不可读时返回空列表。
        日志文件按 1 MB × 3 轮转（最多几 MB），因此直接整读再取尾部。
    """

    path = current_log_file()
    if path is None or line_count <= 0:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-line_count:]


def current_log_file() -> Path | None:
    """返回当前生效的文件日志路径；未启用文件日志时为 ``None``。"""
    return _log_file
