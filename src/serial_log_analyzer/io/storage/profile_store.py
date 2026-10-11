"""用户 Profile 存储：把自定义 Provider Profile 写入用户配置目录。

只写用户目录（``<用户配置目录>/providers/profiles/*.yaml``），不修改仓库内置文件；
写入采用「临时文件 + 原子替换」，避免中途失败留下半截 YAML。
"""

from __future__ import annotations

import os
import re
from contextlib import suppress
from pathlib import Path

from serial_log_analyzer.core.errors import AppError, ConfigError
from serial_log_analyzer.core.llm.profile_writer import dump_profile
from serial_log_analyzer.core.models.provider import ProviderProfile
from serial_log_analyzer.io.paths import user_config_dir

__all__ = ["ProfileStore"]

_PROFILE_DIR = ("providers", "profiles")
_PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class ProfileStore:
    """用户 Profile 的文件存储。

    参数:
        root: 用户配置根目录；缺省为 :func:`serial_log_analyzer.io.paths.user_config_dir`。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else user_config_dir()

    @property
    def root(self) -> Path:
        """用户配置根目录。"""
        return self._root

    def directory(self) -> Path:
        """返回 Profile 目录 ``<root>/providers/profiles``（不一定存在）。"""
        return self._root.joinpath(*_PROFILE_DIR)

    def path_for(self, profile_id: str) -> Path:
        """返回指定 Profile 的文件路径。

        异常:
            ConfigError: ``profile_id`` 不满足 ``[a-z][a-z0-9-]*``。
        """

        if not _PROFILE_ID_RE.match(profile_id):
            raise ConfigError(f"非法 profile_id：{profile_id}")
        return self.directory() / f"{profile_id}.yaml"

    def exists(self, profile_id: str) -> bool:
        """用户目录中是否已存在该 Profile。"""
        return self.path_for(profile_id).is_file()

    def load_text(self, profile_id: str) -> str | None:
        """读取用户目录中的 Profile 原文；不存在返回 ``None``。

        异常:
            AppError: 文件存在但读取失败。
        """

        path = self.path_for(profile_id)
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AppError(f"读取 Profile 失败：{path}（{exc.strerror or exc}）") from exc

    def save(self, profile: ProviderProfile) -> Path:
        """写入（或覆盖）用户目录中的 Profile。

        参数:
            profile: 待保存的 Profile。

        返回:
            实际写入的文件路径。

        异常:
            ConfigError: Profile 内容不合法（由 :func:`dump_profile` 校验）。
            AppError: 目录创建或写入失败。
        """

        text = dump_profile(profile)
        path = self.path_for(profile.profile_id)
        tmp_path = path.with_name(f"{path.name}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(text, encoding="utf-8", newline="\n")
            os.replace(tmp_path, path)
        except OSError as exc:
            _remove_quietly(tmp_path)
            raise AppError(f"保存 Profile 失败：{path}（{exc.strerror or exc}）") from exc
        return path

    def delete(self, profile_id: str) -> bool:
        """删除用户目录中的 Profile。

        返回:
            ``True`` 表示确实删除了文件，``False`` 表示原本不存在。

        异常:
            AppError: 删除失败。
        """

        path = self.path_for(profile_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise AppError(f"删除 Profile 失败：{path}（{exc.strerror or exc}）") from exc
        return True


def _remove_quietly(path: Path) -> None:
    """清理临时文件；失败时保持静默（原始错误更重要）。"""
    with suppress(OSError):
        path.unlink(missing_ok=True)
