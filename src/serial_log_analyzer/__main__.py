"""允许 ``python -m serial_log_analyzer`` 启动应用。"""

from serial_log_analyzer.bootstrap import main

if __name__ == "__main__":
    raise SystemExit(main())
