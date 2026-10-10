"""io 层：core 抽象接口的具体实现（Qt / 系统适配）。

本包是唯一允许直接接触 ``QSerialPort``、``QNetworkAccessManager``、``QSettings``
与 ``keyring`` 的地方；实现只做适配与类型转换，不含业务决策。
"""
