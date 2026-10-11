"""环境变量读取适配：``core.ports.EnvironmentReader`` 的进程环境实现。"""

from __future__ import annotations

import os

__all__ = ["ProcessEnvironment"]


class ProcessEnvironment:
    """从 ``os.environ`` 读取环境变量。"""

    def get(self, name: str) -> str | None:
        """读取环境变量；不存在或为空时返回 ``None``。

        参数：
            name: 环境变量名。
        """
        value = os.environ.get(name)
        if value is None or not value.strip():
            return None
        return value
