# 日志 Preset Schema

日志解析采用 YAML 声明式 Preset：不同固件或日志格式无需修改 Python 代码。
Preset 文件位于 `presets/logs/*.yaml`，用户可在用户配置目录的 `presets/logs/` 下
放置同名文件覆盖内置版本（Windows `%APPDATA%\SerialLogAnalyzer`，其他平台
`~/.config/SerialLogAnalyzer`，可用 `SLA_CONFIG_HOME` 覆盖）。

**硬约束**：YAML 只描述规则，不允许执行任意 Python 表达式、`eval` 或嵌入脚本。

## 1. 完整字段

```yaml
schema_version: 1               # 必填，当前固定为 1
preset_id: hi3861-default       # 必填，^[a-z][a-z0-9-]*$ 且必须等于文件主名
display_name: "Hi3861 默认日志"  # 必填，界面展示名

line:                           # 必填，行匹配规则
  pattern: '^\s*(?:\[(?P<time>[^\]]+)\]\s*)?\[(?P<level>[A-Za-z]+)\]\s*\[(?P<module>[^\]]+)\]\s*(?P<message>.*)$'
  level_map:                    # 必填，级别标识 → 固定级别集
    V: VERBOSE
    D: DEBUG
    I: INFO
    W: WARN
    E: ERROR
  continuation_pattern: '^\s+\S'  # 选填，匹配的行并入上一条
  fields:                         # 选填，从 message 抽取结构化字段 → LogEntry.extra
    temperature: 'temperature=(?P<value>[\d.]+)'

fallback:                       # 选填，无法匹配时的降级规则
  enabled: true
  level: UNKNOWN

commands:                       # 选填，命令面板快捷命令按钮列表
  - label: "PING"               # 必填，非空字符串（首尾去空白）
    command: "PING"             # 必填，发送或预填的文本
    mode: send                  # 选填，send（直接发送，默认）| prefill（预填到输入框）
    tooltip: "检查命令通道连通性" # 选填，按钮悬停提示
  - label: "TEST …"
    command: "TEST "            # prefill 模式保留末尾空格
    mode: prefill
    tooltip: "预填 TEST 前缀，等待补充场景名"
```

## 2. 行规则 `line`

| 字段 | 必填 | 说明 |
|---|---|---|
| `pattern` | 是 | 正则表达式，必须包含命名组 `level`、`module`、`message`；可选 `time` |
| `level_map` | 是 | 板上标识到固定级别集的映射，键为字符串，值为 `VERBOSE` / `DEBUG` / `INFO` / `WARN` / `ERROR` / `UNKNOWN` |
| `continuation_pattern` | 否 | 满足该正则的行并入上一条；缺省时不合并 |
| `fields` | 否 | 字段名 → 正则；对 `message` 做 `search`，命中取第一个捕获组（无捕获组则整体匹配）存入 `LogEntry.extra`；未命中的字段不出现 |

对齐要求：

- `level`、`module`、`message` 三个必需命名组任一缺失，或正则编译失败 → 加载报 `PresetError`；
- `module` 组可匹配到空串（如 `[-]`），此时 `LogEntry.module` 记为 `None`；
- `time` 组存在时填充 `LogEntry.device_time`，否则由 PC 侧接收时间兜底；
- `pattern` 中额外出现的命名组会被忽略，不影响解析（如需保留请开 Issue 讨论）；
- `fields` 可选，键为字段名（非空字符串），值为正则字符串；`fields` 非对象、字段名为空或正则非法 → 加载报 `PresetError`。

## 3. 级别映射 `level_map`

PC 端只支持固定级别集（带严重度顺序）：

```text
VERBOSE < DEBUG < INFO < WARN < ERROR < UNKNOWN
```

Preset 负责把板上的任意标识（`V` / `verbose` / `FATAL` …）映射到该集合。
未命中映射时该条记录为 `UNKNOWN`，日志仍正常保留，不丢弃、不报错。

## 4. 降级规则 `fallback`

| 字段 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 无法匹配的行是否保留 |
| `level` | `UNKNOWN` | 降级条目的级别 |

`enabled: false` 时，不匹配的行会被静默忽略（`raw` 不再保留），仅在日志格式高度可控时使用。

## 5. 快捷命令 `commands`

`commands` 为可选列表，声明命令面板中展示的快捷按钮；省略或设为 `[]` 时隐藏快捷按钮栏。每个列表项必须是包含下列字段的对象：

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `label` | 是 | — | 按钮展示文案，必须为非空字符串（加载时首尾去空白） |
| `command` | 是 | — | 发送或预填的命令文本，`.strip()` 后必须非空；`mode: send` 时首尾去空白（`.strip()`），`mode: prefill` 时仅去左侧空白（`.lstrip()`）以保留末尾空格 |
| `mode` | 否 | `send` | 仅允许 `send`（点击后直接发送）或 `prefill`（点击后填入输入框并把光标移至末尾，不直接发送） |
| `tooltip` | 否 | `""` | 可选悬停提示文本，必须为字符串（首尾去空白） |

## 6. 资源查找顺序

1. 用户配置目录 `presets/logs/`（Windows `%APPDATA%\SerialLogAnalyzer`，
   其他平台 `~/.config/SerialLogAnalyzer`，可用 `SLA_CONFIG_HOME` 覆盖）
2. 源码运行时的仓库根 `presets/logs/`
3. 包内 `serial_log_analyzer/resources/presets/logs/`

同 `preset_id` 时高优先级覆盖低优先级，便于在不改仓库的前提下适配自己的固件。
完整规则见 `docs/configuration.md`。

## 7. 校验与错误

| 情况 | 行为 |
|---|---|
| 文件缺失或 YAML 非法 | 加载报 `PresetError`，界面提示并继续使用当前 Preset |
| 缺少必填字段 / 类型错误 | 同上 |
| 正则编译失败或缺少必需组 | 同上 |
| `fields` 非对象 / 字段名为空 / 字段正则非法 | 同上 |
| `commands` 非列表 / 元素含未知字段 / `mode` 非法 / `label` 或 `command` 为空 | 同上 |
| 未知顶层字段 | 报错（避免拼写错误被静默忽略） |
| 级别标识未命中映射 | 运行期降级为 `UNKNOWN`，不报错 |

## 8. 示例：新增一个固件格式

```yaml
schema_version: 1
preset_id: my-custom-fw
display_name: "My Custom Firmware"

line:
  pattern: '^(?P<level>TRACE|NOTICE|FAULT)\s+(?P<module>\w+):\s*(?P<message>.*)$'
  level_map:
    TRACE: DEBUG
    NOTICE: INFO
    FAULT: ERROR

fallback:
  enabled: true
  level: UNKNOWN
```
