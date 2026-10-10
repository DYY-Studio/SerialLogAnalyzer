/**
 * @file log_demo.c
 * @brief 日志宏与命令通道的最小演示（骨架）。
 *
 * 烧写后可观察 PC 端日志表格是否逐行正确解析；
 * 用串口助手发送 PING / TEST wifi 可验证命令通道。
 */

#include "board_command.h"
#include "log_macro.h"

/**
 * @brief 演示输出各类日志与一条多行日志。
 *
 * 注意：仅在演示 / 自测路径中调用，量产路径应受日志级别过滤。
 */
void LogDemo_Run(void)
{
    LOGI("main", "system ready");
    LOGD("wifi", "scanning channels");
    LOGW("wifi", "retry 1/5");
    LOGE("uart", "rx overflow");
    LOG_CONT("at uart_isr (uart.c:210)");
    LOG_CONT("at rx_task (task.c:88)");
}

/**
 * @brief UART 接收轮询示例：攒够一行后交给命令解析。
 *
 * 实际工程请使用 SDK 提供的 UART 读接口与环形缓冲，此处仅示意调用位置。
 */
void LogDemo_PollUart(void)
{
    /* char line[128];
       while (uart_read_line(line, sizeof(line))) {
           BoardCommand_HandleLine(line);
       } */
}
