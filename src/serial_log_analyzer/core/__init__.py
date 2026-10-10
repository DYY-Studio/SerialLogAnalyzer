"""core 层：纯 Python 业务逻辑与数据模型。

本包不得导入 PySide6，也不得直接访问文件、串口、网络或系统钥匙串；
所有外部能力通过 :mod:`serial_log_analyzer.core.ports` 中的 ``Protocol`` 声明，
由 ``io`` 层实现后在 ``bootstrap`` 注入。
"""
