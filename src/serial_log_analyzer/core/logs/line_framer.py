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
        max_line_bytes: 单行最大字节数，超出时强制截断，防止设备异常导致内存膨胀。

    行尾以 ``\\n`` 切分，段内裸 ``\\r`` 也会被切分（兼容 ``\\r\\n``）。
    """

    def __init__(
        self,
        *,
        encoding: str = "utf-8",
        max_line_bytes: int = 65536,
    ) -> None:
        self._encoding = encoding
        self._max_line_bytes = max_line_bytes
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[str]:
        """输入字节分块，返回本次可完整切分出的文本行（不含行尾符）。

        参数:
            data: 任意长度的原始字节。

        返回:
            完整行列表；未完成的行保留在内部缓冲，等待下次调用。
        """

        if data:
            self._buffer.extend(data)

        lines: list[str] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline != -1:
                segment = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                lines.extend(self._emit(segment))
                continue
            if len(self._buffer) > self._max_line_bytes:
                segment = bytes(self._buffer)
                self._buffer.clear()
                lines.extend(self._emit(segment))
                continue
            break
        return lines

    def finalize(self) -> str | None:
        """请求结束或串口关闭时调用，返回缓冲中的残余内容。

        返回:
            残余文本；无残余时返回 ``None``。
        """

        if not self._buffer:
            return None
        text = bytes(self._buffer).decode(self._encoding, errors="replace")
        self._buffer.clear()
        return text

    def _emit(self, segment: bytes) -> list[str]:
        """把一段无换行的字节转换为文本行，超长时按 ``max_line_bytes`` 拆分。"""
        lines: list[str] = []
        while len(segment) > self._max_line_bytes:
            lines.extend(self._split_cr(segment[: self._max_line_bytes]))
            segment = segment[self._max_line_bytes:]
        lines.extend(self._split_cr(segment))
        return lines

    def _split_cr(self, segment: bytes) -> list[str]:
        """按裸 ``\\r`` 再切分并解码；结尾的 ``\\r`` 作为行尾丢弃。"""
        parts = segment.split(b"\r")
        if len(parts) > 1 and parts[-1] == b"":
            parts = parts[:-1]
        return [part.decode(self._encoding, errors="replace") for part in parts]

    def reset(self) -> None:
        """清空内部缓冲（用于断开重连）。"""

        self._buffer.clear()
