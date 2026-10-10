"""诊断命令行的集成测试：真实资源 + 真实报告渲染（不启动 Qt）。"""

from __future__ import annotations

import json

import serial_log_analyzer.diagnostics.__main__ as cli
from serial_log_analyzer.core.errors import ConfigError


class BrokenPresetLoader:
    """只提供一个坏 Preset 的资源加载器，用于验证退出码契约。"""

    roots = ("<内存>",)

    def read_text(self, relative_path: str) -> str:
        raise ConfigError(relative_path)

    def list_files(self, relative_dir: str, pattern: str) -> list[str]:
        if relative_dir == "presets/logs":
            return ["presets/logs/broken.yaml"]
        return []


def test_cli_prints_report_and_returns_zero(capsys) -> None:
    code = cli.main([])

    out = capsys.readouterr().out
    assert code == 0
    assert "SerialLogAnalyzer 诊断报告" in out
    assert "配置错误    : 无" in out
    assert "资源根目录  :" in out
    assert "Preset（2）:" in out


def test_cli_json_output_is_machine_readable(capsys) -> None:
    code = cli.main(["--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["config_errors"] == []
    assert len(payload["presets"]) == 2
    assert {item.split("（", 1)[0] for item in payload["presets"]} == {
        "hi3861-default",
        "hi3861-timestamped",
    }


def test_cli_export_writes_report_file(tmp_path, capsys) -> None:
    target = tmp_path / "nested" / "report.txt"

    code = cli.main(["--export", str(target), "--no-log-tail"])

    assert code == 0
    assert target.is_file()
    assert "SerialLogAnalyzer 诊断报告" in target.read_text(encoding="utf-8")
    assert "已写入：" in capsys.readouterr().out


def test_cli_returns_one_on_broken_configuration(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "CompositeResourceLoader", _patched(BrokenPresetLoader))

    code = cli.main(["--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert any(item.startswith("Preset：") for item in payload["config_errors"])


def _patched(loader_type):
    """返回一个替换 ``CompositeResourceLoader`` 的替身类（只用 ``from_environment``）。"""

    class _Replacement:
        @classmethod
        def from_environment(cls, repo_root=None):
            return loader_type()

    return _Replacement
