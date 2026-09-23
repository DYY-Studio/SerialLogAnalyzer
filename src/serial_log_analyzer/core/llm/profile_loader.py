"""Provider Profile 加载与校验。

Profile 描述“调用哪一个模型服务”：``base_url``、``model``、凭据引用与流式开关；
Adapter 描述“如何调用这类接口”。两者通过 ``adapter_id`` 关联。
"""

from __future__ import annotations

from typing import Any

from serial_log_analyzer.core.models.provider import ProviderProfile
from serial_log_analyzer.core.ports import ResourceLoader

__all__ = ["load_profile", "load_profiles"]

_PROFILE_DIR = "providers/profiles"


def load_profile(loader: ResourceLoader, profile_id: str) -> ProviderProfile:
    """按 ID 加载单个 Profile。

    参数:
        loader: 资源加载器。
        profile_id: Profile 标识，需满足 ``[a-z][a-z0-9-]*``。

    返回:
        校验完成的 :class:`ProviderProfile`。

    异常:
        ConfigError: 文件缺失、YAML 非法、未知字段、缺少必填字段、``base_url``
            非法或凭据段不合法。
    """

    raise NotImplementedError


def load_profiles(loader: ResourceLoader) -> list[ProviderProfile]:
    """加载全部 Profile，用户目录覆盖同 ID 的内置 Profile。"""

    raise NotImplementedError


def _parse_credential(raw: Any) -> ProviderProfile:
    """解析 ``credential`` 段。

    支持的三种形态::

        {kind: keyring, name: <account>}
        {kind: environment, env_var: <VAR>}
        {kind: runtime}

    异常:
        ConfigError: ``kind`` 未知或缺少对应必填字段。
    """

    raise NotImplementedError
