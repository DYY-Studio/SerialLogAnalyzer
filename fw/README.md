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

## 传感器日志与运行指示灯

固件启动时初始化板载 SHT20（温湿度）与 AP3216C（光照/接近/红外）传感器，并创建一个 IO 任务：

- 每 500ms 翻转运行指示灯 LED2（PCF8574 的 P2，低电平点亮），用于指示程序在运行；
- 每约 3s 输出一条传感器日志，并附带上报 LED 与风扇当前状态（风扇本固件不驱动，恒为 0）：

```text
[I] [sensor] led=1 fan=0 temperature=29.7 humidity=43.6 light=122 proximity=62 infrared=8
```

> LED2 对应 PCF8574 P2（`set_led`），来自 `FS-Hi3861-V4.2` 原理图网表：P0=风扇、
> P1=蜂鸣器、P2=LED（运行指示灯 LED2）、P3~P7=D0~D4（RJ12 扩展口，`set_D2` 即在 P5）。
> 传感器与 PCF8574 共用 I2C0，驱动直接复用 SDK 的
> `vendor/hqyj/fs_hi3861/common/bsp`，不复制代码。

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

## 构建与烧录（华清远见 FS-Hi3861 + hqyj OpenHarmony SDK）

本目录即完整固件源码（入口 `src/sla_firmware.c`）。因依赖 SDK 提供的
`ohos_init.h` / `cmsis_os2.h` / `hi_uart.h`，需放入 SDK 源码树内编译：

1. 将本目录复制进 SDK 的演示目录：
   `<sdk>/src/vendor/hqyj/fs_hi3861/demo/sla_fw/`（含 `BUILD.gn`、`include/`、`src/`）。
2. 在 `<sdk>/src/vendor/hqyj/fs_hi3861/demo/BUILD.gn` 的 `features` 中启用
   `"sla_fw:sla_fw",`，并确保其它 demo 保持注释（多入口会冲突）。
3. 确认 `<sdk>/src/applications/sample/wifi-iot/app/BUILD.gn` 已挂载
   `//vendor/hqyj/fs_hi3861/demo:demo`。
4. **关闭 SDK 的 AT 控制台**：SDK 默认启用 AT 命令组件（`CONFIG_AT_SUPPORT`），
   它在 UART0 上回显输入并对未知命令回 `ERROR`，会与固件命令通道冲突。
   这是 SCons 构建的开关：在 `<sdk>/src/device/hisilicon/hispark_pegasus/sdk_liteos/build/scripts/common_env.py`
   中把 `set_config('env_cfg', 'CONFIG_AT_SUPPORT', ...)` 的值由 `'y'` 改为 `'n'`。
   （`config.gni` / `build/make_scripts/config.mk` 里的同名 `-DCONFIG_AT_COMMAND` 也一并去掉，避免混淆。）
5. 编译：在工具链目录运行 `env_start.bat` 后 `cd <sdk>/src && hb build -f`。
   产物为 `out/hispark_pegasus/wifiiot_hispark_pegasus/Hi3861_wifiiot_app_allinone.bin`。
6. 烧录：DevEco Device Tool 的 `upload`，或 `burntool/BurnTool.exe` 加载上述 bin；
   串口 115200-8-N-1 查看日志并发送命令。

> 产品选择以实际 SDK 为准；本 SDK 中 `hqyj_fs_hi3861` 因缺少 `device/hqyj` 无法
> `hb set`，选 `hispark_pegasus` 即可（参见 `docs/protocols/board-protocol.md`）。
> 复制进 SDK 后，本目录与 SDK 内副本需保持同步。
