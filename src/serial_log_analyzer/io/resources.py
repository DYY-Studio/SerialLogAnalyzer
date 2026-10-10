"""资源加载适配：仓库目录 / 用户配置目录 / 打包内置资源的统一读取。

实现 :class:`serial_log_analyzer.core.ports.ResourceLoader`。

查找顺序（前者优先）::

    用户配置目录  ~/.config/SerialLogAnalyzer/
    仓库目录      <repo>/            （开发运行时）
    包内资源      serial_log_analyzer/resources/  （安装 / 打包运行时）

同一 ``preset_id`` / ``profile_id`` 出现在多个来源时，高优先级来源覆盖低优先级。
缺失文件统一翻译为 :class:`ConfigError`。
"""

from __future__ import annotations

from pathlib import Path

from serial_log_analyzer.core.errors import ConfigError

__all__ = ["CompositeResourceLoader"]


class CompositeResourceLoader:
    """多来源资源加载器。

    参数:
        roots: 按优先级排列的资源根目录（高优先级在前）。
    """

    def __init__(self, roots: list[Path]) -> None:
        self._roots = [root.resolve() for root in roots]

    @classmethod
    def from_environment(cls, repo_root: Path | None = None) -> CompositeResourceLoader:
        """按运行时环境构造默认加载器。

        参数:
            repo_root: 开发运行时的仓库根目录；``None`` 时尝试从包位置推断。
        """

        roots = [Path.home() / ".config" / "SerialLogAnalyzer"]
        candidate = repo_root if repo_root is not None else Path(__file__).resolve().parents[3]
        if repo_root is not None or (candidate / "pyproject.toml").is_file():
            roots.append(candidate)
        roots.append(Path(__file__).resolve().parents[1] / "resources")
        return cls(roots)

    def read_text(self, relative_path: str) -> str:
        """读取文本资源。

        异常:
            ConfigError: 所有来源均不存在该资源，或读取失败。
        """

        path = self.resolve(relative_path)
        try:
            return path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise ConfigError(f"资源不可读：{relative_path}") from exc

    def list_files(self, relative_dir: str, pattern: str) -> list[str]:
        """列出各来源中匹配的文件，合并去重（同名保留高优先级来源）。"""

        self._validate_path(relative_dir)
        if "/" in pattern or "\\" in pattern or pattern in {".", ".."}:
            raise ConfigError("资源文件模式不得包含路径")
        found = set()
        for root in self._roots:
            directory = self._contained(root, relative_dir)
            try:
                for path in directory.glob(pattern):
                    if path.is_file():
                        self._contained(root, path.relative_to(root).as_posix())
                        found.add(path.relative_to(root).as_posix())
            except OSError as exc:
                raise ConfigError(f"资源目录不可读：{relative_dir}") from exc
        return sorted(found)

    def resolve(self, relative_path: str) -> Path:
        """返回实际命中的绝对路径，用于错误提示与展示。"""

        self._validate_path(relative_path)
        for root in self._roots:
            path = self._contained(root, relative_path)
            if path.is_file():
                return path
        raise ConfigError(f"资源不存在：{relative_path}")

    @staticmethod
    def _validate_path(relative_path: str) -> None:
        path = Path(relative_path)
        if not relative_path or path.is_absolute() or path.drive or ".." in path.parts:
            raise ConfigError("资源路径必须为不含上级引用的相对路径")

    @staticmethod
    def _contained(root: Path, relative_path: str) -> Path:
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ConfigError("资源路径超出资源根目录")
        return path
