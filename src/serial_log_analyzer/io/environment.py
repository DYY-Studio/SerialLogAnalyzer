"""环境变量读取适配：``core.ports.EnvironmentReader`` 的实现。

- :class:`ProcessEnvironment`：只读进程环境变量；
- :class:`DotEnvEnvironmentReader`：进程环境优先，缺失时读取指定的本地 ``.env`` 文件。

``.env`` 只是 ``kind: environment`` 的文件来源，进程环境里显式设置的值始终优先。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from serial_log_analyzer.core.errors import ConfigError

__all__ = ["DotEnvEnvironmentReader", "ProcessEnvironment"]


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


class DotEnvEnvironmentReader:
    """实现 ``EnvironmentReader``；进程环境优先，缺失时读取 ``dotenv_path``。

    参数：
        dotenv_path: 显式指定的本地文件，缺失时按空配置处理，不搜索上级目录。
        environ: 可注入环境映射用于测试；``None`` 使用 ``os.environ``。
    异常:
        ConfigError: 文件不可读、编码非法、赋值格式错误或变量重复。
    """

    def __init__(self, dotenv_path: Path, *, environ: Mapping[str, str] | None = None) -> None:
        self._environment = os.environ if environ is None else environ
        self._values = self._read(dotenv_path)

    def get(self, name: str) -> str | None:
        """读取变量；进程环境中显式设置的值（含空值）覆盖文件值。"""
        return self._environment.get(name) if name in self._environment else self._values.get(name)

    @staticmethod
    def _read(path: Path) -> dict[str, str]:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError) as exc:
            raise ConfigError("本地 .env 无法读取，请检查文件权限和 UTF-8 编码") from exc
        values: dict[str, str] = {}
        for number, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, sep, value = line.partition("=")
            name, value = name.strip(), value.strip()
            if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in values:
                raise ConfigError(f".env 第 {number} 行赋值非法或重复")
            if value.startswith(("'", '"')):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 0 or (
                    value[end + 1 :].strip() and not value[end + 1 :].strip().startswith("#")
                ):
                    raise ConfigError(f".env 第 {number} 行引号非法")
                value = value[1:end]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            if "\x00" in value:
                raise ConfigError(f".env 第 {number} 行包含非法字符")
            # 不执行 shell、不展开 ${...}，密钥中的字符保持原样。
            values[name] = value
        return values
