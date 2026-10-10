# SerialLogAnalyzer 架构设计 v1

**状态**：已定稿
**范围**：PC 端通用串口日志分析工具 + 同仓 Hi3861 日志发送固件。

---

## 1. 定位与命名

- 项目/仓库 `SerialLogAnalyzer`，Python 包 `serial_log_analyzer`。
- 目标：串口连接设备，实时接收/解析/展示日志；YAML Preset 声明式解析；将日志上下文提交 LLM 分析；支持单次与多轮；SSE 流式；Provider 配置驱动。
- 通用性：工具不绑定具体芯片或固件，不硬编码设备字段；换设备只需新增 Preset（必要时另写发送固件），PC 端代码不动。
- 本地单机工具；不做 Web 服务化、多用户、远程访问。
- 中文 UI + 中文文档；代码标识符英文。
- 组成：PC 端工具 + 同仓 `fw/`（Hi3861 固件）。

## 2. 总体技术方案（已锁定，不再讨论）

- GUI：Python + PySide6 + Qt Widgets。
- 串口：`QSerialPort` / `QSerialPortInfo`，不引入 pyserial。
- 网络：`QNetworkAccessManager`，不引入 httpx/requests/asyncio 网络栈。
- 并发：单 Qt 事件循环；v1 无 QThread/asyncio。CPU 密集任务出现时再评估 QThreadPool。
- 运行依赖：`PySide6`、`PyYAML`、`keyring`，其余标准库。
- 开发工具：`uv` / `pytest` / `pytest-qt` / `ruff`。
- Python：`requires-python = ">=3.11,<3.15"`，开发 `.python-version` pin 3.12。

## 3. 分层：core / io / ui + bootstrap

```text
ui/          Qt 展示与交互
  │ 依赖
core/        纯 Python：模型 + 用例 + 协议接口
  ▲ 实现
io/          Qt 适配器：串口 / 网络 / 设置 / 存储 / 凭据
bootstrap.py 唯一组装根
```

硬约束（同时写入 `DEVELOPMENT.md`）：

- `core/` 不 import PySide6；不直接访问文件/串口/网络。
- `io/` 只做适配与类型转换，不做业务决策；Qt 类型不外泄。
- `ui/` 不解析日志、不发 LLM 请求、不直接操作 `QSerialPort`/`QNetworkAccessManager`。
- `MainWindow` 不保存核心业务状态。
- 将来迁 Vue+FastAPI：`core/` 原样复用，替换 `io/` + `ui/` 即可。

## 4. 目录结构

```text
SerialLogAnalyzer/
├── main.py                      # python main.py 传统入口
├── pyproject.toml / uv.lock / .python-version
├── README.md / DEVELOPMENT.md / AGENTS.md / DESIGN.md
├── docs/
│   ├── architecture.md
│   └── protocols/
│       ├── log-preset.md
│       ├── provider.md
│       ├── json-pointer.md
│       ├── board-protocol.md
│       └── credentials.md
├── presets/logs/hi3861-default.yaml
├── providers/adapters/*.yaml
├── providers/profiles/*.yaml
├── prompts/*.md
├── fw/{include,src,examples}/ + README.md
├── src/serial_log_analyzer/
│   ├── __init__.py / __main__.py / bootstrap.py
│   ├── core/
│   │   ├── errors.py  ports.py
│   │   ├── models/{device,logs,analysis,provider}.py
│   │   ├── logs/{line_framer,parser,preset,preset_loader,pipeline}.py
│   │   ├── llm/{pointer,adapter,adapter_loader,request,sse,stream}.py
│   │   ├── prompts/loader.py
│   │   └── services/{device_session,analysis,credential_resolver}.py
│   ├── io/
│   │   ├── serial/{qt_serial_transport,port_discovery}.py
│   │   ├── llm/qt_http_transport.py
│   │   ├── settings/qt_settings_store.py
│   │   ├── storage/log_file_store.py
│   │   └── credentials/keyring_store.py
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── controllers/{main,device,analysis}_controller.py
│   │   ├── models/{log_table_model,log_filter_model}.py
│   │   ├── widgets/{serial_toolbar,log_view,analysis_panel}.py
│   │   └── dialogs/{settings,provider,credential}_dialog.py
│   ├── diagnostics/app_logging.py
│   └── resources/
└── tests/{unit,integration,ui}/
```

> 说明：凭据适配器置于 `io/credentials/`，避免 `serial_log_analyzer.io.keyring` 与顶层 `keyring` 包同名造成阅读歧义。

## 5. core 模型与接口

```python
class Parity(Enum): NONE, EVEN, ODD, SPACE, MARK
class StopBits(Enum): ONE, ONE_POINT_FIVE, TWO
class FlowControl(Enum): NONE, HARDWARE, SOFTWARE
class DeviceConnectionState(Enum): DISCONNECTED, CONNECTING, CONNECTED, ERROR

@dataclass(frozen=True)
class SerialConfig: port, baudrate, data_bits, parity, stop_bits, flow_control

@dataclass(frozen=True)
class SerialPortInfo: name, description, manufacturer, serial_number

class LogLevel(Enum): VERBOSE, DEBUG, INFO, WARN, ERROR, UNKNOWN   # 固定集 + 严重度顺序

@dataclass           # 非 frozen：continuation 行需追加到上一条
class LogEntry:
    sequence: int
    received_at: float          # PC 接收时刻（始终存在）
    level: LogLevel
    message: str
    raw: str
    device_time: str | None = None     # 可选，板上时间戳；v1 默认无
    module: str | None = None
    continuation: bool = False
    extra: dict[str, str] = field(default_factory=dict)  # Preset fields 抽取的结构化字段
```

```python
# core/ports.py —— 依赖倒置：core 定义 Protocol，io 实现
class SerialTransport(Protocol):
    def list_ports(self) -> list[SerialPortInfo]: ...   # 枚举可用串口（工具栏 Refresh）
    def open(self, config: SerialConfig) -> None: ...
    def close(self) -> None: ...
    def write(self, data: bytes) -> None: ...
    @property
    def is_open(self) -> bool: ...
    def set_handlers(self, on_bytes, on_error) -> None: ...

class HttpTransport(Protocol):
    def send(self, request: HttpRequest, on_chunk, on_done, on_error) -> CancellationToken: ...

class SettingsStore(Protocol):
    def get(self, key, default=None): ...
    def set(self, key, value) -> None: ...

class KeyringStore(Protocol):        # 系统钥匙串适配（角色单一，故不叫 CredentialStore）
    @property
    def available(self) -> bool: ...
    def read(self, credential_id: str) -> str | None: ...
    def save(self, credential_id: str, secret: str) -> None: ...
    def delete(self, credential_id: str) -> None: ...

class EnvironmentReader(Protocol):
    def get(self, name: str) -> str | None: ...

class ResourceLoader(Protocol):
    def read_text(self, relative_path: str) -> str: ...
    def list_files(self, relative_dir: str, pattern: str) -> list[str]: ...
```

边界约定：`io` → `core` 用普通 callable 回调；core 服务的增量输出由 `ui` Controller 转成 Qt Signal。Qt 类型只出现在 `ui/` 与 `io/`。

## 6. 串口 → 日志流水线

```text
QSerialPort.readyRead → io.readAll() (bytes)
 → core.LineFramer.feed(bytes) -> list[str]      # 自维护字节缓冲，\r\n 切分
 → core.LogParser.parse(line, sequence, received_at) -> ParseResult
 → core.LogPipeline.feed(line, received_at) -> PipelineUpdate
 → core.DeviceSession 分发（`@` 开头 → 命令回复，其余 → 流水线）
 → ui.Controller 每 ~40ms 批量刷入 LogTableModel
```

- `LineFramer` 处理跨块半行；`finalize()` 处理尾部残留、`reset()` 清空缓冲；不假设 `readyRead` 对齐一行；超长行按 `max_line_bytes` 截断。
- `LogParser.parse(line, sequence, received_at) -> ParseResult`；`outcome` ∈ `MATCHED` / `CONTINUATION` / `FALLBACK` / `IGNORED`，`CONTINUATION` 时携带待并入文本。
- `LogPipeline.feed(line, received_at) -> PipelineUpdate(added, updated, dropped_sequences)`；continuation 行**并入上一条**（message/raw 追加，`continuation=True`）。
- 环形缓冲上限默认 100000（可配置）；查询接口 `entries()` / `recent(count, *, min_level=None)` / `selected_with_neighbors(sequences, window)` / `render(entries)` / `clear()` 供分析与 UI 使用。
- `DeviceSession` 负责串口连接、字节分发与命令通道编排（见 §6.1）。
- UI：`QAbstractTableModel` + `QSortFilterProxyModel`（level/module/文本过滤）+ `QTableView`；不以 `QTextEdit` 为数据源。批量 `beginInsertRows`，末条更新 `dataChanged`，截断 `beginRemoveRows`。

### 6.1 DeviceSession（设备会话，`ui` 接入串口链路的唯一入口）

```python
DeviceSession(transport: SerialTransport, pipeline: LogPipeline, handlers: DeviceSessionHandlers)
    .connect(config: SerialConfig) -> None      # 失败抛 SerialConnectionError
    .disconnect() -> None                       # 关闭并 flush 分帧器残余
    .send_command(command: str) -> None         # 自动追加 \r\n；未连接抛 SerialConnectionError
    .list_ports() -> list[SerialPortInfo]
    .state -> DeviceConnectionState
    .pipeline -> LogPipeline

DeviceSessionHandlers(
    on_update:  (PipelineUpdate) -> None,
    on_state:   (DeviceConnectionState, str) -> None,
    on_error:   (AppError) -> None,
    on_command_reply: (CommandReply) -> None = None,   # 见 §7
)
```

`ui` Controller 把这组普通回调转成 Qt Signal；`core` 不 import PySide6。

## 7. 板上日志格式与命令协议（`docs/protocols/board-protocol.md`）

日志行（方括号分级文本，v1 无板上时间戳）：

```text
[LEVEL] [tag] message

[I] [wifi] connected to AP
[E] [uart] rx overflow
```

多行日志后续行以行首空白开头；固件宏 `LOGV/LOGD/LOGI/LOGW/LOGE(tag, fmt, ...)`，行尾 `\r\n`。

板上时间戳为文档预留的可选变体 `[LEVEL] [time] [tag] msg`，届时仅需替换 Preset 正则，无需改代码。

命令通道：

| 命令 | 响应 | 说明 |
|---|---|---|
| `PING` | `@OK PONG` | 连通性 |
| `VERSION` | `@OK fw=1.0.0 chip=hi3861` | 版本 |
| `HELP` | `@OK PING VERSION HELP TEST` | 帮助 |
| `TEST <name>` | `@OK TEST <name> started` | 触发自测（wifi/uart/gpio…） |

响应前缀 `@OK ...` / `@ERR <code> <msg>`，与 `[` 开头日志行不冲突；UI 命令回复区单独呈现。
PC 侧解析见 `core/device/command.py`：`is_response_line(line)`、`parse_response(line) -> CommandReply(text, ok, code)`；
`DeviceSession` 以 `@` 前缀判定回复行，回复不写入日志表格。

命令超时（v1 方案，暂未实现）：由 `ui/DeviceController` 在发送后起 `QTimer`（`board-protocol.md` §2.4 建议 2s），
超时未见回复则在命令回复区提示；`core` 不感知超时，协议也不引入请求 id，从而不改固件即可通用。

## 8. YAML Log Preset Schema（v1 单规则 + fallback + 合并）

```yaml
schema_version: 1
preset_id: hi3861-default
display_name: "Hi3861 默认日志"
line:
  pattern: '^\s*(?:\[(?P<time>[^\]]+)\]\s*)?\[(?P<level>[A-Za-z]+)\]\s*\[(?P<module>[^\]]+)\]\s*(?P<message>.*)$'
  level_map:
    V: VERBOSE
    D: DEBUG
    I: INFO
    W: WARN
    E: ERROR
    VERBOSE: VERBOSE
    DEBUG: DEBUG
    INFO: INFO
    WARN: WARN
    WARNING: WARN
    ERROR: ERROR
  continuation_pattern: '^\s+\S'
  fields:                          # 可选：从 message 抽取结构化字段存入 LogEntry.extra
    temperature: 'temperature=(?P<value>[\d.]+)'
fallback:
  enabled: true
  level: UNKNOWN
```

- 默认组名 `level` / `module` / `message` / `time`；`time` 组可选，存在则填 `device_time`。
- 未映射级别 → `UNKNOWN`；正则编译失败或必填组缺失 → `PresetError`。
- 禁止 eval/表达式，仅允许预定义字段。
- 搜索路径优先级：用户目录（`~/.config/SerialLogAnalyzer/presets`）> 仓库/内置 `presets/`。

## 9. LLM 声明（YAML）

- 声明格式为 YAML，不提供其他格式的兼容层。
- `providers/adapters/*.yaml` 字段：`schema_version / adapter_id / endpoint / messages_format / headers / body / response_content_pointer / response_reasoning_content_pointers / models / usage / streaming`。
- 内置四个 adapter：`openai-compatible`、`openai-responses`、`anthropic`、`google-gemini`。
- `providers/profiles/*.yaml`：

```yaml
schema_version: 1
profile_id: openai-default
adapter_id: openai-compatible
base_url: https://api.openai.com/v1
model: gpt-4o-mini
credential:
  kind: keyring            # keyring | environment | runtime
  name: openai-default     # keyring 账号名；environment 时忽略
  env_var: OPENAI_API_KEY  # kind=environment 时使用
stream: true
request_timeout_seconds: 120
extra_body: {}
extra_headers: {}
```

- `body` / `headers` 占位符：`${model} ${system} ${messages} ${temperature} ${max_output_tokens} ${stream} ${api_key}`。
- `streaming`：`transport（仅 sse） / endpoint / request_body / content_events[{pointer,when}] / terminal{sentinel|when} / error_events[{when,message_pointer,status_pointer}]`。
- v1 至少内置 `openai-compatible` 可用流式声明。

## 10. 扩展 JSON Pointer（`docs/protocols/json-pointer.md`）

- 基础兼容 RFC6901：`/a/0/b`；转义 `~0` → `~`，`~1` → `/`。
- 扩展：数组 token 支持负索引，如 `/choices/-1/message/content`。
- 定案语义：根 `""` → 整文档；`-1` = 末元素；`-0` 非法；单独 `-` 非法；越界 / 类型不符 / 非数组负索引 / 非法转义 → `PointerError`。
- 纯 Python，独立单测，不依赖 Qt/HTTP。

## 11. Streaming

```text
QNetworkReply.readyRead → readAll() → SSEParser.feed(bytes) -> list[payload]
 → JSON → adapter.stream_content_deltas() → Extended JSON Pointer → delta
```

- `SSEParser` 自维护缓冲，处理 `data:` 跨块；终止用 adapter `terminal`；结束时 `finalize()` flush 尾部。
- `transport` 仅支持 `sse`。

## 12. 分析与上下文

```python
class AnalysisMode(Enum): SINGLE, CHAT
class ContextSelector(Enum): SELECTED, SELECTED_WITH_NEIGHBORS, RECENT, ERRORS_ONLY, MANUAL
class AnalysisState(Enum): IDLE, STREAMING, DONE, ERROR

@dataclass AnalysisRequest: mode, selector, user_input, goal_id
@dataclass AnalysisResult: content, reasoning, usage, state
```

- 单次 = 仅一条 user 消息的会话；多轮 = 保留历史（结果面板含历史 + 输入框），提供“新会话/清空”。
- 上下文由 `AnalysisContextBuilder` 从 `LogPipeline` 取并叠加进新 user 消息；`SELECTED_WITH_NEIGHBORS` 窗口 N 默认 10。
- Prompt：`prompts/*.md`，内置目标（定位错误 / 解释日志 / 给出修复建议）+ 自由输入；`string.Template`（`$context $goal $language`）安全替换。

## 13. 设置 / 凭据 / 存储

- `QSettings`：窗口尺寸、splitter、最近串口/波特率、当前 profile、UI 选项。
- `providers/profiles/*.yaml`：结构复杂配置。
- 凭据三种 kind：`keyring`（`{kind: keyring, name}`）、`environment`（`{kind: environment, env_var}`）、`runtime`（`{kind: runtime}`，每次运行时输入）。
- 解析优先级：`runtime 输入` → `keyring` → `environment`；任一命中即停止。
- 运行时输入仅用于当前会话，**不自动写入 Keychain**；由用户手动保存。
- Keyring 不可用时 `available=False`，UI 置灰 keyring 选项、回退 env/runtime 并提示。
- `keyring` 库 service 名固定为 `SerialLogAnalyzer`，账号名即 credential `name`。
- 日志存储：**仅手动导入/导出**（`io/storage/log_file_store.py`）；内存环形缓冲；无 Session 概念。

## 14. 错误体系（`core/errors.py`）

```text
AppError
├── ConfigError
├── SerialError ├── SerialConnectionError / SerialWriteError
├── NetworkError ├── NetworkTimeoutError / HttpStatusError
├── ProviderError
├── ResponseParseError
├── PointerError
├── PresetError
└── CredentialError
```

`io/` 把 Qt / keyring 错误翻译为上述类型；`ui/` 决定展示形式。不静默吞异常。

## 15. 启动方式

- 仓库根 `main.py`：薄启动器，把 `src/` 加入 `sys.path` 后调用 `serial_log_analyzer.bootstrap.main()`；`python main.py` 直接运行。
- 同时保留安装与 console script：`[project.scripts] serial-log-analyzer = "serial_log_analyzer.bootstrap:main"`。
- `bootstrap.main()`：创建 `QApplication` → 设置 metadata → 创建单个 `QNetworkAccessManager` → 构造 `io` 适配器 → 构造 `core` 服务 → 构造 `ui` → 显式注入 → `show()`。无 DI 框架。

## 16. UI 布局

```text
Menu / Toolbar
Port │ Baud │ Refresh │ Connect
┌─────────────────────┬─────────────────┐
│   Log Table         │  LLM Analysis   │
│ Time Level Module   │  Result / Chat  │
└─────────────────────┴─────────────────┘
Status bar
```

v1 不做：自定义标题栏、动画、多窗口工作区、复杂主题系统。

## 17. 建议模块划分

以下划分仅用于说明各模块的依赖关系与可独立开展的范围，实际分工可按工作量调整。

- **固件与串口链路**：`fw/`、命令协议、`io/serial`、`core/logs/line_framer` + `pipeline`。
- **界面**：`ui/**`、控制器转发、`LogTableModel`、`AnalysisPanel`。
- **LLM**：`core/llm/**`、`io/llm`、`providers/**`、`prompts/`。
- **配置与集成**：`presets/**`、preset / provider / credential 加载、settings、storage/export、diagnostics、集成测试、文档。

## 18. 测试策略

- 单元（不启 Qt）：`LineFramer`、`LogParser`、Preset 校验、Extended JSON Pointer、`RequestBuilder`、`SSEParser`、`ResponseParser`、`StreamProcessor`、`AnalysisContextBuilder`、凭据解析优先级。
- 集成：`QtSerialTransport`、`QtHttpTransport`、`QSettingsStore`、`KeyringStore`（mock）、资源加载器。
- UI（少量）：连接状态、批量插入、过滤、`AnalysisPanel` 流式更新。

## 19. v1 明确不做

asyncio、QThread、pyserial、httpx/requests、数据库、Web 服务、插件系统、动态脚本 Preset、全局 EventBus、全局 mutable singleton、Session 存储、多语言 i18n、自定义标题栏、多规则优先级 Preset、非 SSE 流式协议。

## 20. 实现顺序（供分工参考，实际划分由成员自行决定）

`M0 骨架` → `M1 core 纯逻辑`（models / errors / pointer / parser / preset）→ `M2 串口与日志 UI` → `M3 LLM`（loader / request / 非流式 → 流式）→ `M4 分析交互`（上下文 / 单次 + 多轮 / prompt）→ `M5 凭据管理` → `M6 固件与命令通道` → `M7 打磨`（settings / 导入导出 / diagnostics / 文档）。
