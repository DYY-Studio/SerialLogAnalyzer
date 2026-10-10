"""测试全局配置：把 ``src/`` 加入模块搜索路径，便于未安装时直接运行 pytest。"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
