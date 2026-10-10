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

from typing import Any

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

    raise NotImplementedError


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

    raise NotImplementedError
