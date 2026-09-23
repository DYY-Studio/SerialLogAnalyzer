# Hi3861 日志发送固件（fw/）

本目录存放 Hi3861 开发板侧的日志发送固件：通过 UART 输出结构化日志，
并响应 PC 端发来的简单文本命令。

## 约定的日志格式

每行一条日志，格式固定为：

```text
[LEVEL] [tag] message\r\n
```

示例：

```text
[I] [wifi] connected to AP
[W] [wifi] retry 2/5
[E] [uart] rx overflow
[D] [main] boot stage 3
```

多行日志（栈堆、后续缩进行）直接以换行输出，后续行以行首空白开头：

```text
[E] [main] assert failed
    at osTimerStart (timer.c:128)
    at app_main (main.c:57)
```

可选变体（如需记录设备运行时间）：在级别前增加一对方括号：

```text
[  12.345] [D] [wifi] scanning
```

> 选择该变体时，PC 端需切换到 `hi3861-timestamped` Preset（见 `presets/logs/`）。

## 提供的日志宏

`include/log_macro.h` 定义了 `LOGV / LOGD / LOGI / LOGW / LOGE` 五个宏，
内部统一走 `printf`，请勿在业务代码中直接手写日志格式，避免格式漂移。
新增级别标识时需同步更新 PC 端 `presets/logs/*.yaml` 的 `level_map`。

## 命令通道

PC 端发送以 `\r\n` 结尾的文本命令，固件以 `@OK ...` 或 `@ERR <code> <msg>` 响应：

| 命令 | 响应示例 | 说明 |
|---|---|---|
| `PING` | `@OK PONG` | 连通性检查 |
| `VERSION` | `@OK fw=1.0.0 chip=hi3861` | 固件与芯片版本 |
| `HELP` | `@OK PING VERSION HELP TEST LOGLEVEL` | 命令列表 |
| `TEST <name>` | `@OK TEST wifi started` | 触发指定自测（wifi / uart / gpio） |
| `LOGLEVEL <L>` | `@OK LOGLEVEL W` | 设置板上最低输出级别 |

约定：

- 响应前缀固定为 `@`，与 `[` 开头的日志行天然区分；
- 未知命令返回 `@ERR 1 unknown command`；
- 参数错误返回 `@ERR 2 invalid argument`；
- 命令解析在主循环中轮询 UART 接收缓冲完成，避免在中断里做字符串处理。

## 构建方式

1. 在 DevEco Device Tool / OpenHarmony 源码树中导入 `fw/` 作为示例工程；
2. 将 `include/log_macro.h` 加入头文件搜索路径，`src/` 下源文件加入编译；
3. 使用 Hi3861 默认 UART0（115200-8-N-1）作为日志与命令通道；
4. 烧写后可用 `python main.py` 连接验证。

> 本目录只提供日志宏与命令协议的参考实现骨架，完整工程由固件负责同学按
> 实际 SDK 版本补全。
