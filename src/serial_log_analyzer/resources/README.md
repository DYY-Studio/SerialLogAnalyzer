# 内置资源目录

打包发行时，仓库根目录下的 `presets/`、`providers/`、`prompts/` 会被复制到本目录
（见 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel.force-include]`）。

运行时由 `io/resources.py` 的 `CompositeResourceLoader` 按以下顺序查找，前者优先：

1. 用户配置目录 `~/.config/SerialLogAnalyzer/`
2. 仓库根目录（开发运行）
3. 本目录（安装 / 打包运行）

请勿手工编辑本目录下的文件：它们是从仓库根目录复制而来，应以仓库中的源文件为准。
