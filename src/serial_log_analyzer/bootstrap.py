"""组合根（Composition Root）：唯一组装依赖的地方。

职责：
1. 创建 ``QApplication`` 并设置应用元数据；
2. 创建唯一的 ``QNetworkAccessManager``；
3. 构造 ``io`` 适配器（串口 / 网络 / 设置 / 钥匙串 / 资源）；
4. 加载声明式资源（Preset / Adapter / Profile / Prompt）；
5. 构造 ``core`` 服务（``LogPipeline`` / ``DeviceSession`` / ``AnalysisService``）；
6. 构造 ``ui``（控制器 / 窗口 / 组件）并显式注入依赖；
7. 显示主窗口并进入事件循环。

全部依赖通过构造函数显式传入，不引入 DI 框架。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from serial_log_analyzer.core.llm.client import LLMClient

__all__ = ["build_application", "build_llm_client", "main"]


def build_llm_client(
    profile_id: str, manager: object, *, project_root: Path | None = None
) -> LLMClient:
    """组装读取本地 .env 的 LLM 客户端，供应用或独立调用使用。

    参数:
        profile_id: 服务配置 ID，例如 sensenova 或 internlm。
        manager: 调用方持有的唯一 QNetworkAccessManager；需要运行 Qt 事件循环。
        project_root: .env 与仓库资源所在目录；源码运行时默认使用仓库根目录。
    异常:
        ConfigError: .env、资源、服务配置或网络 manager 非法。
        CredentialError: 密钥缺失时在 client.send 调用前抛出。
    """
    from serial_log_analyzer.core.llm.adapter_loader import load_adapter
    from serial_log_analyzer.core.llm.client import LLMClient
    from serial_log_analyzer.core.llm.profile_loader import load_profile
    from serial_log_analyzer.core.llm.request import RequestBuilder
    from serial_log_analyzer.core.services.credential_resolver import CredentialResolver
    from serial_log_analyzer.io.credentials.environment_reader import DotEnvEnvironmentReader
    from serial_log_analyzer.io.llm.qt_http_transport import QtHttpTransport
    from serial_log_analyzer.io.resources import CompositeResourceLoader

    root = project_root if project_root is not None else Path(__file__).resolve().parents[2]
    resources = CompositeResourceLoader.from_environment(root)
    profile = load_profile(resources, profile_id)
    adapter = load_adapter(resources, profile.adapter_id)
    environment = DotEnvEnvironmentReader(root / ".env")
    credentials = CredentialResolver(None, environment)
    return LLMClient(
        RequestBuilder(adapter, profile, credentials), adapter, QtHttpTransport(manager)
    )


def build_application(argv: list[str] | None = None) -> object:
    """组装并返回可运行的应用对象。

    参数:
        argv: 命令行参数；``None`` 时使用 ``sys.argv``。

    返回:
        持有全部对象引用的应用上下文对象（内部定义），包含 ``app`` 与 ``window``。

    异常:
        ConfigError: 内置资源缺失或声明文件非法。
    """

    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """应用入口：组装 → 显示窗口 → 进入事件循环。

    参数:
        argv: 命令行参数；``None`` 时使用 ``sys.argv``。

    返回:
        进程退出码。
    """

    raise NotImplementedError
