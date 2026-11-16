# 异常检测规则 Schema

异常筛选、时间窗口归并与本地告警阈值采用 YAML 声明式配置，位于 `rules/anomalies/*.yaml`。
用户可在用户配置目录的 `rules/anomalies/` 下放置同名文件覆盖内置版本（Windows `%APPDATA%\SerialLogAnalyzer`，
其他平台 `~/.config/SerialLogAnalyzer`，可用 `SLA_CONFIG_HOME` 覆盖）。

**硬约束**：YAML 只描述规则与阈值，不允许执行任意 Python 表达式、`eval` 或嵌入脚本。

## 1. 完整字段

```yaml
schema_version: 1
rule_set_id: default
display_name: "通用嵌入式异常规则"

defaults:
  window_seconds: 60
  cooldown_seconds: 60
  max_evidence: 20

rules:
  - rule_id: memory-alloc-failed
    category: "内存分配失败"
    severity: CRITICAL
    enabled: true
    modules: []
    min_level: WARN
    keywords:
      - "malloc failed"
      - "out of memory"
    pattern: null
    thresholds: []
    immediate_alert: true
    min_occurrences: 1
    window_seconds: 60
    cooldown_seconds: 60

  - rule_id: sensor-overheat
    category: "传感器过温"
    severity: HIGH
    min_level: INFO
    modules:
      - "sensor"
    thresholds:
      - field: temperature
        op: gte
        value: 80.0
    immediate_alert: false
    min_occurrences: 3
    window_seconds: 60
    cooldown_seconds: 60
```

## 2. 顶层与默认值字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 固定为 `1` |
| `rule_set_id` | 是 | `^[a-z][a-z0-9-]*$`，且必须等于文件名主名 |
| `display_name` | 是 | 界面展示名（非空字符串） |
| `defaults` | 否 | 规则默认参数对象：`window_seconds`（正数，默认 `60`）、`cooldown_seconds`（非负数，默认 `60`）、`max_evidence`（正整数，默认 `20`） |
| `rules` | 是 | 非空规则对象数组，按声明顺序优先级匹配（首条命中规则生效） |

## 3. 单条规则 `rules[]`

| 字段 | 必填 | 说明 |
|---|---|---|
| `rule_id` | 是 | `^[a-z][a-z0-9-]*$`，同文件内唯一 |
| `category` | 是 | 异常分类名称，如「内存分配失败」「任务/调度超时」「驱动/外设错误」「通信异常」「其他/未知」 |
| `severity` | 是 | `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` |
| `enabled` | 否 | 布尔值，默认 `true` |
| `modules` | 否 | 限定模块名字符串列表（大小写不敏感）；省略或空列表表示匹配任意模块 |
| `min_level` | 否 | 最低日志级别门限（`VERBOSE`/`DEBUG`/`INFO`/`WARN`/`ERROR`/`UNKNOWN`，默认 `WARN`） |
| `keywords` | 否 | 大小写不敏感子串列表（优先推荐，零回溯风险） |
| `pattern` | 否 | 可选正则表达式字符串（长度上限 `256` 字符，大小写不敏感编译）；`keywords` 与 `pattern` 之间为**或**关系 |
| `thresholds` | 否 | 可选结构化数值阈值列表（`[{field, op, value}]`），针对 `LogEntry.extra` 做比较；列表内多个条件为**与**关系。`keywords`、`pattern`、`thresholds` 三者至少声明非空其一 |
| `immediate_alert` | 否 | 布尔值，默认 `false`；为 `true` 时首次命中即触发告警（仍受冷却约束） |
| `min_occurrences` | 否 | 正整数，默认 `1`；时间窗口内命中达到该次数时触发告警 |
| `window_seconds` | 否 | 正数，缺省继承 `defaults.window_seconds`；作为窗口聚合与计数依据（基于 `LogEntry.received_at`） |
| `cooldown_seconds` | 否 | 非负数，缺省继承 `defaults.cooldown_seconds`；同簇两次本地告警最小冷却间隔 |

### 3.1 `min_level` 与 `UNKNOWN` 语义

`LogLevel.UNKNOWN`（未能匹配 Preset 的降级行或未知级别标识符）在比较时**不会被当作 `ERROR`**：

- `min_level: WARN` / `ERROR` 仅匹配已识别的对应级别及以上，不会误报无级别启动打印；
- `min_level: VERBOSE` 放行全部级别（含 `UNKNOWN`）；
- `min_level: UNKNOWN` 仅匹配 `UNKNOWN`。

### 3.2 结构化数值阈值 `thresholds`

`thresholds` 与日志 Preset 的 `line.fields`（见 [`log-preset.md`](log-preset.md)）配合工作，对 `LogEntry.extra` 中抽出的结构化字段执行有限实数比较。

每项元素均为对象，**仅允许且必填**以下 3 个字段：

| 字段 | 类型与校验 | 说明 |
|---|---|---|
| `field` | 非空字符串（加载时首尾 `strip`，保留大小写） | 对应 `LogEntry.extra` 中的字段名 |
| `op` | 小写枚举字符串：`gt` / `gte` / `lt` / `lte` / `eq` / `ne` | 分别对应 `>`、`>=`、`<`、`<=`、`==`、`!=` |
| `value` | 有限实数（`int` 或 `float`，加载时转为 `float`） | 显式拒绝布尔值（`bool`）、`NaN`、`Inf` / `-Inf` 与字符串等非数值 |

#### 组合与匹配语义

1. **前置门限**：规则先依次判定 `enabled`、`min_level` 与 `modules`；任一不通过直接跳过。
2. **规则有效性**：单条规则至少须声明非空 `keywords`、`pattern` 或非空 `thresholds` 之一。
3. **文本 + 阈值组合**：
   - 仅声明文本条件（`keywords` / `pattern`）：满足 `(keyword_hit or pattern_hit)` 即命中；
   - 仅声明 `thresholds`：同时满足 `thresholds` 内**全部**条件（与关系）即命中；
   - 同时声明文本条件与 `thresholds`：须**同时**满足 `(keyword_hit or pattern_hit)` 与全部 `thresholds` 条件（文本条件与阈值条件之间为**与**关系）。
4. **有限数值比较与缺省跳过**：
   - 运行期从 `entry.extra.get(field)` 取值并尝试按有限实数解析（拒绝 `bool`、空串、非数字文本及 `nan`/`inf`/`-inf`）；
   - 当目标字段缺失或无法解析为有限实数时，**判定为不匹配该规则**（安全跳过，不抛异常、不静默回落为默认数值）；
   - `eq` 与 `ne` 采用稳健浮点比较：`math.isclose(actual, value, rel_tol=0.0, abs_tol=1e-9)`（`ne` 为其取反）。
5. **连续阈值变化归并**：命中后由 `normalize_message` 将消息正文中的动态数字脱敏为 `<NUM>`，同规则同模块的连续越界采样自动归并入同一个 `AnomalyCluster`。

## 4. 校验与错误

| 情况 | 行为 |
|---|---|
| 文件缺失 / YAML 非法 / 顶层非对象 | 抛出 `ConfigError` |
| 出现未知字段（顶层、`defaults`、`rules[]`、`thresholds[]`） | 抛出 `ConfigError`（不静默忽略拼写错误） |
| `rule_set_id` 不匹配文件名或 `rule_id` 重复 | 抛出 `ConfigError` |
| `keywords`、`pattern` 与 `thresholds` 同时缺失/为空 | 抛出 `ConfigError` |
| `thresholds` 非列表，或元素非对象 / 缺少 `{field, op, value}` 任一字段 | 抛出 `ConfigError` |
| `thresholds[].field` 为空或非字符串、`op` 非小写 `gt/gte/lt/lte/eq/ne` 之一 | 抛出 `ConfigError` |
| `thresholds[].value` 为 `bool`、`NaN`/`Inf` 或非数字类型 | 抛出 `ConfigError` |
| `pattern` 长度超过 256 或正则编译失败 | 抛出 `ConfigError` |
| `window_seconds` / `min_occurrences` / `max_evidence` 非正数，或 `cooldown_seconds` 为负 | 抛出 `ConfigError` |
