"""扩展 JSON Pointer。

在 RFC 6901 基础上仅增加一个扩展：**数组负索引**。

语义定案（详见 ``docs/protocols/json-pointer.md``）：
- ``""`` 指向整个文档；
- ``~0`` → ``~``，``~1`` → ``/``；
- 数组下标 ``-1`` 表示末元素，``-2`` 表示倒数第二个，依此类推；
- ``-0`` 非法；单独的 ``-`` 非法（RFC 6901 中 ``-`` 仅用于写入语义，本项目只做读取）；
- 越界、类型不符、对非数组使用负索引、非法转义 → :class:`PointerError`。

本模块为纯 Python，不依赖 Qt 与 HTTP，可独立单测。
"""

from __future__ import annotations

import re
from typing import Any

from serial_log_analyzer.core.errors import PointerError

__all__ = ["parse_pointer", "resolve_pointer"]

_ESCAPE_MAP = {"~0": "~", "~1": "/"}


def parse_pointer(pointer: str) -> list[str]:
    """把指针字符串解析为解码后的 token 列表。

    参数:
        pointer: 形如 ``/choices/-1/message/content`` 的指针；空串表示根。

    返回:
        已解码转义的 token 列表；根指针返回空列表。

    异常:
        PointerError: 指针不以 ``/`` 开头，或包含非法转义（``~`` 后不是 0/1）。
    """

    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise PointerError("JSON Pointer 必须为空或以 / 开头")
    if not pointer:
        return []
    tokens = pointer[1:].split("/")
    if any(re.search(r"~(?![01])", token) for token in tokens):
        raise PointerError("JSON Pointer 包含非法转义")
    return [token.replace("~1", "/").replace("~0", "~") for token in tokens]


def resolve_pointer(document: Any, pointer: str) -> Any:
    """在文档中解析指针并返回目标值。

    参数:
        document: 已解码的 JSON 结构（``dict`` / ``list`` / 标量）。
        pointer: 指针字符串。

    返回:
        指针指向的值。

    异常:
        PointerError: 路径不存在、下标越界、类型不匹配或使用非法负索引。
    """

    value = document
    for token in parse_pointer(pointer):
        if token in ("-0", "-"):
            raise PointerError("非法数组下标")
        if isinstance(value, dict):
            if re.fullmatch(r"-?[0-9]+", token):
                raise PointerError("数字下标只能用于数组")
            if token not in value:
                raise PointerError(f"路径不存在：{pointer}")
            value = value[token]
        elif isinstance(value, list):
            if not re.fullmatch(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)", token):
                raise PointerError("非法数组下标")
            index = int(token)
            if not -len(value) <= index < len(value):
                raise PointerError("数组下标越界")
            value = value[index]
        else:
            raise PointerError("路径经过标量，无法继续取值")
    return value
