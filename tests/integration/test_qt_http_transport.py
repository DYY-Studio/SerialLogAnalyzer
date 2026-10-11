"""真实 Qt HTTP 集成测试；服务使用 Qt TCP，不使用外网或后台线程。"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QHostAddress, QNetworkAccessManager, QTcpServer

from serial_log_analyzer.core.errors import (
    HttpStatusError,
    NetworkError,
    NetworkTimeoutError,
    ResponseParseError,
)
from serial_log_analyzer.core.models.provider import HttpRequest
from serial_log_analyzer.io.llm.qt_http_transport import QtHttpTransport


@pytest.fixture
def server(qtbot):
    listener = QTcpServer()
    assert listener.listen(QHostAddress.SpecialAddress.LocalHost, 0)
    sockets, requests = [], []

    def accept():
        socket = listener.nextPendingConnection()
        sockets.append(socket)
        data = bytearray()
        handled = False

        def read():
            nonlocal handled
            data.extend(bytes(socket.readAll()))
            if handled or b"\r\n\r\n" not in data:
                return
            header, body = bytes(data).split(b"\r\n\r\n", 1)
            headers = {
                line.split(b":", 1)[0].lower(): line.split(b":", 1)[1].strip()
                for line in header.split(b"\r\n")[1:]
            }
            if len(body) < int(headers.get(b"content-length", b"0")):
                return
            handled = True
            requests.append((header, body))
            route = header.split(b" ")[1].decode()
            if route == "/stall":
                return
            status = int(route.split("/")[-1]) if route.startswith("/status/") else 200
            payload = b'{"choices":[{"message":{"content":"ok"}}]}'
            if route == "/stream":
                payload = (
                    'data: {"choices":[{"delta":{"content":"中文"}}]}\n\ndata: [DONE]\n\n'.encode()
                )
            if route == "/bad-json":
                payload = b"not-json"
            length = len(payload) + (10 if route == "/broken" else 0)
            socket.write(
                f"HTTP/1.1 {status} Test\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n".encode()
            )
            if route == "/stream":
                parts = [payload[:35], payload[35:36], payload[36:]]

                def write_part(index):
                    socket.write(parts[index])
                    if index + 1 < len(parts):
                        QTimer.singleShot(5, socket, lambda: write_part(index + 1))
                    else:
                        socket.disconnectFromHost()

                write_part(0)
            else:
                socket.write(payload)
                socket.disconnectFromHost()

        socket.readyRead.connect(read)

    listener.newConnection.connect(accept)
    yield f"http://127.0.0.1:{listener.serverPort()}", requests
    for socket in sockets:
        socket.abort()
    listener.close()
    listener.deleteLater()


@pytest.fixture
def transport(qtbot):
    manager = QNetworkAccessManager()
    transport = QtHttpTransport(manager)
    yield transport
    for pending in tuple(transport._active):
        pending.cancel()
    manager.deleteLater()


def send(transport, url, *, timeout=1):
    chunks, done, errors = [], [], []
    token = transport.send(
        HttpRequest("POST", url, body={"text": "中文"}, timeout_seconds=timeout),
        chunks.append,
        lambda: done.append(True),
        errors.append,
    )
    return token, chunks, done, errors


def test_http_success(server, transport, qtbot):
    token, chunks, done, errors = send(transport, server[0] + "/ok")
    qtbot.waitUntil(lambda: bool(done or errors))
    assert done == [True] and errors == []
    assert json.loads(b"".join(chunks))["choices"][0]["message"]["content"] == "ok"
    assert json.loads(server[1][0][1]) == {"text": "中文"}
    token.cancel()
    assert not transport._active and done == [True] and errors == []


def test_get_request_sends_no_body(server, transport, qtbot):
    chunks, done, errors = [], [], []
    token = transport.send(
        HttpRequest(
            "GET",
            server[0] + "/models",
            headers={"Authorization": "Bearer k"},
            timeout_seconds=1,
        ),
        chunks.append,
        lambda: done.append(True),
        errors.append,
    )
    qtbot.waitUntil(lambda: bool(done or errors))

    header, body = server[1][0]
    assert done == [True] and errors == []
    assert body == b""
    assert header.startswith(b"GET /models HTTP/1.1")
    assert b"authorization: bearer k" in header.lower()
    token.cancel()
    assert not transport._active


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_status(server, transport, qtbot, status):
    _, chunks, done, errors = send(transport, server[0] + f"/status/{status}")
    qtbot.waitUntil(lambda: bool(errors))
    assert not chunks and not done and len(errors) == 1
    assert isinstance(errors[0], HttpStatusError) and errors[0].status == status


def test_timeout(server, transport, qtbot):
    _, _, done, errors = send(transport, server[0] + "/stall", timeout=0.03)
    qtbot.waitUntil(lambda: bool(errors))
    assert not done and len(errors) == 1 and isinstance(errors[0], NetworkTimeoutError)
    assert not transport._active


def test_cancel(server, transport, qtbot):
    token, _, done, errors = send(transport, server[0] + "/stall")
    token.cancel()
    token.cancel()
    qtbot.wait(30)
    assert not done and len(errors) == 1 and isinstance(errors[0], NetworkError)
    assert not transport._active


def test_connection_closed_mid_body(server, transport, qtbot):
    _, _, done, errors = send(transport, server[0] + "/broken")
    qtbot.waitUntil(lambda: bool(done or errors))
    assert not done and len(errors) == 1 and isinstance(errors[0], NetworkError)


def test_callback_parse_error(server, transport, qtbot):
    done, errors = [], []

    def fail(data):
        raise ResponseParseError("测试解析失败")

    transport.send(
        HttpRequest("POST", server[0] + "/ok"), fail, lambda: done.append(True), errors.append
    )
    qtbot.waitUntil(lambda: bool(errors))
    assert not done and len(errors) == 1 and not transport._active


def test_concurrent_requests(server, transport, qtbot):
    first = send(transport, server[0] + "/ok")
    second = send(transport, server[0] + "/stall")
    second[0].cancel()
    qtbot.waitUntil(lambda: bool(first[2]))
    assert first[3] == [] and len(second[3]) == 1 and not transport._active

