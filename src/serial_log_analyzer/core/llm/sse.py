"""增量 SSE 分帧：支持任意网络边界与 UTF-8 分块。"""

from __future__ import annotations

import codecs

from serial_log_analyzer.core.errors import ConfigError, ResponseParseError
from serial_log_analyzer.core.models.provider import StreamEvent


class SSEParser:
    """解析 SSE 字节流；encoding 指定编码，max_event_bytes 限制事件内存。"""

    def __init__(self, *, encoding: str = "utf-8", max_event_bytes: int = 1048576) -> None:
        if type(max_event_bytes) is not int or max_event_bytes <= 0:
            raise ConfigError("事件上限必须为正整数")
        self._encoding = encoding
        self._max_event_bytes = max_event_bytes
        self.reset()

    def reset(self) -> None:
        """清空所有分帧、解码和结束状态，用于新请求。"""
        try:
            self._decoder = codecs.getincrementaldecoder(
                "utf-8-sig" if self._encoding == "utf-8" else self._encoding
            )(errors="strict")
        except LookupError as exc:
            raise ConfigError("不支持的 SSE 编码") from exc
        self._line = []
        self._raw = []
        self._data = []
        self._event = None
        self._size = 0
        self._skip_lf = False
        self._closed = False

    def feed(self, data: bytes) -> list[StreamEvent]:
        """输入字节，返回完整事件；非法编码或超限抛出 ResponseParseError。"""
        if self._closed:
            raise ResponseParseError("SSE 已结束，请先 reset")
        result = []
        # 限制每次解码的临时文本，超大输入不一次复制到缓冲。
        for offset in range(0, len(data), 4096):
            try:
                text = self._decoder.decode(data[offset : offset + 4096])
            except UnicodeError as exc:
                raise ResponseParseError("SSE 字节编码非法") from exc
            result.extend(self._consume(text))
        return result

    def _consume(self, text: str) -> list[StreamEvent]:
        result = []
        for char in text:
            if self._skip_lf:
                self._skip_lf = False
                if char == "\n":
                    continue
            self._size += len(char.encode(self._encoding))
            if self._size > self._max_event_bytes:
                raise ResponseParseError("SSE 单事件超出大小上限")
            if char in "\r\n":
                result.extend(self._finish_line())
                self._skip_lf = char == "\r"
            else:
                self._line.append(char)
        return result

    def _finish_line(self) -> list[StreamEvent]:
        line = "".join(self._line)
        self._line = []
        if not line:
            result = self._emit()
            self._size = 0
            return result
        self._raw.append(line)
        if line.startswith(":"):
            return []
        name, sep, value = line.partition(":")
        if not sep:
            value = ""
        if value.startswith(" "):
            value = value[1:]
        if name == "data":
            self._data.append(value)
        elif name == "event":
            self._event = value or None
        return []

    def _emit(self) -> list[StreamEvent]:
        result = (
            [StreamEvent("\n".join(self._data), self._event, "\n".join(self._raw))]
            if self._data
            else []
        )
        self._data = []
        self._raw = []
        self._event = None
        return result

    def finalize(self) -> list[StreamEvent]:
        """结束输入并按项目契约 flush 尾部事件；不完整编码抛出 ResponseParseError。"""
        if self._closed:
            return []
        try:
            result = self._consume(self._decoder.decode(b"", final=True))
        except UnicodeError as exc:
            raise ResponseParseError("SSE 尾部字符不完整") from exc
        if self._line:
            result.extend(self._finish_line())
        result.extend(self._emit())
        self._closed = True
        return result
