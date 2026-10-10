"""统一的错误体系。

``io`` 层负责把外部库（Qt、keyring、系统）的错误翻译为本模块中的异常类型；
``ui`` 层决定最终以何种形式呈现给用户（状态栏 / 行内提示 / 对话框）。

约定：
- 所有业务异常继承 :class:`AppError`，避免抛出裸 ``Exception``。
- 错误消息面向用户，使用中文；如需结构化信息，在子类上增加属性。
"""

from __future__ import annotations

__all__ = [
    "AppError",
    "ConfigError",
    "CredentialError",
    "HttpStatusError",
    "NetworkError",
    "NetworkTimeoutError",
    "PointerError",
    "PresetError",
    "ProviderError",
    "ResponseParseError",
    "SerialConnectionError",
    "SerialError",
    "SerialWriteError",
]


class AppError(Exception):
    """应用内所有可预期错误的基类。"""


class ConfigError(AppError):
    """配置（设置项、资源声明、命令行参数）不合法或缺失。"""


class SerialError(AppError):
    """串口相关错误的基类。"""


class SerialConnectionError(SerialError):
    """打开、保持或关闭串口失败。"""


class SerialWriteError(SerialError):
    """向串口写入数据失败。"""


class NetworkError(AppError):
    """网络请求相关错误的基类。"""


class NetworkTimeoutError(NetworkError):
    """请求超时。"""


class HttpStatusError(NetworkError):
    """服务端返回非成功状态码。

    参数:
        status: HTTP 状态码。
        body: 可选的响应正文片段，用于诊断。
    """

    def __init__(self, status: int, body: str = "") -> None:
        super().__init__(f"HTTP 请求失败：状态码 {status}{'：' + body if body else ''}")
        self.status = status
        self.body = body


class ProviderError(AppError):
    """LLM Provider 声明或调用失败（缺少凭据、Adapter 未声明某项能力等）。"""


class ResponseParseError(AppError):
    """LLM 响应无法按声明的规则解析（JSON 非法、指针不匹配、类型不符）。"""


class PointerError(AppError):
    """扩展 JSON Pointer 解析或求值失败。"""


class PresetError(AppError):
    """日志 Preset 加载、校验或编译失败。"""


class CredentialError(AppError):
    """凭据读取、写入或删除失败（含钥匙串不可用）。"""
