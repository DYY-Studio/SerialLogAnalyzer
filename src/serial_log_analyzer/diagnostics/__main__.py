"""诊断报告命令行入口：``python -m serial_log_analyzer.diagnostics``。

用法：
    ``python -m serial_log_analyzer.diagnostics``                打印中文诊断报告
    ``python -m serial_log_analyzer.diagnostics --json``         以 JSON 输出
    ``python -m serial_log_analyzer.diagnostics --export PATH``  同时写入文件

退出码：
    0 表示配置全部加载成功；1 表示存在配置错误或导出失败，可直接用于 CI 的资源校验。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from serial_log_analyzer.core.errors import AppError
from serial_log_analyzer.diagnostics.app_logging import (
    configure_logging,
    current_log_file,
    get_logger,
)
from serial_log_analyzer.diagnostics.report import collect, export, to_json
from serial_log_analyzer.io.credentials.keyring_store import KeyringStoreAdapter
from serial_log_analyzer.io.resources import CompositeResourceLoader

__all__ = ["main"]

_logger = get_logger("diagnostics")


def _probe_keyring() -> bool:
    """探测系统钥匙串是否可用。

    探测本身只是“尽力而为”：任何失败都视为不可用，并记录一条告警日志，
    由诊断报告如实展示，不影响其余诊断信息的采集。
    """
    try:
        return KeyringStoreAdapter().available
    except Exception as exc:  # noqa: BLE001 - 探测失败等同于“不可用”
        _logger.warning("钥匙串探测失败，按不可用处理：%s", exc)
        return False


def main(argv: list[str] | None = None) -> int:
    """采集并打印诊断报告。

    参数：
        argv: 命令行参数；``None`` 时读取 ``sys.argv[1:]``。

    返回：
        进程退出码（0 表示配置无错误）。
    """
    parser = argparse.ArgumentParser(
        prog="python -m serial_log_analyzer.diagnostics",
        description="输出 SerialLogAnalyzer 的运行环境与配置诊断报告。",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    parser.add_argument(
        "--export",
        metavar="PATH",
        help="把报告写入文件；PATH 可以是文件路径或已存在的目录",
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        help="在报告中展示的应用日志文件路径（默认取当前日志配置）",
    )
    parser.add_argument("--no-log-tail", action="store_true", help="不采集日志末尾内容")
    args = parser.parse_args(argv)

    configure_logging()
    loader = CompositeResourceLoader.from_environment()
    log_file = Path(args.log_file) if args.log_file else current_log_file()
    report = collect(
        loader,
        keyring_available=_probe_keyring(),
        log_file=log_file,
        log_tail_lines=0 if args.no_log_tail else 20,
    )

    print(to_json(report) if args.json else report.render())

    if args.export:
        try:
            print(f"已写入：{export(report, args.export)}")
        except AppError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
