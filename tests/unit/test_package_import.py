"""冒烟测试：验证包结构与关键模块可导入（不启动 Qt、不访问硬件）。"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

CORE_MODULES = [
    "serial_log_analyzer",
    "serial_log_analyzer.core.errors",
    "serial_log_analyzer.core.ports",
    "serial_log_analyzer.core.models.device",
    "serial_log_analyzer.core.models.logs",
    "serial_log_analyzer.core.models.analysis",
    "serial_log_analyzer.core.models.provider",
    "serial_log_analyzer.core.logs.line_framer",
    "serial_log_analyzer.core.logs.parser",
    "serial_log_analyzer.core.logs.preset",
    "serial_log_analyzer.core.logs.preset_loader",
    "serial_log_analyzer.core.logs.pipeline",
    "serial_log_analyzer.core.llm.pointer",
    "serial_log_analyzer.core.llm.adapter",
    "serial_log_analyzer.core.llm.adapter_loader",
    "serial_log_analyzer.core.llm.profile_loader",
    "serial_log_analyzer.core.llm.request",
    "serial_log_analyzer.core.llm.sse",
    "serial_log_analyzer.core.llm.stream",
    "serial_log_analyzer.core.prompts.loader",
    "serial_log_analyzer.core.services.credential_resolver",
    "serial_log_analyzer.core.services.device_session",
    "serial_log_analyzer.core.services.analysis",
]

_CHECK_SCRIPT = f"""
import importlib
import sys

for name in {CORE_MODULES!r}:
    importlib.import_module(name)

loaded = sorted(name for name in sys.modules if name.startswith("PySide6"))
if loaded:
    print("LOADED:" + ",".join(loaded))
    raise SystemExit(1)
"""


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_module_imports(module_name: str) -> None:
    """core 及包根模块应能在无 Qt 环境下导入。"""

    assert importlib.import_module(module_name) is not None


def test_core_does_not_import_pyside() -> None:
    """导入 core 不应把 PySide6 载入 ``sys.modules``（架构硬约束）。

    ``pytest-qt`` 插件会在测试进程内预先载入 PySide6，因此该检查必须在
    独立子进程中进行。
    """

    src = Path(__file__).resolve().parents[2] / "src"
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert result.returncode == 0, f"core 不应依赖 PySide6：{result.stdout}{result.stderr}"
