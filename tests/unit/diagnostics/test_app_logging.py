"""``diagnostics/app_logging.py`` 的集中日志配置测试。"""

from __future__ import annotations

import logging

import pytest

from serial_log_analyzer.diagnostics.app_logging import (
    LOGGER_NAME,
    configure_logging,
    current_log_file,
    get_logger,
    log_file_path,
    read_tail,
)
from serial_log_analyzer.io.paths import user_log_dir


@pytest.fixture(autouse=True)
def clean_logging_env(monkeypatch):
    """隔离环境变量与 handler 状态，避免用例互相污染。"""
    monkeypatch.delenv("SLA_LOG_LEVEL", raising=False)
    monkeypatch.delenv("SLA_LOG_FILE", raising=False)
    yield
    configure_logging(level="INFO", log_file=None)


def _logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def test_get_logger_prefixes_name():
    assert get_logger("settings").name == f"{LOGGER_NAME}.settings"
    assert get_logger(LOGGER_NAME).name == LOGGER_NAME
    assert get_logger(f"{LOGGER_NAME}.llm").name == f"{LOGGER_NAME}.llm"


def test_log_file_path_is_under_user_log_dir():
    assert log_file_path() == user_log_dir() / "serial-log-analyzer.log"


def test_configure_without_file_keeps_stderr_only():
    configure_logging(level="DEBUG")

    assert current_log_file() is None
    assert _logger().level == logging.DEBUG
    assert _logger().propagate is False
    assert len(_logger().handlers) == 1


def test_configure_with_file_writes_records(tmp_path):
    target = tmp_path / "logs" / "app.log"

    configure_logging(level="INFO", log_file=target)
    get_logger("test").info("写入一条消息")

    assert current_log_file() == target
    assert len(_logger().handlers) == 2
    assert "写入一条消息" in target.read_text(encoding="utf-8")


def test_environment_overrides_file_argument(tmp_path, monkeypatch):
    override = tmp_path / "env.log"
    monkeypatch.setenv("SLA_LOG_FILE", str(override))

    configure_logging(level="INFO", log_file=tmp_path / "argument.log")

    assert current_log_file() == override


def test_repeated_configuration_is_idempotent(tmp_path):
    target = tmp_path / "app.log"

    configure_logging(level="INFO", log_file=target)
    configure_logging(level="INFO", log_file=target)

    assert len(_logger().handlers) == 2


def test_read_tail_returns_last_lines(tmp_path):
    target = tmp_path / "app.log"
    configure_logging(level="INFO", log_file=target)
    logger = get_logger("test")
    for index in range(5):
        logger.info("第 %d 条", index)

    tail = read_tail(2)

    assert len(tail) == 2
    assert "第 3 条" in tail[0] and "第 4 条" in tail[1]


def test_read_tail_without_file_logging_is_empty():
    configure_logging(level="INFO", log_file=None)

    assert current_log_file() is None
    assert read_tail() == []


def test_reset_truncates_previous_content(tmp_path):
    target = tmp_path / "app.log"
    configure_logging(level="INFO", log_file=target)
    get_logger("test").info("上一次运行")

    configure_logging(level="INFO", log_file=target, reset=True)

    assert target.read_text(encoding="utf-8") == ""
    get_logger("test").info("本次运行")
    assert target.read_text(encoding="utf-8").count("本次运行") == 1


def test_environment_level_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SLA_LOG_LEVEL", "warning")
    target = tmp_path / "app.log"

    configure_logging(level="DEBUG", log_file=target)

    assert _logger().level == logging.WARNING


def test_invalid_level_falls_back_to_info_and_warns(tmp_path):
    target = tmp_path / "app.log"

    configure_logging(level="LOUD", log_file=target)

    assert _logger().level == logging.INFO
    assert "无法识别的日志级别" in target.read_text(encoding="utf-8")


def test_unavailable_log_file_falls_back_to_stderr(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("不是目录", encoding="utf-8")

    configure_logging(level="INFO", log_file=blocker / "app.log")

    assert current_log_file() is None
    assert len(_logger().handlers) == 1
