"""命令响应协议测试。"""

from __future__ import annotations

from serial_log_analyzer.core.device.command import is_response_line, parse_response


def test_ok_reply() -> None:
    reply = parse_response("@OK PONG")
    assert (reply.ok, reply.text, reply.code) == (True, "PONG", None)


def test_err_reply_keeps_code_and_message() -> None:
    reply = parse_response("@ERR 1 unknown command")
    assert (reply.ok, reply.code, reply.text) == (False, 1, "unknown command")


def test_is_response_line() -> None:
    assert is_response_line("@OK PONG") is True
    assert is_response_line("[I] [main] x") is False
