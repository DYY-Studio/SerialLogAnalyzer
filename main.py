#!/usr/bin/env python3
"""SerialLogAnalyzer 传统启动入口：``python main.py``。

将 ``src/`` 加入 ``sys.path`` 后调用包入口，便于不安装依赖的情况下直接运行。
安装后也可使用 console script：``serial-log-analyzer``。
"""

from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap() -> int:
    """把 ``src/`` 注入模块搜索路径并启动应用。"""
    src = Path(__file__).resolve().parent / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from serial_log_analyzer.bootstrap import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_bootstrap())
