"""测试全局配置：把 ``src/`` 加入模块搜索路径，便于未安装时直接运行 pytest。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True, scope="session")
def isolated_config_home(tmp_path_factory):
    """把用户配置目录指到临时目录：测试不得写进真实配置目录与应用日志文件。"""

    home = tmp_path_factory.mktemp("sla-config-home")
    previous = os.environ.get("SLA_CONFIG_HOME")
    os.environ["SLA_CONFIG_HOME"] = str(home)
    yield
    if previous is None:
        os.environ.pop("SLA_CONFIG_HOME", None)
    else:
        os.environ["SLA_CONFIG_HOME"] = previous
