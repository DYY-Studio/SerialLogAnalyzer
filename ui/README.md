# UI 模块说明

## 目录结构

```
ui/
├── __init__.py                  # 模块导出
├── main_window.py               # 主窗口 - 顶层界面组装
│
├── controllers/                 # 控制器层 - 连接 UI 与 core 业务
│   ├── __init__.py
│   ├── main_controller.py       # 主控制器 - 全局协调
│   ├── device_controller.py     # 设备控制器 - 串口连接桥接
│   └── analysis_controller.py   # 分析控制器 - LLM 分析桥接
│
├── models/                      # Qt 数据模型
│   ├── __init__.py
│   ├── log_table_model.py       # 日志表格数据模型 (LogTableModel)
│   └── log_filter_model.py      # 日志过滤代理模型
│
├── widgets/                     # 自定义 UI 组件
│   ├── __init__.py
│   ├── serial_toolbar.py        # 串口工具栏
│   ├── log_view.py              # 日志视图（表格 + 过滤栏）
│   └── analysis_panel.py        # LLM 分析面板 (AnalysisPanel)
│
└── dialogs/                     # 对话框
    ├── __init__.py
    ├── settings_dialog.py       # 设置对话框
    ├── provider_dialog.py       # LLM Provider 配置对话框
    └── credential_dialog.py     # 凭据输入对话框
```

## 核心组件说明

### 1. LogTableModel (models/log_table_model.py)
- 继承 `QAbstractTableModel`，高效渲染大量日志
- 支持环形缓冲（默认最大 10 万行）
- 批量插入、单条更新、批量删除
- 按日志级别着色（VERBOSE/DEBUG/INFO/WARN/ERROR）
- 列：序号、时间、级别、模块、消息

### 2. LogFilterModel (models/log_filter_model.py)
- 继承 `QSortFilterProxyModel`
- 支持按级别多选过滤
- 支持按模块名模糊匹配
- 支持按关键字文本搜索

### 3. AnalysisPanel (widgets/analysis_panel.py)
- 右侧 LLM 分析面板
- 上下文选择：选中、选中+邻居、最近、仅错误
- 预设分析目标 + 自由输入
- SSE 流式输出显示
- 多轮对话输入区
- 状态显示（就绪/分析中/完成/错误）

### 4. DeviceController (controllers/device_controller.py)
- 把 core `DeviceSession` 的普通回调转成 Qt Signal
- 信号：日志接收到、状态变化、错误、串口列表更新
- 对外接口：connect / disconnect / refresh_ports / send_command

### 5. AnalysisController (controllers/analysis_controller.py)
- 把 core `AnalysisService` 的回调转成 Qt Signal
- 信号：流式分片、状态变化、错误
- 对外接口：start_analysis / send_followup / new_session

### 6. MainWindow (main_window.py)
- 整体布局：顶部工具栏 + 左右分割（日志 | 分析）+ 底部状态栏
- 依赖注入：接收 device_controller 和 analysis_controller
- 信号 wiring：连接所有 UI 事件到控制器

## 设计原则（遵循 DESIGN.md 硬约束）

1. **ui/ 不解析日志、不发 LLM 请求、不直接操作 QSerialPort**
   - 所有业务逻辑在 core/，ui 只做展示和交互
2. **Qt 类型只出现在 ui/ 与 io/**
   - core/ 纯 Python，不 import PySide6
3. **控制器做回调 → Signal 转换**
   - core 用普通 callable 回调，ui 侧转成 Qt Signal
4. **MainWindow 不保存核心业务状态**
   - 状态都在 core 服务里，ui 只是镜像

## 依赖关系图

```
MainWindow
├── SerialToolbar ──────┐
├── LogView             │
│   └── QTableView      │
│       └── LogFilterModel ── LogTableModel
├── AnalysisPanel       │
└── StatusBar           │
                        ▼
                MainController
                ├── DeviceController ── DeviceSession (core)
                └── AnalysisController ── AnalysisService (core)
```

## 集成方式（在 bootstrap.py 中）

```python
# 1. 创建 core 服务
device_session = DeviceSession(transport, pipeline)
analysis_service = AnalysisService(...)

# 2. 创建控制器
device_controller = DeviceController(device_session)
analysis_controller = AnalysisController(analysis_service)

# 3. 创建主窗口
window = MainWindow(device_controller, analysis_controller)
window.show()
```
