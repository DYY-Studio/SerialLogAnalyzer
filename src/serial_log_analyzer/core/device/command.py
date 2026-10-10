"""PC 与板端命令通道的响应协议。

板端响应格式见 ``docs/protocols/board-protocol.md``：

.. code-block:: text

    @OK <payload>
    @ERR <code> <message>

以 ``@`` 开头的行与 ``[`` 开头的日志行天然区分，用于在串口日志流中识别命令回复。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CommandReply",
    "RESPONSE_PREFIX_ERR",
    "RESPONSE_PREFIX_OK",
    "is_response_line",
    "parse_response",
]

RESPONSE_PREFIX_OK = "@OK "
RESPONSE_PREFIX_ERR = "@ERR "


@dataclass(frozen=True)
class CommandReply:
    """一条命令响应。

    参数:
        text: 载荷文本；失败时为错误消息。
        ok: 是否成功（``@OK``）。
        code: 失败时的错误码；成功或无法识别时为 ``None``。
    """

    text: str
    ok: bool
    code: int | None = None


def is_response_line(line: str) -> bool:
    """判断一行是否为命令响应行（以 ``@`` 开头）。"""

    return line.startswith("@")


def parse_response(line: str) -> CommandReply:
    """解析一行命令响应。

    无法识别为 ``@OK`` / ``@ERR`` 的 ``@`` 行按失败处理，且不抛异常。
    """

    if line.startswith(RESPONSE_PREFIX_OK):
        return CommandReply(text=line[len(RESPONSE_PREFIX_OK) :], ok=True)
    if line.startswith(RESPONSE_PREFIX_ERR):
        rest = line[len(RESPONSE_PREFIX_ERR) :]
        code_text, _, message = rest.partition(" ")
        try:
            code = int(code_text)
        except ValueError:
            return CommandReply(text=rest, ok=False, code=None)
        return CommandReply(text=message, ok=False, code=code)
    return CommandReply(text=line, ok=False, code=None)
