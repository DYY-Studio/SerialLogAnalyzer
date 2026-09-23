"""LLM Adapter 加载与校验。

读取 ``providers/adapters/*.yaml``，校验字段完整性与类型，编译扩展 JSON Pointer，
构造 :class:`JSONAdapter`。

校验原则：未知字段报错（避免拼写错误被静默忽略），占位符白名单限制在
``${model} ${system} ${messages} ${temperature} ${max_output_tokens} ${stream} ${api_key}``。
"""

from __future__ import annotations

from typing import Any

from serial_log_analyzer.core.llm.adapter import JSONAdapter
from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["load_adapter", "load_adapters"]

_ADAPTER_DIR = "providers/adapters"


def load_adapter(loader: ResourceLoader, adapter_id: str) -> JSONAdapter:
    """按 ID 加载单个 Adapter。

    参数:
        loader: 资源加载器。
        adapter_id: Adapter 标识，需满足 ``[a-z][a-z0-9-]*``。

    返回:
        校验完成的 :class:`JSONAdapter`。

    异常:
        ConfigError: 文件缺失、YAML 非法、未知字段、缺少必填字段或类型错误。
    """

    raise NotImplementedError


def load_adapters(loader: ResourceLoader) -> list[JSONAdapter]:
    """加载全部 Adapter，用户目录覆盖同 ID 的内置 Adapter。"""

    raise NotImplementedError


def _validate_adapter(data: dict[str, Any], source_path: str) -> JSONAdapter:
    """校验 Adapter 声明并构造对象。

    异常:
        ConfigError: 校验失败。
    """

    raise NotImplementedError


def _validate_streaming(value: Any) -> object:
    """校验 ``streaming`` 段并构造 :class:`StreamingSpec`。

    异常:
        ConfigError: 缺少 ``content_events`` / ``terminal``，或条件字段非法。
    """

    raise NotImplementedError


def _render_placeholders(template: str, values: dict[str, Any]) -> str:
    """替换模板字符串中的 ``${name}`` 占位符。

    异常:
        ConfigError: 出现白名单外的占位符。
    """

    raise NotImplementedError
