"""Qt HTTP 传输适配：只传递字节，不解析模型协议。"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from serial_log_analyzer.core.errors import (
    AppError,
    ConfigError,
    HttpStatusError,
    NetworkError,
    NetworkTimeoutError,
)
from serial_log_analyzer.core.models.provider import HttpRequest
from serial_log_analyzer.core.ports import (
    BytesHandler,
    CancellationToken,
    ErrorHandler,
    VoidHandler,
)


class _Pending:
    def __init__(self, owner, reply, seconds, on_chunk, on_done, on_error):
        self.owner = owner
        self.reply = reply
        self.on_chunk = on_chunk
        self.on_done = on_done
        self.on_error = on_error
        self.ended = False
        self.timer = QTimer(reply)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        reply.readyRead.connect(self._read)
        reply.finished.connect(self._finish)
        self.timer.start(max(1, int(seconds * 1000)))

    def _read(self):
        if self.ended:
            return
        status = self.reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status is None or not 200 <= int(status) < 300:
            # 错误正文不进入业务解析，亦不回显可能包含凭据的服务端正文。
            self.reply.readAll()
            return
        data = bytes(self.reply.readAll())
        if data:
            try:
                self.on_chunk(data)
            except AppError as exc:
                self._end(exc, abort=True)

    def _finish(self):
        if self.ended:
            return
        error = self.owner._translate_error(self.reply)
        if error is None:
            self._read()
        if not self.ended:
            self._end(error)

    def _timeout(self):
        self._end(NetworkTimeoutError("模型请求超时"), abort=True)

    def cancel(self):
        if not self.ended:
            self._end(NetworkError("模型请求已取消"), abort=True)

    def _end(self, error, *, abort=False):
        if self.ended:
            return
        self.ended = True
        reply = self.reply
        self.timer.stop()
        if abort:
            reply.abort()
        self.owner._active.discard(self)
        try:
            if error is None:
                self.on_done()
            else:
                self.on_error(error)
        finally:
            reply.deleteLater()
            self.reply = self.timer = None
            self.on_chunk = self.on_done = self.on_error = None


class QtHttpTransport:
    """通过注入的 manager 发送异步请求；parent 为可选生命周期归属对象。"""

    def __init__(self, manager: object, parent: object | None = None) -> None:
        if not isinstance(manager, QNetworkAccessManager):
            raise ConfigError("manager 必须为 QNetworkAccessManager")
        self._manager = manager
        self._parent = parent if isinstance(parent, QObject) else None
        self._active = set()

    def send(
        self,
        request: HttpRequest,
        on_chunk: BytesHandler,
        on_done: VoidHandler,
        on_error: ErrorHandler,
    ) -> CancellationToken:
        """发送 GET / POST 请求；返回取消令牌，失败回调与成功回调合计仅执行一次。

        参数为请求及字节、完成、错误回调；本地非法请求抛出 ConfigError。
        """
        seconds = request.timeout_seconds
        if seconds * 1000 > 2147483647:
            raise ConfigError("请求超时超过 Qt 计时范围")
        url = QUrl(request.url)
        if (
            request.method not in {"GET", "POST"}
            or not url.isValid()
            or url.scheme() not in {"http", "https"}
            or not url.host()
            or url.userInfo()
            or url.hasFragment()
        ):
            raise ConfigError("仅支持无凭据的 HTTP(S) GET/POST 请求")
        method_body: bytes | None = None
        if request.method == "POST":
            try:
                method_body = json.dumps(
                    request.body, ensure_ascii=False, allow_nan=False
                ).encode("utf-8")
            except (ValueError, TypeError) as exc:
                raise ConfigError("请求体无法序列化为 JSON") from exc
        qt_request = QNetworkRequest(url)
        qt_request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        if method_body is not None:
            qt_request.setRawHeader(b"Content-Type", b"application/json")
        for name, value in request.headers.items():
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or not name
                or any(c in name + value for c in "\r\n\x00")
            ):
                raise ConfigError("HTTP 请求头非法")
            try:
                qt_request.setRawHeader(name.encode("ascii"), value.encode("utf-8"))
            except UnicodeError as exc:
                raise ConfigError("HTTP 请求头名称必须为 ASCII") from exc
        reply = (
            self._manager.get(qt_request)
            if method_body is None
            else self._manager.post(qt_request, method_body)
        )
        pending = _Pending(self, reply, seconds, on_chunk, on_done, on_error)
        self._active.add(pending)
        return pending

    def _translate_error(self, reply: QNetworkReply) -> AppError | None:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status is not None and not 200 <= int(status) < 300:
            return HttpStatusError(int(status))
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return NetworkError(f"网络请求失败（Qt 错误码 {reply.error().value}）")
        if status is None:
            return NetworkError("响应缺少 HTTP 状态码")
        return None
