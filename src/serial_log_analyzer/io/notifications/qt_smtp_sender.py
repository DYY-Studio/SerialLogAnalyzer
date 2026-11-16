"""基于 ``smtplib`` + 私有单线程 ``QThreadPool`` 的异步 SMTP 发送适配器。

线程边界：
- ``send()`` 在 Qt 主线程接收不可变配置与已解析的密码快照，投递至私有单线程 ``QThreadPool``
  顺序执行阻塞式 ``smtplib`` I/O，绝不阻塞主事件循环与串口接收；
- 工作线程绝不触碰 ``CredentialResolver``、``QSettings``、``LogPipeline`` 或任何 Widget；
- 发送结果通过桥接 ``QObject`` 的 ``QueuedConnection`` 信号回切到 Qt 主线程后才调用回调；
- 所有错误（认证/TLS/超时/网络）均脱敏翻译为 :class:`NotificationError`，绝不泄露密码或 AUTH 报文。
"""

from __future__ import annotations

import smtplib
import ssl
import threading
from contextlib import suppress
from dataclasses import dataclass
from email.message import EmailMessage

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal

from serial_log_analyzer.core.errors import NotificationError
from serial_log_analyzer.core.models.notification import SmtpConfig, SmtpSecurity
from serial_log_analyzer.core.ports import ErrorHandler, VoidHandler

__all__ = ["QtSmtpNotifier"]


@dataclass(frozen=True)
class _SmtpJob:
    task_id: int
    config: SmtpConfig
    password: str
    subject: str
    body: str


class _SmtpRunnable(QRunnable):
    """在工作线程执行单次阻塞 SMTP 投递的 ``QRunnable``。"""

    def __init__(
        self,
        job: _SmtpJob,
        completed: Signal,
        stop_event: threading.Event,
    ) -> None:
        super().__init__()
        self._job = job
        self._completed = completed
        self._stop_event = stop_event

    def run(self) -> None:
        if self._stop_event.is_set():
            return
        ok = True
        error_text = ""
        try:
            _send_blocking(self._job)
        except NotificationError as exc:
            ok = False
            error_text = str(exc)
        except Exception as exc:  # noqa: BLE001 - 兜底转译，避免工作线程未捕获异常
            ok = False
            error_text = f"SMTP 发送失败（{exc.__class__.__name__}）"

        if self._stop_event.is_set():
            return
        with suppress(RuntimeError):
            self._completed.emit(self._job.task_id, ok, error_text)


def _send_blocking(job: _SmtpJob) -> None:
    cfg = job.config
    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = ", ".join(cfg.recipients)
    msg["Subject"] = job.subject
    msg.set_content(job.body, subtype="plain", charset="utf-8")

    try:
        if cfg.security is SmtpSecurity.SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                cfg.host, cfg.port, timeout=cfg.timeout_seconds, context=context
            ) as server:
                _authenticate_and_deliver(server, cfg, job.password, msg)
        elif cfg.security is SmtpSecurity.STARTTLS:
            context = ssl.create_default_context()
            with smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout_seconds) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                _authenticate_and_deliver(server, cfg, job.password, msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout_seconds) as server:
                server.ehlo()
                _authenticate_and_deliver(server, cfg, job.password, msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise NotificationError("SMTP 认证失败，请检查用户名或密码/授权码") from exc
    except TimeoutError as exc:
        raise NotificationError("SMTP 请求超时") from exc
    except ssl.SSLError as exc:
        raise NotificationError("SMTP TLS/SSL 握手失败，请检查端口与安全传输模式") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise NotificationError("SMTP 收件人地址被服务端拒绝") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise NotificationError("SMTP 发件人地址被服务端拒绝") from exc
    except smtplib.SMTPServerDisconnected as exc:
        if (
            isinstance(exc.__cause__, TimeoutError)
            or isinstance(exc.__context__, TimeoutError)
            or "timed out" in str(exc).lower()
        ):
            raise NotificationError("SMTP 请求超时") from exc
        raise NotificationError("SMTP 连接意外断开") from exc
    except smtplib.SMTPException as exc:
        raise NotificationError(f"SMTP 发送失败（{exc.__class__.__name__}）") from exc
    except OSError as exc:
        raise NotificationError(f"SMTP 网络连接失败（{exc.__class__.__name__}）") from exc


def _authenticate_and_deliver(
    server: smtplib.SMTP, cfg: SmtpConfig, password: str, msg: EmailMessage
) -> None:
    username = cfg.username.strip()
    if username or password:
        server.login(username, password)
    server.send_message(msg, from_addr=cfg.sender, to_addrs=list(cfg.recipients))


class QtSmtpNotifier(QObject):
    """``EmailNotifier`` 的 Qt 线程池异步实现。"""

    _completed = Signal(int, bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._stop_event = threading.Event()
        self._shutting_down = False
        self._pending: dict[int, tuple[VoidHandler, ErrorHandler]] = {}
        self._next_id = 1
        self._completed.connect(self._on_completed, Qt.ConnectionType.QueuedConnection)

    def send(
        self,
        config: SmtpConfig,
        password: str,
        subject: str,
        body: str,
        on_done: VoidHandler,
        on_error: ErrorHandler,
    ) -> None:
        """在私有单线程 ``QThreadPool`` 中投递邮件，完成后回 Qt 主线程执行回调。"""

        if self._shutting_down:
            on_error(NotificationError("邮件通知器已停止"))
            return

        task_id = self._next_id
        self._next_id += 1
        self._pending[task_id] = (on_done, on_error)
        job = _SmtpJob(
            task_id=task_id,
            config=config,
            password=password,
            subject=subject,
            body=body,
        )
        self._pool.start(_SmtpRunnable(job, self._completed, self._stop_event))

    def shutdown(self, wait_ms: int = 1000) -> bool:
        """停机清理：置位停止标志、清空排队任务并等待进行中任务结束。"""

        self._shutting_down = True
        self._stop_event.set()
        self._pool.clear()
        done = self._pool.waitForDone(max(0, int(wait_ms)))
        self._pending.clear()
        return done

    def _on_completed(self, task_id: int, ok: bool, error_text: str) -> None:
        callbacks = self._pending.pop(task_id, None)
        if callbacks is None or self._shutting_down:
            return
        on_done, on_error = callbacks
        if ok:
            on_done()
        else:
            on_error(NotificationError(error_text or "SMTP 发送失败"))
