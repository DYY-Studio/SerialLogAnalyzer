"""ui 层：PySide6 界面与控制器。

职责边界：只负责展示与用户交互，通过 ``core`` 服务获取数据；
不解析日志、不发送 LLM 请求、不直接操作 ``QSerialPort`` / ``QNetworkAccessManager``。
"""

from serial_log_analyzer.ui.main_window import MainWindow

__all__ = ["MainWindow"]
