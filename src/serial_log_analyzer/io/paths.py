"""运行时路径解析：用户配置目录、日志目录、导出目录与资源根目录。

职责：
    集中定义“文件放在哪里”的规则，避免各模块各自拼接路径。所有路径都可通过环境变量
    覆盖，便于 CI、便携模式与测试中重定向。

环境变量：
    ``SLA_CONFIG_HOME``  用户配置根目录（覆盖默认用户目录）。
    ``SLA_EXPORT_DIR``   日志导出默认目录。

异常：
    本模块只做路径计算，不抛业务异常。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "APP_DIR_NAME",
    "default_export_dir",
    "package_resources_dir",
    "repo_root",
    "user_config_dir",
    "user_log_dir",
]

APP_DIR_NAME = "SerialLogAnalyzer"


def repo_root() -> Path | None:
    """返回源码直跑时的仓库根目录；安装运行时返回 ``None``。

    判定方式：从本文件上溯到 ``src`` 的父目录，并校验其下同时存在 ``src/`` 与 ``presets/``，
    避免把 site-packages 之类的目录误判成仓库根。

    返回：
        仓库根目录，或 ``None``（当前不是源码运行）。
    """
    src_dir = Path(__file__).resolve().parents[2]
    root = src_dir.parent
    if (root / "src").is_dir() and (root / "presets").is_dir():
        return root
    return None


def package_resources_dir() -> Path:
    """返回包内随发行版打包的资源目录 ``serial_log_analyzer/resources``。"""
    return Path(__file__).resolve().parents[1] / "resources"


def user_config_dir() -> Path:
    """返回用户配置根目录（不一定存在，写入方负责创建）。

    优先级：``SLA_CONFIG_HOME`` → Windows ``%APPDATA%/SerialLogAnalyzer`` →
    其他平台 ``~/.config/SerialLogAnalyzer``。
    """
    override = os.environ.get("SLA_CONFIG_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME


def user_log_dir() -> Path:
    """返回应用日志目录：``<用户配置目录>/logs``。"""
    return user_config_dir() / "logs"


def default_export_dir() -> Path:
    """返回日志导出的默认目录。

    优先级：``SLA_EXPORT_DIR`` → 源码运行时的 ``<仓库根>/exports``（已被 .gitignore 忽略）→
    安装运行时的 ``~/SerialLogAnalyzer/exports``。
    """
    override = os.environ.get("SLA_EXPORT_DIR")
    if override:
        return Path(override).expanduser()
    root = repo_root()
    if root is not None:
        return root / "exports"
    return Path.home() / APP_DIR_NAME / "exports"
