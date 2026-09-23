"""基于 ``QNetworkAccessManager`` 的 HTTP 传输实现。

实现 :class:`serial_log_analyzer.core.ports.HttpTransport`：

- 请求：把 :class:`HttpRequest` 转换为 ``QNetworkRequest`` + JSON 字节；
- 流式：``QNetworkReply.readyRead`` → ``readAll()`` → ``on_chunk``；
- 结束：``finished`` → 检查 HTTP 状态码与网络错误 → ``on_done`` / ``on_error``；
- 清理：结束后 ``deleteLater()``，避免内存泄漏；
- 超时：使用 ``QTimer`` 实现（v1 不使用 ``QNetworkRequest`` 的 transfer timeout）。

整个应用只创建一个 ``QNetworkAccessManager`` 实例，由 ``bootstrap`` 注入。
"""

from __future__ import annotations

from serial_log_analyzer.core.models.provider import HttpRequest
from serial_log_analyzer.core.ports import (
    BytesHandler,
    CancellationToken,
    ErrorHandler,
    VoidHandler,
)

__all__ = ["QtHttpTransport"]


class QtHttpTransport:
    """``HttpTransport`` 的 Qt 实现。

    参数:
        manager: 由 ``bootstrap`` 创建并持有的 ``QNetworkAccessManager``。
        parent: 可选的 ``QObject`` 父对象。
    """

    def __init__(self, manager: object, parent: object | None = None) -> None:
        raise NotImplementedError

    def send(
        self,
        request: HttpRequest,
        on_chunk: BytesHandler,
        on_done: VoidHandler,
        on_error: ErrorHandler,
    ) -> CancellationToken:
        """发送请求并注册回调。

        返回:
            取消令牌；``cancel()`` 会中止请求并触发 ``on_error``。
        """

        raise NotImplementedError

    def _translate_error(self, reply: object) -> Exception:
        """把 ``QNetworkReply`` 的错误翻译为 core 异常。"""

        raise NotImplementedError
