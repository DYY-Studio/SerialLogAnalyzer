"""字节流分帧：把串口任意分块的数据切分为完整文本行。

串口数据不保证与行边界对齐：一次 ``readyRead`` 可能只包含半行、包含多行，
或在 UTF-8 字符中间截断。本类自维护字节缓冲，直到出现换行符才产出完整行。
"""

from __future__ import annotations

__all__ = ["LineFramer"]


class LineFramer:
    """把字节分块重组为完整文本行。

    参数:
        encoding: 文本编码，默认 ``utf-8``。
        newline: 行分隔符，默认 ``\\n``；``\\r\\n`` 与 ``\\r`` 也会被正常处理。
        max_line_bytes: 单行最大字节数，超出时强制截断，防止设备异常导致内存膨胀。
    """

    def __init__(
        self,
        *,
        encoding: str = "utf-8",
        newline: str = "\n",
        max_line_bytes: int = 65536,
    ) -> None:
        self._encoding = encoding
        self._newline = newline
        self._max_line_bytes = max_line_bytes
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[str]:
        """输入字节分块，返回本次可完整切分出的文本行（不含行尾符）。

        参数:
            data: 任意长度的原始字节。

        返回:
            完整行列表；未完成的行保留在内部缓冲，等待下次调用。
        """

        raise NotImplementedError

    def finalize(self) -> str | None:
        """请求结束或串口关闭时调用，返回缓冲中的残余内容。

        返回:
            残余文本；无残余时返回 ``None``。
        """

        raise NotImplementedError

    def reset(self) -> None:
        """清空内部缓冲（用于断开重连）。"""

        self._buffer.clear()
