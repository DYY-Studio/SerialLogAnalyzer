# 板上日志格式与命令协议

本文档是 PC 端与 Hi3861 固件之间的**线上协议**约定。任何一方修改格式，必须先改本文档，
再同步修改 `presets/logs/*.yaml`（PC 侧）与 `fw/`（板侧）。

## 1. 日志行格式

```text
[LEVEL] [tag] message\r\n
```

| 部分 | 说明 |
|---|---|
| `LEVEL` | 级别标识，单个字母或单词，如 `V` `D` `I` `W` `E`；映射规则见 Preset 的 `level_map` |
| `tag` | 模块名，不含方括号，如 `wifi` `uart` `main`；可为 `-` 表示无模块 |
| `message` | 消息正文，允许包含任意字符（不含换行） |
| 行尾 | 固定 `\r\n`，PC 端分帧器同时兼容 `\n` |

示例：

```text
[I] [main] system ready
[W] [wifi] retry 2/5
[E] [uart] rx overflow
```

### 1.1 多行日志

栈堆或长消息的后续行以**行首空白**开头，PC 端会将其并入上一条：

```text
[E] [main] assert failed
    at osTimerStart (timer.c:128)
    at app_main (main.c:57)
```

### 1.2 可选：板上时间戳

若固件开启运行时间输出，行首增加一对方括号：

```text
[  12.345] [D] [wifi] scanning
```

该变体对应 PC 端 Preset `hi3861-timestamped`，值会填入 `LogEntry.device_time`；
未开启时 PC 端始终以接收时刻 `received_at` 作为时间基准。

## 2. 命令通道

PC 端发送文本命令（`\r\n` 结尾），固件同步或异步回复一行结果。

### 2.1 响应格式

```text
@OK <payload>
@ERR <code> <message>
```

- 前缀固定为 `@`，与 `[` 开头的日志行不会冲突；
- `code` 为无符号整数，见错误码表；
- PC 端不会把 `@` 开头的行写入日志表格，而是显示在底部「命令」面板的回复历史里。

### 2.2 命令表

| 命令 | 成功响应 | 说明 |
|---|---|---|
| `PING` | `@OK PONG` | 连通性检查 |
| `VERSION` | `@OK fw=1.0.0 chip=hi3861` | 固件与芯片版本 |
| `HELP` | `@OK PING VERSION HELP TEST` | 命令列表 |
| `TEST <name>` | `@OK TEST wifi started` | 触发自测；`name` ∈ {`wifi`, `uart`, `gpio`} |

### 2.3 错误码

| code | 含义 |
|---|---|
| 1 | 未知命令 |
| 2 | 参数非法 |
| 3 | 当前状态不支持该命令 |

### 2.4 交互约定

- 命令解析在主循环轮询完成，不在中断上下文处理字符串；
- 固件可在收到 `TEST` 后先回 `@OK`，再异步输出测试日志；
- PC 端超时时间建议 2 秒，超时后在「命令」面板提示，不影响日志流。
