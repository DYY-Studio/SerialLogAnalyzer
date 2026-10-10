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

### 2.3 配置与资源链路

```text
bootstrap.main
  → configure_logging（diagnostics/app_logging.py，SLA_LOG_LEVEL / SLA_LOG_FILE）
  → CompositeResourceLoader.from_environment  （用户配置目录 → 仓库根 → 包内 resources）
  → load_presets / load_adapters / load_profiles / PromptLibrary
  → QtSettingsStore（QSettings：窗口、串口、级别、导出目录等偏好）
  → KeyringStoreAdapter → CredentialResolver（运行时输入 > kind 首选 > 另一来源）
  → DeviceController / AnalysisController（全部构造函数注入）

DiagnosticsReport.collect(loader, ...)  ← python -m serial_log_analyzer.diagnostics
  → 纯 Python、无 Qt：资源清单 + 配置错误 + 钥匙串可用性 + 日志末尾
```

关键点：`core/` 只依赖 `core/ports.py` 的 `Protocol`；路径拼装集中在 `io/paths.py`，
因此测试可用 `SLA_CONFIG_HOME` 把用户配置目录整体重定向到临时目录。


## 3. 放代码的决策表

| 你想做的事 | 放哪里 | 说明 |
|---|---|---|
| 新增日志字段 | `core/models/logs.py` + Preset schema | 同步更新 `docs/protocols/log-preset.md` |
| 换一种日志格式 | `presets/logs/*.yaml` | 不改 Python |
| 调整解析行为 | `core/logs/parser.py` | 需补单元测试 |
| 支持新的模型接口 | `providers/adapters/*.yaml` | 优先声明式解决，不改代码 |
| 新增/修改 Profile 可配字段 | `core/llm/profile_loader.py` + `profile_writer.py` | 同步 `io/storage/profile_store.py` 与 `docs/protocols/provider.md` |
| 改 Profile 编辑界面（新建 / 删除 / 模型下拉） | `ui/dialogs/provider_dialog.py` | 归界面分工；数据层已由 `ProfileStore` 提供，不必改 core |
| 改资源查找顺序或新增资源类型 | `io/resources.py` + `io/paths.py` | 用户目录永远优先于内置资源 |
| 新增设置项 | `io/settings/qt_settings_store.py` 的 `SETTINGS_KEYS` | 界面读写放 `ui/dialogs/settings_dialog.py` |
| 改凭据来源或优先级 | `core/services/credential_resolver.py` | 钥匙串/环境变量实现留在 `io/credentials/`、`io/environment.py` |
| 改日志导出/导入格式 | `io/storage/log_file_store.py` | 不改 `LogPipeline` |
| 改诊断报告内容 | `diagnostics/report.py` | 保持纯 Python、不 import Qt |
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
| 更多导出格式（Excel / HTML） | 在 `ExportFormat` 增加分支，不改核心流水线（CSV / JSONL 已实现） |
| 新增凭据后端（如 1Password） | 实现 `core/ports.KeyringStore`，在 `CredentialResolver` 复用同一优先级逻辑 |
| 多份用户配置（便携模式 / 多设备） | 用 `SLA_CONFIG_HOME` 切换用户配置目录，无需改代码 |
| Profiles 管理器（新建 / 复制 / 删除 / 拉取模型列表） | 属界面分工：在 `ProviderDialog` 上扩展，落盘复用 `ProfileStore`；模型列表需 LLM 分工先实现 `providers/adapters` 的 `models` 发现 |
| 迁移到 Web 后端 | 复用 `core/`，新增 FastAPI 层与 httpx 版 `HttpTransport` |
