/**
 * @file sla_firmware.c
 * @brief SerialLogAnalyzer 固件的实机入口：日志输出 + 命令通道。
 *
 * 通过 UART0（板载 USB 转串口，115200-8-N-1）与 PC 端通信：
 * - 日志任务周期性输出 `[LEVEL] [tag] message`（格式见 docs/protocols/board-protocol.md）；
 * - 命令任务读取 UART0 收到的整行文本并交给 BoardCommand_HandleLine 处理。
 *
 * 说明：UART0 由系统控制台初始化，本文件不重复调用 hi_uart_init，避免打断 printf。
 */

#include <string.h>
#include <unistd.h>

#include "ohos_init.h"
#include "cmsis_os2.h"
#include "hi_uart.h"

#include "board_command.h"
#include "log_macro.h"

#define SLA_LOG_TASK_STACK (4 * 1024)
#define SLA_CMD_TASK_STACK (4 * 1024)

/** 心跳日志间隔（微秒）。 */
#define SLA_LOG_PERIOD_US (2000 * 1000)
/** 命令轮询空闲时的休眠，避免空转（微秒）。 */
#define SLA_CMD_POLL_DELAY_US (20 * 1000)
/** 单条命令最长字节数；超长部分丢弃。 */
#define SLA_CMD_LINE_MAX 128

/**
 * @brief 日志任务：输出一条多行示例后周期性打印心跳。
 */
static void SlaLogTask(void)
{
    uint32_t tick = 0;

    LOGI("main", "system ready");
    LOGD("boot", "log task started");

    /* 多行日志：后续行以行首空白开头，PC 端会并入上一条。 */
    LOGE("demo", "assert failed");
    LOG_CONT("at osTimerStart (timer.c:128)");
    LOG_CONT("at app_main (main.c:57)");

    while (1) {
        tick++;
        LOGI("app", "heartbeat tick=%u", tick);
        if ((tick % 5) == 0) {
            LOGW("app", "periodic warn tick=%u", tick);
        }
        usleep(SLA_LOG_PERIOD_US);
    }
}

/**
 * @brief 命令任务：轮询 UART0，按行调用命令处理器。
 */
static void SlaCmdTask(void)
{
    uint8_t chunk[32];
    char line[SLA_CMD_LINE_MAX];
    size_t line_len = 0;

    while (1) {
        hi_s32 n = hi_uart_read(HI_UART_IDX_0, chunk, sizeof(chunk));
        for (hi_s32 i = 0; i < n; i++) {
            char c = (char)chunk[i];
            if (c == '\r' || c == '\n') {
                if (line_len > 0) {
                    line[line_len] = '\0';
                    BoardCommand_HandleLine(line);
                    line_len = 0;
                }
            } else if (line_len < SLA_CMD_LINE_MAX - 1) {
                line[line_len++] = c;
            }
        }
        usleep(SLA_CMD_POLL_DELAY_US);
    }
}

/**
 * @brief 固件入口：创建日志任务与命令任务。
 *
 * 由 OpenHarmony 启动流程通过 `SYS_RUN` 注册，系统就绪后调用。
 */
static void SlaFirmwareInit(void)
{
    osThreadAttr_t attr;

    /* UART0 默认仅作日志控制台（TX）；先 deinit 再 init 才能开启 RX，否则命令任务读不到数据。 */
    hi_uart_attribute uart_cfg = {115200, 8, 1, 0, 0};
    (hi_void)hi_uart_deinit(HI_UART_IDX_0);
    if (hi_uart_init(HI_UART_IDX_0, &uart_cfg, HI_NULL) != HI_ERR_SUCCESS) {
        LOGE("main", "uart0 rx init failed");
    } else {
        LOGI("main", "uart0 rx ready");
    }

    memset(&attr, 0, sizeof(attr));
    attr.name = "sla_log";
    attr.stack_size = SLA_LOG_TASK_STACK;
    attr.priority = osPriorityNormal;
    if (osThreadNew((osThreadFunc_t)SlaLogTask, NULL, &attr) == NULL) {
        LOGE("main", "create log task failed");
    }

    attr.name = "sla_cmd";
    attr.stack_size = SLA_CMD_TASK_STACK;
    attr.priority = osPriorityNormal1;
    if (osThreadNew((osThreadFunc_t)SlaCmdTask, NULL, &attr) == NULL) {
        LOGE("main", "create cmd task failed");
    }
}

SYS_RUN(SlaFirmwareInit);
