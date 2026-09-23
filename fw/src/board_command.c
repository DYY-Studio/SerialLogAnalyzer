/**
 * @file board_command.c
 * @brief 命令通道的最小参考实现（骨架，需按实际 SDK 补全 UART 读缓冲轮询）。
 */

#include "board_command.h"

#include <string.h>

#include "log_macro.h"

#define SLA_FW_VERSION "1.0.0"
#define SLA_LOGLEVEL_DEFAULT "D"

/** 当前板上日志过滤级别，可由 LOGLEVEL 命令修改。 */
static char g_log_level[2] = SLA_LOGLEVEL_DEFAULT;

/** @brief 比较命令首字段，返回真实参数指针；不匹配返回 NULL。 */
static const char *match_command(const char *line, const char *name)
{
    size_t len = strlen(name);
    if (strncmp(line, name, len) != 0) {
        return NULL;
    }
    if (line[len] == '\0') {
        return line + len;
    }
    if (line[len] != ' ') {
        return NULL;
    }
    return line + len + 1;
}

void BoardCommand_ReplyVersion(void)
{
    printf(SLA_REPLY_OK "fw=%s chip=hi3861\r\n", SLA_FW_VERSION);
}

void BoardCommand_HandleLine(const char *line)
{
    const char *arg;

    if ((arg = match_command(line, "PING")) != NULL && *arg == '\0') {
        printf(SLA_REPLY_OK "PONG\r\n");
        return;
    }
    if ((arg = match_command(line, "VERSION")) != NULL && *arg == '\0') {
        BoardCommand_ReplyVersion();
        return;
    }
    if ((arg = match_command(line, "HELP")) != NULL && *arg == '\0') {
        printf(SLA_REPLY_OK "PING VERSION HELP TEST LOGLEVEL\r\n");
        return;
    }
    if ((arg = match_command(line, "TEST")) != NULL) {
        if (*arg == '\0') {
            printf(SLA_REPLY_ERR "%d missing test name\r\n", SLA_ERR_INVALID_ARGUMENT);
            return;
        }
        printf(SLA_REPLY_OK "TEST %s started\r\n", arg);
        LOGI("test", "run test %s", arg);
        return;
    }
    if ((arg = match_command(line, "LOGLEVEL")) != NULL) {
        if (*arg == '\0' || arg[1] != '\0') {
            printf(SLA_REPLY_ERR "%d invalid log level\r\n", SLA_ERR_INVALID_ARGUMENT);
            return;
        }
        g_log_level[0] = *arg;
        printf(SLA_REPLY_OK "LOGLEVEL %c\r\n", g_log_level[0]);
        return;
    }
    printf(SLA_REPLY_ERR "%d unknown command\r\n", SLA_ERR_UNKNOWN_COMMAND);
}
