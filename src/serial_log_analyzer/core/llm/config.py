"""LLM 声明的通用校验，不读取外部资源。"""

from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlsplit

import yaml

from serial_log_analyzer.core.errors import ConfigError, PointerError
from serial_log_analyzer.core.llm.pointer import parse_pointer


def mapping(value: Any, allowed: set[str], required: set[str] = frozenset()) -> dict:
    """校验映射字段；未知、缺失或非字符串键抛出 ConfigError。"""
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ConfigError("配置必须是字符串键的映射")
    if value.keys() - allowed or required - value.keys():
        raise ConfigError(
            "配置字段未知或缺失："
            + ", ".join(sorted((value.keys() - allowed) | (required - value.keys())))
        )
    return value


def text(value: Any) -> str:
    """校验非空字符串；不合法时抛出 ConfigError。"""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("字段必须是非空字符串")
    return value


def identifier(value: Any) -> str:
    """校验资源 ID；不合法时抛出 ConfigError。"""
    if not re.fullmatch(r"[a-z][a-z0-9-]*", text(value)):
        raise ConfigError("资源 ID 格式非法")
    return value


def pointer(value: Any) -> str:
    """校验指针；语法错误转换为 ConfigError。"""
    if not isinstance(value, str):
        raise ConfigError("指针必须是字符串")
    try:
        parse_pointer(value)
    except PointerError as exc:
        raise ConfigError("指针语法非法") from exc
    return value


def boolean(value: Any) -> bool:
    """校验布尔字段；不合法时抛出 ConfigError。"""
    if type(value) is not bool:
        raise ConfigError("字段必须是布尔值")
    return value


def timeout(value: Any) -> float:
    """校验有限正数超时；不合法时抛出 ConfigError。"""
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ConfigError("超时必须是有限正数")
    return float(value)


def base_url(value: Any) -> str:
    """校验无凭据、查询或片段的 HTTP(S) 基地址。"""
    value = text(value)
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ConfigError("服务地址非法") from exc
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or any(c.isspace() for c in value)
        or port == 0
    ):
        raise ConfigError("服务地址必须是无凭据的 HTTP(S) URL")
    return value.rstrip("/")


def endpoint(value: Any) -> str:
    """校验相对服务端点，保留查询参数。"""
    value = text(value)
    if (
        "://" in value
        or value.startswith("//")
        or "#" in value
        or any(c.isspace() for c in value)
        or ".." in value.split("/")
    ):
        raise ConfigError("端点必须为相对路径")
    if "$" in value.replace("${model}", ""):
        raise ConfigError("端点包含未知占位符")
    return value


def document(raw: str) -> dict:
    """安全解析 YAML 映射，拒绝重复键；不合法时抛出 ConfigError。"""

    class UniqueLoader(yaml.SafeLoader):
        pass

    def construct(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str) or key in result:
                raise ConfigError("YAML 键重复或不是字符串")
            result[key] = loader.construct_object(value_node)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct)
    try:
        result = yaml.load(raw, Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise ConfigError("YAML 格式非法") from exc
    if not isinstance(result, dict):
        raise ConfigError("YAML 顶层必须为映射")
    return result
