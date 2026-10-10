"""资源加载：按优先级合并「用户配置目录 / 仓库根 / 包内资源」三处声明式资源。

职责：
    实现 ``core/ports.py`` 的 ``ResourceLoader`` 协议，只提供“按相对路径读取 / 列举”，
    调用方（preset、adapter、profile、prompt 加载器）不需要感知文件系统布局。
    同名文件以列表中靠前的根目录为准，实现“用户配置覆盖内置资源”。

参数：
    roots: 按优先级从高到低排列的资源根目录列表。

异常：
    ``ConfigError``：路径为空、为绝对路径、包含 ``..`` 逃逸，或资源不存在 / 不可读。

示例：
    >>> loader = CompositeResourceLoader.from_environment()
    >>> loader.list_files("presets/logs", "*.yaml")       # doctest: +SKIP
    ['presets/logs/hi3861-default.yaml']
"""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.io.paths import package_resources_dir, user_config_dir
from serial_log_analyzer.io.paths import repo_root as _detect_repo_root

__all__ = ["CompositeResourceLoader"]


def _normalize(relative_path: str) -> str:
    """把外部传入的相对路径规范化为 POSIX 形式，并拒绝越界路径。

    参数：
        relative_path: 形如 ``presets/logs/foo.yaml`` 的相对路径。

    返回：
        规范化后的相对路径字符串（``.`` 会被保留为 ``"."``）。

    异常：
        ConfigError: 路径为空、为绝对路径或包含 ``..``。
    """
    text = str(relative_path).strip().replace("\\", "/")
    if not text:
        raise ConfigError("资源路径不能为空")
    candidate = PurePosixPath(text)
    if candidate.is_absolute() or (len(text) > 1 and text[1] == ":"):
        raise ConfigError(f"资源路径必须是相对路径：{relative_path}")
    if ".." in candidate.parts:
        raise ConfigError(f"资源路径不得包含 '..'：{relative_path}")
    return str(candidate)


class CompositeResourceLoader:
    """在多个根目录中按优先级查找声明式资源的 ``ResourceLoader`` 实现。

    参数：
        roots: 资源根目录，按优先级从高到低；调用方负责保证目录存在性（缺失的根会被跳过）。
    """

    def __init__(self, roots: list[Path]) -> None:
        if not roots:
            raise ConfigError("资源根目录列表不能为空")
        self._roots: list[Path] = [Path(root) for root in roots]

    @classmethod
    def from_environment(cls, repo_root: Path | None = None) -> CompositeResourceLoader:
        """按运行环境组装默认根目录列表：用户配置目录 → 仓库根 → 包内资源。

        参数：
            repo_root: 显式指定仓库根目录；为 ``None`` 时自动探测（安装运行时自动跳过）。

        返回：
            组装好的 ``CompositeResourceLoader``。
        """
        roots: list[Path] = [user_config_dir()]
        root = Path(repo_root) if repo_root is not None else _detect_repo_root()
        if root is not None:
            roots.append(root)
        roots.append(package_resources_dir())
        deduped: list[Path] = []
        for item in roots:
            if item not in deduped:
                deduped.append(item)
        return cls(deduped)

    @property
    def roots(self) -> tuple[Path, ...]:
        """按优先级排列的资源根目录（只读副本）。"""
        return tuple(self._roots)

    def describe_roots(self) -> str:
        """把根目录列表渲染为单行中文说明，用于错误信息与诊断报告。"""
        return " → ".join(str(root) for root in self._roots)

    def resolve(self, relative_path: str) -> Path:
        """返回资源在磁盘上的实际路径。

        参数：
            relative_path: 相对资源路径，例如 ``providers/profiles/openai.yaml``。

        返回：
            命中文件的绝对路径。

        异常：
            ConfigError: 路径非法，或在所有根目录中都找不到该文件。
        """
        relative = _normalize(relative_path)
        for root in self._roots:
            candidate = root / relative
            if candidate.is_file():
                return candidate
        raise ConfigError(f"未找到资源 {relative}；已查找：{self.describe_roots()}")

    def read_text(self, relative_path: str) -> str:
        """读取资源文本内容（UTF-8）。

        参数：
            relative_path: 相对资源路径。

        返回：
            文件文本内容。

        异常：
            ConfigError: 资源不存在或不可读。
        """
        path = self.resolve(relative_path)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"读取资源失败 {path}：{exc}") from exc

    def list_files(self, relative_dir: str, pattern: str) -> list[str]:
        """列举各根目录下 ``relative_dir`` 中匹配 ``pattern`` 的文件。

        跨根同名文件只保留优先级最高的一份；返回值始终是相对路径，且已排序，
        因此调用方可以稳定地把文件名当作资源 id。

        参数：
            relative_dir: 目录相对路径，例如 ``presets/logs``。
            pattern: ``fnmatch`` 通配模式，例如 ``*.yaml``。

        返回：
            形如 ``presets/logs/foo.yaml`` 的相对路径列表（升序、去重）。

        异常：
            ConfigError: 目录相对路径非法。
        """
        normalized = _normalize(relative_dir)
        directory = "" if normalized == "." else normalized
        prefix = f"{directory}/" if directory else ""
        found: dict[str, str] = {}
        for root in self._roots:
            base = root / directory if directory else root
            if not base.is_dir():
                continue
            try:
                entries = sorted(base.iterdir())
            except OSError as exc:
                raise ConfigError(f"读取资源目录失败 {base}：{exc}") from exc
            for entry in entries:
                if entry.is_file() and fnmatch.fnmatch(entry.name, pattern):
                    found.setdefault(entry.name, f"{prefix}{entry.name}")
        return sorted(found.values())
