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

__all__ = ["CompositeResourceLoader"]


class CompositeResourceLoader:
    """多来源资源加载器。

    参数:
        roots: 按优先级排列的资源根目录（高优先级在前）。
    """

    def __init__(self, roots: list[Path]) -> None:
        raise NotImplementedError

    @classmethod
    def from_environment(cls, repo_root: Path | None = None) -> CompositeResourceLoader:
        """按运行时环境构造默认加载器。

        参数:
            repo_root: 开发运行时的仓库根目录；``None`` 时尝试从包位置推断。
        """

        raise NotImplementedError

    def read_text(self, relative_path: str) -> str:
        """读取文本资源。

        异常:
            ConfigError: 所有来源均不存在该资源，或读取失败。
        """

        raise NotImplementedError

    def list_files(self, relative_dir: str, pattern: str) -> list[str]:
        """列出各来源中匹配的文件，合并去重（同名保留高优先级来源）。"""

        raise NotImplementedError

    def resolve(self, relative_path: str) -> Path:
        """返回实际命中的绝对路径，用于错误提示与展示。"""

        raise NotImplementedError
