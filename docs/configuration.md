# 配置文件与本地数据

本文说明 SerialLogAnalyzer 的**文件放在哪里、字段怎么填、API Key 与设置如何加载与保存、日志如何导入导出、诊断信息从哪里取**。
完整的资源 schema 校验规则见 `docs/protocols/`（Preset / Provider / 凭据 / JSON Pointer），本文只做汇总与索引。

## 1. 总原则

- **声明式**：设备日志格式、模型服务、Prompt 全部由 YAML / Markdown 资源描述，代码里不硬编码具体芯片或厂商。
  仓库中**没有**任何脚本式配置，也不允许通过 `eval` / `exec` 执行配置内容。
- **用户资源覆盖内置资源**：同名资源以优先级更高的目录为准，内置文件本身永不被改写。
- **未知字段即错误**：任何资源的未知字段、非法值都会抛出 `ConfigError` / `PresetError`（继承自 `AppError`），
  错误信息带中文说明与来源文件路径；不会静默忽略。
- **`schema_version` 必填**：Preset = 1，Provider Profile = 1，LLM Adapter = 3。版本不符直接报错。
- **标识符即文件名**：`preset_id` / `profile_id` / `adapter_id` 必须与所在 YAML 的文件名（去扩展名）一致，
  且匹配 `^[a-z][a-z0-9-]*$`。

## 2. 资源目录与查找顺序

`CompositeResourceLoader`（`io/resources.py`）按下列顺序查找，先命中者生效：

| 优先级 | 目录 | 用途 |
|---|---|---|
| 1 | `SLA_CONFIG_HOME`（默认 `%APPDATA%\SerialLogAnalyzer`，其他平台 `~/.config/SerialLogAnalyzer`） | 用户自定义与覆盖 |
| 2 | 仓库根目录（源码直跑时自动识别） | 开发时的内置资源 |
| 3 | `serial_log_analyzer/resources/`（发行包内） | 安装后的内置资源 |

- 相对路径必须使用 `/` 分隔，禁止绝对路径与 `..`（越界会被拒绝）。
- 资源类型与路径：

| 资源 | 相对路径 | 格式 |
|---|---|---|
| 日志解析 Preset | `presets/logs/*.yaml` | YAML |
| LLM Adapter | `providers/adapters/*.yaml` | YAML |
| LLM Profile | `providers/profiles/*.yaml` | YAML |
| Prompt 模板 | `prompts/*.md` | Markdown + `string.Template` |

- 想确认「当前到底加载了哪些文件」：运行诊断（见 §8），报告会列出全部资源根目录与已加载清单。

## 3. Preset（设备日志解析）

路径 `presets/logs/<preset_id>.yaml`，字段速查（完整规则见 `docs/protocols/log-preset.md`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 固定 `1` |
| `preset_id` | 是 | 必须等于文件名 |
| `display_name` | 是 | 界面展示名（中文） |
| `line.pattern` | 是 | 行解析正则，必须含命名组 `level`、`module`、`message`，可选 `time` |
| `line.level_map` | 是 | 级别标识 → `VERBOSE`/`DEBUG`/`INFO`/`WARN`/`ERROR`/`UNKNOWN` |
| `line.continuation_pattern` | 否 | 命中则并入上一条日志（多行栈堆） |
| `line.fields` | 否 | 从 `message` 抽取结构化字段（`name: 正则`，需含命名组 `value`） |
| `fallback.enabled` / `fallback.level` | 否 | 未匹配行是否保留，默认 `true` / `UNKNOWN` |

级别标识未在 `level_map` 中命中时**不报错**，运行期记为 `UNKNOWN`。

```yaml
schema_version: 1
preset_id: my-board
display_name: "我的板子日志"
line:
  pattern: '^\[(?P<level>[A-Za-z]+)\]\s*\[(?P<module>[^\]]+)\]\s*(?P<message>.*)$'
  level_map:
    I: INFO
    W: WARN
    E: ERROR
  continuation_pattern: '^\s+\S'
  fields:
    temperature: 'temperature=(?P<value>[\d.]+)'
fallback:
  enabled: true
  level: UNKNOWN
```

## 4. LLM Adapter 与 Profile

> **术语**：**Adapter** 决定请求与响应的**格式**（OpenAI Compatible / OpenAI Responses / Anthropic / Gemini）；
> **Profile** 决定**连哪个服务、用哪个模型与参数**。仓库里的 **Preset** 专指设备日志格式
> （`presets/logs/*.yaml`，见 §3），与模型配置无关。

### 4.1 Adapter（`providers/adapters/<adapter_id>.yaml`）

内置 `openai-compatible`、`openai-responses`、`anthropic`、`google-gemini`。
Adapter 描述「一次请求长什么样、响应内容在哪个 JSON Pointer」，字段与占位符规则见 `docs/protocols/provider.md`。

要点：

- `endpoint` 是**相对路径**（不得含 `://`），由 Profile 的 `base_url` 拼接。
- `headers` / `body` 中的占位符只有白名单内的才会被替换：
  `${model}` `${system}` `${messages}` `${temperature}` `${max_output_tokens}` `${stream}` `${api_key}`。
- `body` 中含 `${` 的字符串必须**整个字符串恰好是一个占位符**；`"prefix-${model}"` 这类拼接会报错，
  必须拆成独立字段或用 Adapter 结构表达。
- `response_content_pointer` 必填；`response_reasoning_content_pointers`、`usage`、`models`（模型发现）、
  `streaming`（SSE 流式）按需声明。JSON Pointer 支持 RFC 6901 转义与数组负索引（`-1` 表示末元素），
  非法指针（`-0`、裸 `-`、越界、类型不符）会报 `ConfigError` / `PointerError`。

### 4.2 Profile（`providers/profiles/<profile_id>.yaml`）

Profile 描述「连哪个服务、用哪个模型、用哪把 Key」，是界面上可切换的实体。

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 固定 `1` |
| `profile_id` | 是 | 必须等于文件名 |
| `adapter_id` | 是 | 必须能加载到对应 Adapter |
| `base_url` | 是 | `http://` 或 `https://` 开头，**不得以 `/` 结尾** |
| `model` | 是 | 传给 Adapter 的 `${model}` |
| `stream` | 否 | 默认 `true`；Adapter 未声明 `streaming` 时必须为 `false` |
| `request_timeout_seconds` | 否 | 默认 `120`，必须为正数 |
| `credential` | 否 | 见 §5，缺省为「运行时输入」 |
| `extra_body` / `extra_headers` | 否 | 追加到请求体 / 请求头的对象，键值直接透传 |

```yaml
schema_version: 1
profile_id: my-deepseek
adapter_id: openai-compatible
base_url: https://api.deepseek.com/v1
model: deepseek-chat
stream: true
request_timeout_seconds: 120
credential:
  kind: keyring
  name: my-deepseek      # 系统钥匙串账号名（缺省取 profile_id）
extra_body: {}
extra_headers: {}
```

### 4.3 在界面上保存 Profile

「模型服务」对话框只做界面编辑；点击**保存到用户配置**时通过 `ProfileStore` 写入

```text
<用户配置目录>/providers/profiles/<profile_id>.yaml
```

- 写入采用「临时文件 + 原子替换」，避免半截文件；
- 只写用户配置目录，**不会修改**仓库/内置文件；
- 保存前先用 `profile_writer.dump_profile()` 校验字段，非法值会弹窗提示并保持对话框打开。

### 4.4 Profile 编辑器的当前边界（壳子）

仓库内置的 `providers/profiles/*.yaml` 本身就是示例，**改选中的那一条**即可，不需要先「新建」。
因此「模型服务」对话框目前刻意只做**选择已有 Profile + 编辑少量字段 + 保存**：

| 层 | 归哪个分工（DESIGN §17） | 现状 |
|---|---|---|
| `providers/**` 资源 schema 与运行期语义（模型发现、请求参数、流式） | LLM 分工 | 运行期仍为桩（`core/llm/request.py` 等） |
| 加载 / 校验 / 序列化 / 原子落盘 / 凭据解析 | 配置与集成（本文档） | 已实现 |
| 界面形态（Profiles 管理器、新建 / 复制 / 删除 / 模型下拉） | 界面分工 | 只有壳子 |

- **壳子已覆盖**：选择 Profile、编辑 `base_url` / `model` / `stream` / `request_timeout_seconds`、
  查看 Adapter 与凭据来源、保存到用户配置目录。
- **未实现（本任务范围外）**：新建 / 复制 / 删除 Profile、在界面上改选 Adapter、编辑
  `extra_body` / `extra_headers`、拉取服务端模型列表（依赖 LLM 分工的模型发现）。
- 模型参数（`${temperature}` / `${max_output_tokens}` 的**取值**）由 LLM 分工的 `RequestBuilder`
  决定，Profile 只负责声明模型与 `extra_body` 透传，所以界面暂不提供这两项。

## 5. API Key 与凭据

配置里不写明文密钥，只声明**从哪里取**。`credential` 段（见 `docs/protocols/credentials.md`）：

```yaml
credential:
  kind: keyring        # keyring | environment | runtime，只读这一个来源
  name: my-deepseek    # 钥匙串 account；缺省时取 profile_id
```

`kind: environment` 时写 `env_var: MY_DEEPSEEK_API_KEY` 代替 `name`；`kind: runtime` 不写来源字段。
同一个 `credential` 段**只能有一个来源字段**，多写会报 `ConfigError`。

解析顺序（`core/services/credential_resolver.py`）：

1. **本次会话的运行时输入**（对话框里临时输入，只存内存，键为 `name`，缺省为 `profile_id`）；
2. 未命中时读 `kind` 声明的那个来源，**不跨来源回落**；
3. 两者都没取到非空值时抛 `CredentialError`，错误信息列出已尝试的来源、失败原因与可换用的其他来源。

约定：

- 系统钥匙串 `service` 固定为 `SerialLogAnalyzer`，`account` 即凭据的 `name`。
- `kind: environment` 的值来自进程环境；进程里没有该变量时可读仓库根目录的本地 `.env`
  （`.env.example` 是模板，`.env` 被 Git 忽略）。
- 钥匙串不可用时（无 SecretService、后端为 fail/null 等）：`available=False`，界面把保存选项置灰，
  并提示声明 `kind: keyring` 的 Profile 取不到密钥，需要改用 `environment` 或 `runtime` 来源。
- 运行时输入**不会自动写入**钥匙串；只有用户显式勾选「保存到系统钥匙串」才调用 `save`。
- 「清除已保存的密钥」会删除钥匙串中的条目（需二次确认）。

也可以只靠环境变量运行，不触碰钥匙串：

```bash
export MY_DEEPSEEK_API_KEY=sk-...
```

## 6. 界面设置（QSettings）

简单偏好保存在系统配置中（Windows 注册表、macOS plist、Linux ini），键名集中定义在
`io/settings/qt_settings_store.py` 的 `SETTINGS_KEYS`：

| 键 | 含义 | 默认 |
|---|---|---|
| `window/geometry` | 主窗口几何 | 系统决定 |
| `window/state` | 工具栏/停靠状态 | 系统决定 |
| `window/splitter_sizes` | 分割条比例 | 预设比例 |
| `device/last_port` | 最近使用的串口 | 空 |
| `device/last_baudrate` | 最近波特率 | 空 |
| `llm/current_profile` | 当前 Profile | 首个可用 |
| `logs/current_preset` | 当前 Preset | 首个可用 |
| `logs/autoscroll` | 自动滚动 | `true` |
| `logs/capacity` | 日志环形缓冲容量（1000–1000000） | `100000` |
| `logs/app_log_level` | 应用日志级别 | `INFO` |
| `logs/export_dir` | 默认导出目录（留空用默认目录） | 空 |

- 复杂配置（Profile）**不放进** QSettings，统一用 YAML。
- 布尔值经 `get_bool()` 读取，兼容 `true`/`false` 与 `0`/`1`；`get_int()` / `get_str()` 在类型不符时回退默认值。
- 「设置」对话框只读写上述键，保存失败会提示用户并保持对话框打开。
- 保存后**立即生效**的项：自动滚动、日志容量（超出部分当场裁掉并同步表格）、应用日志级别；
  导出目录与当前 Profile / Preset 在下次使用时读取。
- 串口高级参数（数据位 / 校验位 / 停止位 / 流控）不落盘，只在本次会话内生效。
- 当前 LLM Profile 可在工具栏切换（换用对应 Adapter、写回 `llm/current_profile`）；
  「配置 → 切换日志 Preset…」切换 `logs/current_preset` 并**清空当前日志**（连接中不允许切换）。

## 7. 日志导出与导入

内存中的日志由 `LogPipeline` 的环形缓冲保存（无 Session 概念、不自动落盘）。留档通过
`io/storage/log_file_store.py` 的 `LogFileStore` 手动导出；日志视图的「导出」按目标后缀
选择格式，「导入」把文本文件逐行喂回既有解析流水线（走同一个 Preset）。

| 格式 | 后缀 | 内容 |
|---|---|---|
| `ExportFormat.TEXT` | `.log` | 每条日志的原始行（`LogEntry.raw`），最接近串口原始输出 |
| `ExportFormat.CSV` | `.csv` | 表头 `sequence,received_at,level,module,device_time,message,extra`，`extra` 为紧凑 JSON |
| `ExportFormat.JSONL` | `.jsonl` | 每条一行 JSON：`sequence`/`received_at`(微秒精度)/`level`/`module`/`device_time`/`continuation`/`message`/`extra`/`raw` |

- 编码统一 UTF-8，父目录自动创建；写失败抛 `AppError`（中文提示，不静默丢弃）。
- 默认文件名 `<stem>-YYYYmmdd-HHMMSS.<后缀>`，`stem` 只保留 ASCII 安全字符，留空时用 `serial-log`。
- 默认目录：`SLA_EXPORT_DIR` → 源码运行时 `<仓库根>/exports`（已被 `.gitignore` 忽略）→ 安装后 `~/SerialLogAnalyzer/exports`；
  界面里 `logs/export_dir` 可覆盖。
- **导入**：`import_entries(path, on_line)` 按行回调，跳过空行；导入的行按递增时间戳（步长 1 ms）模拟接收时间，
  便于在表格里按时间排序查看。

## 8. 诊断信息

一条命令即可打印（或导出）诊断报告，用于自查配置与提交 issue：

```bash
uv run python -m serial_log_analyzer.diagnostics              # 中文文本报告
uv run python -m serial_log_analyzer.diagnostics --json       # JSON 输出
uv run python -m serial_log_analyzer.diagnostics --export report.txt   # 同时写入文件
uv run python -m serial_log_analyzer.diagnostics --export .   # 传入已存在的目录时自动生成带时间戳的文件名
uv run python -m serial_log_analyzer.diagnostics --log-file app.log --no-log-tail
```

`--export` 的 PATH 可以是文件，也可以是已存在的目录（此时生成 `diagnostics-<时间戳>.txt`）；
`--log-file` 指定报告中展示的应用日志路径，`--no-log-tail` 表示不采集日志末尾。

报告内容（`diagnostics/report.py`）：

- 应用版本、Python 版本、可执行文件、操作系统；
- 用户配置目录、应用日志文件、**全部资源根目录（按优先级）**；
- 已加载的 Preset / Adapter / Profile 清单；
- 逐条**配置错误**（加载失败不会被隐藏，诊断本身也不会因此失败）；
- 系统钥匙串可用性；
- 应用日志末尾若干行。

退出码：`0` = 配置全部加载成功；`1` = 存在配置错误或导出失败。
因此可直接作为 CI 的资源校验步骤（例如提交前检查 `presets/` 是否还能加载）。

## 9. 应用日志

工具自身的日志与应用无关的设备日志**严格分离**：

- logger 名 `serial_log_analyzer`，通过 `get_logger(name)` 获取子 logger；
- 默认输出到 stderr，行格式 `时间 级别 logger: 消息`；
- 文件日志（可选）为 1 MB × 3 轮转，UTF-8，默认路径 `<用户配置目录>/logs/serial-log-analyzer.log`；
- `configure_logging()` 可重复调用（幂等），不会重复叠加 handler。

## 10. 环境变量汇总

| 变量 | 作用 | 默认 |
|---|---|---|
| `SLA_CONFIG_HOME` | 用户配置根目录（资源覆盖、Profile 保存、应用日志） | `%APPDATA%\SerialLogAnalyzer` / `~/.config/SerialLogAnalyzer` |
| `SLA_EXPORT_DIR` | 日志导出默认目录 | `<仓库根>/exports` / `~/SerialLogAnalyzer/exports` |
| `SLA_LOG_LEVEL` | 应用日志级别 `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` | `INFO`（非法值退回 `INFO` 并告警） |
| `SLA_LOG_FILE` | 应用日志文件路径，设置后启用文件日志 | 空（仅 stderr） |
| `SLA_HW_PORT` | 硬件联调门控测试使用的串口；未设置则跳过 | 空 |
| `<profile 的 env_var>` | 该 Profile 的 API Key | 空（仅当 `credential.kind=environment` 时使用；不跨来源回落） |

## 11. 相关文档

- [`docs/protocols/log-preset.md`](protocols/log-preset.md)：Preset schema 与校验规则
- [`docs/protocols/provider.md`](protocols/provider.md)：Adapter / Profile schema 与占位符
- [`docs/protocols/credentials.md`](protocols/credentials.md)：凭据来源与优先级
- [`docs/protocols/json-pointer.md`](protocols/json-pointer.md)：扩展 JSON Pointer（含负索引）
- [`docs/architecture.md`](architecture.md)：分层、代码决策与扩展点
- [`DEVELOPMENT.md`](../DEVELOPMENT.md)：环境、测试与调试
