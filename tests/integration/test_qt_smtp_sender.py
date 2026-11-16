"""``QtSmtpNotifier`` 集成测试：本地 TCP SMTP 桩验证线程池非阻塞、超时、脱敏与停机清理。"""

from __future__ import annotations

import email
import email.header
import email.policy
import socketserver
import threading

import pytest

from serial_log_analyzer.core.errors import AppError, NotificationError
from serial_log_analyzer.core.models.notification import SmtpConfig, SmtpSecurity
from serial_log_analyzer.io.notifications.qt_smtp_sender import QtSmtpNotifier


class _SmtpStubServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.received_raw: list[bytes] = []
        self.release_event = threading.Event()
        super().__init__(("127.0.0.1", 0), _SmtpStubHandler)


class _SmtpStubHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server: _SmtpStubServer = self.server  # type: ignore[assignment]
        self.wfile.write(b"220 localhost ESMTP stub\r\n")
        self.wfile.flush()

        if server.mode == "hang":
            server.release_event.wait(2.0)
            return

        while True:
            raw_line = self.rfile.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            upper = line.upper()
            if upper.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-localhost\r\n250 AUTH PLAIN LOGIN\r\n")
            elif upper.startswith("AUTH"):
                if server.mode == "auth_fail":
                    self.wfile.write(b"535 5.7.8 Authentication failed\r\n")
                else:
                    self.wfile.write(b"235 2.7.0 Authentication successful\r\n")
            elif upper.startswith(("MAIL FROM", "RCPT TO")):
                self.wfile.write(b"250 2.1.0 OK\r\n")
            elif upper == "DATA":
                self.wfile.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                self.wfile.flush()
                chunks: list[bytes] = []
                while True:
                    data_line = self.rfile.readline()
                    if not data_line or data_line.rstrip(b"\r\n") == b".":
                        break
                    chunks.append(data_line)
                server.received_raw.append(b"".join(chunks))
                self.wfile.write(b"250 2.0.0 queued\r\n")
            elif upper == "QUIT":
                self.wfile.write(b"221 2.0.0 Bye\r\n")
                self.wfile.flush()
                break
            else:
                self.wfile.write(b"500 unrecognized command\r\n")
            self.wfile.flush()


@pytest.fixture
def smtp_server():
    created: list[_SmtpStubServer] = []

    def _start(mode: str = "ok") -> _SmtpStubServer:
        srv = _SmtpStubServer(mode=mode)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        created.append(srv)
        return srv

    yield _start
    for srv in created:
        srv.release_event.set()
        srv.shutdown()
        srv.server_close()


def test_async_send_delivers_utf8_email_without_blocking_qt(qapp, qtbot, smtp_server) -> None:
    srv = smtp_server("ok")
    port = srv.server_address[1]
    notifier = QtSmtpNotifier()
    done_flags: list[bool] = []
    errors: list[AppError] = []

    cfg = SmtpConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        security=SmtpSecurity.NONE,
        username="",
        sender="sla@example.com",
        recipients=("ops@example.com",),
        timeout_seconds=5.0,
    )
    notifier.send(
        cfg,
        "",
        "[CRITICAL] 内存分配失败",
        "中文异常告警摘要正文",
        lambda: done_flags.append(True),
        errors.append,
    )

    qtbot.waitUntil(lambda: len(done_flags) == 1 or len(errors) == 1, timeout=3000)
    assert errors == []
    assert done_flags == [True]
    assert len(srv.received_raw) == 1
    msg = email.message_from_bytes(srv.received_raw[0], policy=email.policy.default)
    assert msg["From"] == "sla@example.com"
    assert msg["To"] == "ops@example.com"
    assert "内存分配失败" in str(msg["Subject"])
    assert "中文异常告警摘要正文" in msg.get_content()
    assert notifier.shutdown(1000) is True


def test_auth_failure_sanitizes_secret_and_reports_notification_error(
    qapp, qtbot, smtp_server
) -> None:
    srv = smtp_server("auth_fail")
    port = srv.server_address[1]
    notifier = QtSmtpNotifier()
    errors: list[AppError] = []
    secret = "super-secret-token-xyz"

    cfg = SmtpConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        security=SmtpSecurity.NONE,
        username="ops",
        sender="ops@example.com",
        recipients=("ops@example.com",),
        timeout_seconds=5.0,
    )
    notifier.send(
        cfg,
        secret,
        "Test Auth",
        "Body",
        lambda: None,
        errors.append,
    )

    qtbot.waitUntil(lambda: len(errors) == 1, timeout=3000)
    assert isinstance(errors[0], NotificationError)
    assert "认证失败" in str(errors[0])
    assert secret not in str(errors[0])
    assert notifier.shutdown(1000) is True


def test_timeout_and_shutdown_cleanup(qapp, qtbot, smtp_server) -> None:
    srv = smtp_server("hang")
    port = srv.server_address[1]
    notifier = QtSmtpNotifier()
    errors: list[AppError] = []

    cfg = SmtpConfig(
        enabled=True,
        host="127.0.0.1",
        port=port,
        security=SmtpSecurity.NONE,
        username="",
        sender="ops@example.com",
        recipients=("ops@example.com",),
        timeout_seconds=0.15,
    )
    notifier.send(cfg, "", "Timeout", "Body", lambda: None, errors.append)

    qtbot.waitUntil(lambda: len(errors) == 1, timeout=3000)
    assert isinstance(errors[0], NotificationError)
    assert "超时" in str(errors[0])
    assert notifier.shutdown(1000) is True

    # shutdown 之后再发送立即以 NotificationError 失败，不留挂起任务
    late_errors: list[AppError] = []
    notifier.send(cfg, "", "Late", "Body", lambda: None, late_errors.append)
    assert len(late_errors) == 1 and isinstance(late_errors[0], NotificationError)
