"""
Demo 启动文件 - 用模拟数据展示 UI 效果
不依赖 core/io 层，可独立运行
"""

import sys
import time
import random
import types
from enum import Enum
from dataclasses import dataclass, field

# 加入短路径（解决 Windows 长路径问题）
sys.path.insert(0, r"C:\pylibs")
# 加入项目根目录
PROJECT_ROOT = r"C:\Users\Administrator\Doubao\chats\2026-10-10\new-chat\SerialLogAnalyzer"
sys.path.insert(0, PROJECT_ROOT)

# ============================================================
# Mock core 模块（在导入 ui 之前注入）
# ============================================================

# --- models.device ---
class DeviceConnectionState(Enum):
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    ERROR = 3

class Parity(Enum):
    NONE = 0
    EVEN = 1
    ODD = 1

class StopBits(Enum):
    ONE = 0

class FlowControl(Enum):
    NONE = 0

@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int = 115200
    data_bits: int = 8
    parity: object = None
    stop_bits: int = 1
    flow_control: object = None

@dataclass(frozen=True)
class SerialPortInfo:
    name: str
    description: str = ""
    manufacturer: str = ""
    serial_number: str = ""

# --- models.logs ---
class LogLevel(Enum):
    VERBOSE = 0
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    UNKNOWN = 5

@dataclass
class LogEntry:
    sequence: int
    received_at: float
    level: LogLevel
    message: str
    raw: str
    device_time: str = None
    module: str = None
    continuation: bool = False
    extra: dict = field(default_factory=dict)

# --- models.analysis ---
class AnalysisMode(Enum):
    SINGLE = 0
    CHAT = 1

class ContextSelector(Enum):
    SELECTED = 0
    SELECTED_WITH_NEIGHBORS = 1
    RECENT = 2
    ERRORS_ONLY = 3
    MANUAL = 4

class AnalysisState(Enum):
    IDLE = 0
    STREAMING = 1
    DONE = 2
    ERROR = 3

@dataclass
class AnalysisRequest:
    mode: AnalysisMode = None
    selector: ContextSelector = None
    user_input: str = ""
    goal_id: str = ""

@dataclass
class AnalysisResult:
    content: str = ""
    reasoning: str = ""
    usage: dict = field(default_factory=dict)
    state: AnalysisState = AnalysisState.IDLE

# --- errors ---
class AppError(Exception):
    pass

class SerialConnectionError(AppError):
    pass

# --- services ---
class DeviceSessionHandlers:
    def __init__(self, on_update=None, on_state=None, on_error=None, on_command_reply=None):
        self.on_update = on_update
        self.on_state = on_state
        self.on_error = on_error
        self.on_command_reply = on_command_reply

class DeviceSession:
    def __init__(self, *args, **kwargs):
        pass
    def set_handlers(self, h):
        pass

class AnalysisService:
    def __init__(self, *args, **kwargs):
        self.on_stream_chunk = None
        self.on_state_changed = None
        self.on_error = None
    def analyze(self, *args, **kwargs):
        pass
    def reset_session(self):
        pass

# --- 注入到 sys.modules ---
def _mock_module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

# serial_log_analyzer 包
_mock_module("serial_log_analyzer")

# models
_mock_module("serial_log_analyzer.core")
_mock_module("serial_log_analyzer.core.models")
sys.modules["serial_log_analyzer.core.models.device"] = types.SimpleNamespace(
    DeviceConnectionState=DeviceConnectionState,
    SerialConfig=SerialConfig,
    SerialPortInfo=SerialPortInfo,
    Parity=Parity,
    StopBits=StopBits,
    FlowControl=FlowControl,
)
sys.modules["serial_log_analyzer.core.models.logs"] = types.SimpleNamespace(
    LogLevel=LogLevel,
    LogEntry=LogEntry,
)
sys.modules["serial_log_analyzer.core.models.analysis"] = types.SimpleNamespace(
    AnalysisMode=AnalysisMode,
    ContextSelector=ContextSelector,
    AnalysisState=AnalysisState,
    AnalysisRequest=AnalysisRequest,
    AnalysisResult=AnalysisResult,
)

# services
_mock_module("serial_log_analyzer.core.services")
sys.modules["serial_log_analyzer.core.services.device_session"] = types.SimpleNamespace(
    DeviceSession=DeviceSession,
    DeviceSessionHandlers=DeviceSessionHandlers,
)
sys.modules["serial_log_analyzer.core.services.analysis"] = types.SimpleNamespace(
    AnalysisService=AnalysisService,
)

# errors
_mock_module("serial_log_analyzer.core.errors")
sys.modules["serial_log_analyzer.core.errors"] = types.SimpleNamespace(
    AppError=AppError,
    SerialConnectionError=SerialConnectionError,
)

# ============================================================
# 现在可以安全导入 ui 了
# ============================================================

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QStatusBar, QLabel, QLineEdit, QPushButton, QComboBox
)
from PySide6.QtCore import Qt, QTimer

from ui.widgets.serial_toolbar import SerialToolbar
from ui.widgets.log_view import LogView
from ui.widgets.analysis_panel import AnalysisPanel
from ui.models.log_table_model import LogTableModel
from ui.models.log_filter_model import LogFilterModel


# 模拟日志模板
LOG_TEMPLATES = [
    (LogLevel.INFO, "kernel", "Hello OpenHarmony! Hi3861 boot completed"),
    (LogLevel.DEBUG, "wifi", "WiFi connecting to AP: TestNet"),
    (LogLevel.INFO, "wifi", "WiFi connected, IP: 192.168.1.100"),
    (LogLevel.INFO, "task", "Task scheduler started, 4 tasks running"),
    (LogLevel.DEBUG, "sensor", "Temperature read: 25.3 C"),
    (LogLevel.WARN, "mem", "Low memory warning: free heap = 12KB"),
    (LogLevel.ERROR, "mem", "malloc failed: size=1024, reason=out of memory"),
    (LogLevel.DEBUG, "gpio", "GPIO14 set to output mode"),
    (LogLevel.INFO, "uart", "UART baudrate set to 115200"),
    (LogLevel.DEBUG, "timer", "Timer0 triggered, period=1000ms"),
    (LogLevel.WARN, "task", "Task 'sensor_read' exceeded watchdog timeout"),
    (LogLevel.ERROR, "stack", "Stack overflow detected: task=TaskA, addr=0x1000"),
    (LogLevel.INFO, "net", "HTTP GET /api/status -> 200 OK"),
    (LogLevel.DEBUG, "i2c", "I2C read register 0x01 -> 0xAB"),
    (LogLevel.INFO, "app", "Application started successfully"),
]


def generate_mock_logs(count: int = 50) -> list:
    entries = []
    now = time.time()
    for i in range(count):
        level, module, msg = random.choice(LOG_TEMPLATES)
        entry = LogEntry(
            sequence=i + 1,
            received_at=now - (count - i) * 0.5,
            level=level,
            message=msg,
            raw=f"[{module}] {msg}",
            module=module,
        )
        entries.append(entry)
    return entries


class DemoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SerialLogAnalyzer - Demo 模式")
        self.resize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 中间分割 - 左右分栏
        self.splitter = QSplitter(Qt.Horizontal)

        # 左侧：日志表格 + 命令输入
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(12, 8, 12, 4)
        left_layout.setSpacing(4)

        self.log_view = LogView()
        left_layout.addWidget(self.log_view, stretch=1)

        # 命令输入栏（日志表格下面）
        from PySide6.QtWidgets import QLineEdit, QPushButton
        cmd_widget = QWidget()
        cmd_widget.setFixedHeight(36)
        cmd_layout = QHBoxLayout(cmd_widget)
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.setSpacing(8)
        cmd_layout.setAlignment(Qt.AlignVCenter)

        cmd_lbl = QLabel("命令:")
        cmd_lbl.setAlignment(Qt.AlignVCenter)
        cmd_lbl.setMinimumHeight(32)
        cmd_layout.addWidget(cmd_lbl)

        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("输入命令...")
        self.command_input.setFixedHeight(32)
        self.command_input.returnPressed.connect(self._on_send_command)
        cmd_layout.addWidget(self.command_input)

        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedHeight(32)
        self.send_btn.clicked.connect(self._on_send_command)
        cmd_layout.addWidget(self.send_btn)

        left_layout.addWidget(cmd_widget)
        self.splitter.addWidget(left_widget)

        # 右侧：分析面板
        self.analysis_panel = AnalysisPanel()
        self.splitter.addWidget(self.analysis_panel)

        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([800, 400])
        main_layout.addWidget(self.splitter)

        # 底部串口控制栏
        from PySide6.QtWidgets import QComboBox
        bottom_bar = QWidget()
        bottom_bar.setStyleSheet("""
            background: #f8f9fa;
            border-top: 1px solid #e2e8f0;
        """)
        bottom_bar.setFixedHeight(48)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(16, 8, 16, 8)
        bottom_layout.setSpacing(12)
        bottom_layout.setAlignment(Qt.AlignVCenter)

        lbl1 = QLabel("串口:")
        lbl1.setAlignment(Qt.AlignVCenter)
        lbl1.setMinimumHeight(32)
        bottom_layout.addWidget(lbl1)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(160)
        self.port_combo.setFixedHeight(32)
        bottom_layout.addWidget(self.port_combo)

        bottom_layout.addSpacing(20)

        lbl2 = QLabel("波特率:")
        lbl2.setAlignment(Qt.AlignVCenter)
        lbl2.setMinimumHeight(32)
        bottom_layout.addWidget(lbl2)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setMinimumWidth(100)
        self.baud_combo.setFixedHeight(32)
        bottom_layout.addWidget(self.baud_combo)

        bottom_layout.addSpacing(20)

        self.settings_btn = QPushButton("⚙ 设置")
        self.settings_btn.setFixedHeight(32)
        self.settings_btn.clicked.connect(self._open_serial_settings)
        bottom_layout.addWidget(self.settings_btn)

        bottom_layout.addStretch()

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setCheckable(True)
        self.connect_btn.setFixedHeight(32)
        self.connect_btn.setMinimumWidth(80)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182ce;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #2b6cb0;
            }
            QPushButton:checked {
                background-color: #e53e3e;
            }
            QPushButton:checked:hover {
                background-color: #c53030;
            }
        """)
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        bottom_layout.addWidget(self.connect_btn)

        main_layout.addWidget(bottom_bar)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Demo 模式 - 模拟数据")

        # 数据模型
        self.log_table_model = LogTableModel()
        self.log_filter_model = LogFilterModel()
        self.log_view.set_models(self.log_table_model, self.log_filter_model)

        # 填充模拟数据
        mock_logs = generate_mock_logs(100)
        self.log_table_model.add_entries(mock_logs)
        self.log_view.scroll_to_bottom()

        # 状态栏联动
        self.log_table_model.row_count_changed.connect(
            lambda c: self.status_bar.showMessage(f"Demo 模式 - 共 {c} 条日志")
        )

        # 模拟按钮事件
        self.log_view.clear_requested.connect(self.log_table_model.clear)
        self.log_view.export_requested.connect(lambda: self.status_bar.showMessage("导出功能演示"))
        self.analysis_panel.analyze_clicked.connect(self._mock_analyze)
        self.analysis_panel.send_message_clicked.connect(self._mock_followup)
        self.analysis_panel.new_session_clicked.connect(self._mock_new_session)
        self.analysis_panel.ai_settings_clicked.connect(self._open_ai_settings)

        # 模拟实时日志定时器（初始不启动）
        self._seq = 100
        self._timer = QTimer()
        self._timer.timeout.connect(self._gen_rt_log)

    def _on_send_command(self):
        cmd = self.command_input.text().strip()
        if cmd:
            self.status_bar.showMessage(f"发送命令: {cmd}")
            self.command_input.clear()

    def _on_connect_clicked(self, checked):
        if checked:
            port = self.port_combo.currentText()
            baudrate = self.baud_combo.currentText()
            self.connect_btn.setText("断开")
            self.status_bar.showMessage(f"已连接 {port} @ {baudrate}")
            self._timer.start(500)
        else:
            self.connect_btn.setText("连接")
            self.status_bar.showMessage("已断开")
            self._timer.stop()

    def _open_serial_settings(self):
        """打开串口设置对话框 - 严格按照Qt Designer截图排版"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QGridLayout, QComboBox, QLabel, QGroupBox, QRadioButton, QButtonGroup, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("串口高级设置")
        dlg.setMinimumWidth(550)
        dlg.setStyleSheet("""
            QDialog {
                background: #ffffff;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
            QGroupBox {
                border: 1px solid #a0aec0;
                border-radius: 4px;
                margin-top: 16px;
                padding-top: 20px;
                font-size: 15px;
                color: #2d3748;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLabel {
                font-size: 14px;
                color: #2d3748;
            }
            QComboBox {
                background: white;
                border: 1px solid #a0aec0;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 140px;
                min-height: 24px;
                font-size: 13px;
            }
            QRadioButton {
                spacing: 8px;
                font-size: 16px;
                color: #2d3748;
            }
            QPushButton {
                background-color: #f7fafc;
                color: #2d3748;
                border: 1px solid #a0aec0;
                border-radius: 4px;
                padding: 8px 32px;
                min-width: 90px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #edf2f7;
            }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ===== 串口选项分组 =====
        group = QGroupBox("串口选项")
        group_layout = QGridLayout(group)
        group_layout.setSpacing(16)
        group_layout.setContentsMargins(20, 24, 20, 20)

        # 第一行：数据位、停止位、校验位
        group_layout.addWidget(QLabel("数据位:"), 0, 0)
        databits = QComboBox()
        databits.addItems(["5", "6", "7", "8"])
        databits.setCurrentText("8")
        group_layout.addWidget(databits, 0, 1)

        group_layout.addWidget(QLabel("停止位:"), 0, 2)
        stopbits = QComboBox()
        stopbits.addItems(["1", "1.5", "2"])
        group_layout.addWidget(stopbits, 0, 3)

        group_layout.addWidget(QLabel("校验位:"), 0, 4)
        parity = QComboBox()
        parity.addItems(["NONE", "EVEN", "ODD"])
        group_layout.addWidget(parity, 0, 5)

        layout.addWidget(group)

        # ===== 流控选项分组 =====
        flow_group = QGroupBox("流控选项")
        flow_layout = QHBoxLayout(flow_group)
        flow_layout.setContentsMargins(20, 24, 20, 20)
        flow_layout.setSpacing(20)
        flow_group_btn = QButtonGroup(dlg)
        r1 = QRadioButton("None")
        r1.setChecked(True)
        flow_group_btn.addButton(r1, 0)
        flow_layout.addWidget(r1)
        r2 = QRadioButton("Hardware")
        flow_group_btn.addButton(r2, 1)
        flow_layout.addWidget(r2)
        r3 = QRadioButton("Software")
        flow_group_btn.addButton(r3, 2)
        flow_layout.addWidget(r3)
        flow_layout.setStretch(0, 1)
        flow_layout.setStretch(1, 1)
        flow_layout.setStretch(2, 1)
        layout.addWidget(flow_group)

        # ===== 底部按钮 =====
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec():
            self.status_bar.showMessage("串口设置已保存")

    def _open_ai_settings(self):
        """打开 AI 模型配置对话框"""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
            QComboBox, QLineEdit, QPushButton, QDialogButtonBox,
            QGroupBox, QLabel, QTabWidget, QWidget,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("AI 模型配置")
        dlg.setMinimumWidth(560)
        dlg.setStyleSheet("""
            QDialog {
                background: #ffffff;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
            QGroupBox {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                margin-top: 16px;
                padding-top: 20px;
                font-weight: 600;
                color: #2d3748;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                color: #2b6cb0;
            }
            QLabel {
                color: #4a5568;
            }
            QLineEdit, QComboBox {
                background: white;
                border: 1px solid #cbd5e0;
                border-radius: 6px;
                padding: 6px 10px;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #3182ce;
            }
            QPushButton {
                background-color: #f7fafc;
                color: #2d3748;
                border: 1px solid #cbd5e0;
                border-radius: 6px;
                padding: 6px 20px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #edf2f7;
                border-color: #4299e1;
            }
            QDialogButtonBox QPushButton {
                min-width: 80px;
            }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ===== 提供商选择 =====
        provider_group = QGroupBox("模型提供商")
        provider_layout = QFormLayout(provider_group)
        provider_layout.setSpacing(12)
        provider_layout.setContentsMargins(16, 24, 16, 16)

        provider_combo = QComboBox()
        provider_combo.addItems([
            "OpenAI (GPT-4o / GPT-3.5)",
            "DeepSeek (V3 / R1)",
            "通义千问 (Qwen)",
            "智谱 GLM",
            "Ollama (本地模型)",
            "自定义 OpenAI 兼容接口",
        ])
        provider_layout.addRow("提供商：", provider_combo)

        base_url_edit = QLineEdit()
        base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        provider_layout.addRow("API Base URL：", base_url_edit)

        model_edit = QLineEdit()
        model_edit.setPlaceholderText("gpt-4o-mini")
        provider_layout.addRow("模型名称：", model_edit)

        layout.addWidget(provider_group)

        # ===== 密钥配置 =====
        key_group = QGroupBox("API 密钥")
        key_layout = QFormLayout(key_group)
        key_layout.setSpacing(12)
        key_layout.setContentsMargins(16, 24, 16, 16)

        api_key_edit = QLineEdit()
        api_key_edit.setPlaceholderText("sk-...")
        api_key_edit.setEchoMode(QLineEdit.Password)
        key_layout.addRow("API Key：", api_key_edit)

        key_hint = QLabel("密钥将安全存储在系统凭据管理器中，不会明文保存")
        key_hint.setStyleSheet("color: #718096; font-size: 11px;")
        key_layout.addRow("", key_hint)

        layout.addWidget(key_group)

        # ===== 高级参数 =====
        adv_group = QGroupBox("高级参数")
        adv_layout = QFormLayout(adv_group)
        adv_layout.setSpacing(12)
        adv_layout.setContentsMargins(16, 24, 16, 16)

        temp_combo = QComboBox()
        temp_combo.addItems(["0.0 (精确)", "0.3 (平衡)", "0.7 (创意)", "1.0 (发散)"])
        temp_combo.setCurrentIndex(1)
        adv_layout.addRow("温度：", temp_combo)

        max_tokens_edit = QLineEdit()
        max_tokens_edit.setText("4096")
        adv_layout.addRow("最大输出 Tokens：", max_tokens_edit)

        layout.addWidget(adv_group)

        # ===== 底部按钮 =====
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存配置")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec():
            self.status_bar.showMessage("AI 模型配置已保存")

    def _mock_refresh_ports(self):
        self.port_combo.clear()
        self.port_combo.addItem("COM3 - USB-SERIAL CH340")
        self.port_combo.addItem("COM5 - Silicon Labs CP210x")
        self.status_bar.showMessage("已刷新串口列表")

    def _gen_rt_log(self):
        self._seq += 1
        level, module, msg = random.choice(LOG_TEMPLATES)
        entry = LogEntry(
            sequence=self._seq,
            received_at=time.time(),
            level=level,
            message=msg,
            raw=f"[{module}] {msg}",
            module=module,
        )
        self.log_table_model.add_entries([entry])
        self.log_view.scroll_to_bottom()

    def _mock_analyze(self, mode, selector, user_input):
        self.analysis_panel.set_state(AnalysisState.STREAMING)
        self.status_bar.showMessage("LLM 分析中...")

        result = """【分析结果】

基于日志上下文，发现以下关键问题：

1. 内存分配失败
   - 检测到 malloc failed: size=1024 错误
   - 此前出现 Low memory warning: free heap = 12KB
   - 建议：排查内存泄漏，增大堆配置或减少动态分配

2. 栈溢出异常
   - Stack overflow detected: task=TaskA, addr=0x1000
   - 疑似递归调用过深或局部数组过大
   - 建议：增大 TaskA 栈空间，优化递归逻辑

3. 任务看门狗超时
   - Task 'sensor_read' exceeded watchdog timeout
   - 传感器读取可能阻塞任务调度
   - 建议：增加超时保护，改用非阻塞 I/O

【修复优先级】
P0: 栈溢出（直接导致崩溃）
P1: 内存泄漏排查
P2: 传感器读取优化
"""
        self._stream_text = result
        self._stream_idx = 0
        self._stream_timer = QTimer()
        self._stream_timer.timeout.connect(self._stream_chunk)
        self._stream_timer.start(15)

    def _stream_chunk(self):
        step = 4
        if self._stream_idx < len(self._stream_text):
            self.analysis_panel.append_stream_chunk(
                self._stream_text[self._stream_idx:self._stream_idx + step]
            )
            self._stream_idx += step
        else:
            self._stream_timer.stop()
            self.analysis_panel.set_state(AnalysisState.DONE, "完成")
            self.status_bar.showMessage("分析完成")

    def _mock_followup(self, msg):
        self.analysis_panel.append_stream_chunk(f"\n[追问] {msg}\n")
        self.analysis_panel.append_stream_chunk("这是模拟的追问回复内容...\n")

    def _mock_new_session(self):
        self.analysis_panel.clear_result()
        self.status_bar.showMessage("已开启新会话")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 应用明亮浅色主题
    from ui.style import LIGHT_THEME_QSS
    app.setStyleSheet(LIGHT_THEME_QSS)

    window = DemoWindow()
    window.show()
    sys.exit(app.exec())
