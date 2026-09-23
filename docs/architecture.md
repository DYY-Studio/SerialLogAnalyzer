# 架构总览

本文档是 `DESIGN.md` 的补充说明，聚焦“为什么这样分层”与“改代码时放哪里”的问题；
接口细节以 `DESIGN.md` 与各模块 Docstring 为准。

## 1. 三层 + 组装根

```text
ui/          PySide6 界面：只做展示与交互
  │ 依赖 core 服务
core/        纯 Python：模型、用例、协议接口
  ▲ 由 io 实现
io/          Qt / 系统适配：串口、网络、设置、存储、凭据
bootstrap.py 唯一组装点：显式构造并注入全部依赖
```

依赖方向只有一个：`ui → core ← io`。`core` 不知道 `ui` 与 `io` 的存在。

## 2. 数据流

### 2.1 日志链路

```text
QSerialPort.readyRead
  → QtSerialTransport.on_bytes(bytes)
  → LineFramer.feed(bytes) → list[str]
  → LogParser.parse(line) → ParseResult
  → LogPipeline.feed(line) → PipelineUpdate
  → DeviceController.log_update(Qt Signal)
  → LogTableModel.apply_update → QTableView
```

关键点：`readyRead` 与“一行日志”没有对应关系，分帧器必须自维护缓冲。

### 2.2 分析链路

```text
AnalysisPanel.analyze_requested
  → AnalysisController
  → AnalysisContextBuilder.build（从 LogPipeline 取日志）
  → PromptLibrary.render（模板 + 上下文）
  → RequestBuilder.build → HttpRequest
  → QtHttpTransport.send（QNetworkAccessManager）
  → SSEParser.feed → StreamProcessor.handle → 增量回调
  → AnalysisController.result_updated(Qt Signal)
  → AnalysisPanel.append_delta
```

## 3. 放代码的决策表

| 你想做的事 | 放哪里 | 说明 |
|---|---|---|
| 新增日志字段 | `core/models/logs.py` + Preset schema | 同步更新 `docs/protocols/log-preset.md` |
| 换一种日志格式 | `presets/logs/*.yaml` | 不改 Python |
| 调整解析行为 | `core/logs/parser.py` | 需补单元测试 |
| 支持新的模型接口 | `providers/adapters/*.yaml` | 优先声明式解决，不改代码 |
| 改请求编码逻辑 | `core/llm/request.py` | 保持与 Qt 无关 |
| 改网络细节 | `io/llm/qt_http_transport.py` | Qt 类型只在此出现 |
| 改串口细节 | `io/serial/qt_serial_transport.py` | 同上 |
| 改界面布局 | `ui/widgets/` 或 `ui/main_window.py` | 不写业务逻辑 |
| 组件间协调 | `ui/controllers/` | 只转发与编排，不实现业务 |
| 新增外部依赖 | 先讨论 | 见 `DEVELOPMENT.md` 依赖规则 |

## 4. 线程模型

v1 全部运行在 Qt 主线程：串口与网络均为异步事件驱动，解析为轻量 CPU 操作。
若将来出现明确的 CPU 密集瓶颈（例如超大文件导入），先讨论再引入 `QThreadPool`，
并保持 `core` 的纯函数特性以便跨线程复用。

## 5. 扩展点

| 需求 | 建议做法 |
|---|---|
| 多规则 Preset（按优先级匹配） | 扩展 `PresetLineRule` 为列表，YAML schema 版本递增 |
| 非 SSE 流式协议 | 在 `core/llm` 增加新的帧解析器，`StreamProcessor` 保持输入抽象 |
| 导出为 CSV / JSONL | 扩展 `LogFileStore`，不改核心流水线 |
| 迁移到 Web 后端 | 复用 `core/`，新增 FastAPI 层与 httpx 版 `HttpTransport` |
