/**
 * @file sla_firmware.c
 * @brief SerialLogAnalyzer 固件的实机入口：日志输出 + 命令通道。
 *
 * 通过 UART0（板载 USB 转串口，115200-8-N-1）与 PC 端通信：
 * - 日志任务周期性输出 `[LEVEL] [tag] message`（格式见 docs/protocols/board-protocol.md）；
 * - 命令任务读取 UART0 收到的整行文本并交给 BoardCommand_HandleLine 处理；
 * - IO 任务翻转运行指示灯 LED2（PCF8574 P2）并周期性输出 SHT20/AP3216C 传感器读数。
 *
 * 说明：UART0 需先 deinit 再 init 才能开启 RX（见 SlaFirmwareInit）。
 */

#include <string.h>
#include <unistd.h>

#include "ohos_init.h"
#include "cmsis_os2.h"
#include "hi_uart.h"
#include "iot_errno.h"

#include "board_command.h"
#include "hal_bsp_ap3216c.h"
#include "hal_bsp_pcf8574.h"
#include "hal_bsp_sht20.h"
#include "log_macro.h"

#define SLA_LOG_TASK_STACK (4 * 1024)
#define SLA_CMD_TASK_STACK (4 * 1024)
#define SLA_IO_TASK_STACK (4 * 1024)

/** 心跳日志间隔（微秒）。 */
#define SLA_LOG_PERIOD_US (2000 * 1000)
/** 命令轮询空闲时的休眠，避免空转（微秒）。 */
#define SLA_CMD_POLL_DELAY_US (20 * 1000)
/** 单条命令最长字节数；超长部分丢弃。 */
#define SLA_CMD_LINE_MAX 128

/** 运行指示灯（LED2，PCF8574 P2）翻转间隔（微秒）。 */
#define SLA_IO_BLINK_US (500 * 1000)
/** 每翻转多少次输出一条传感器日志（约 3 秒）。 */
#define SLA_IO_SENSOR_EVERY 6

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
 * @brief IO 任务：翻转运行指示灯（LED2），并周期性输出传感器读数。
 *
 * 传感器为 SHT20（温度/湿度）与 AP3216C（光照/接近/红外）。
 * 日志同时上报 LED 与风扇状态；风扇本固件不驱动，恒为 0。
 */
static void SlaIoTask(void)
{
    uint8_t led_on = 0;
    uint32_t tick = 0;

    while (1) {
        led_on = !led_on;
        set_led(led_on);

        if ((tick % SLA_IO_SENSOR_EVERY) == 0) {
            float temperature = 0.0f;
            float humidity = 0.0f;
            uint16_t infrared = 0;
            uint16_t light = 0;
            uint16_t proximity = 0;

            /* 读取失败时不输出伪造读数，避免把 0 当成有效值。 */
            if (SHT20_ReadData(&temperature, &humidity) != IOT_SUCCESS ||
                AP3216C_ReadData(&infrared, &light, &proximity) != IOT_SUCCESS) {
                LOGE("sensor", "read failed");
            } else {
                LOGI("sensor",
                     "led=%u fan=0 temperature=%.1f humidity=%.1f light=%u proximity=%u infrared=%u",
                     led_on, temperature, humidity, light, proximity, infrared);
            }
        }

        tick++;
        usleep(SLA_IO_BLINK_US);
    }
}

/**
 * @brief 固件入口：初始化外设，创建日志、命令与 IO 任务。
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

    PCF8574_Init();
    SHT20_Init();
    AP3216C_Init();

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

    attr.name = "sla_io";
    attr.stack_size = SLA_IO_TASK_STACK;
    attr.priority = osPriorityNormal;
    if (osThreadNew((osThreadFunc_t)SlaIoTask, NULL, &attr) == NULL) {
        LOGE("main", "create io task failed");
    }
}

SYS_RUN(SlaFirmwareInit);
