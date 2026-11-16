/**
 * @file board_command.c
 * @brief 命令通道的参考实现与可控自测故障样例。
 */

#include "board_command.h"

#include <stddef.h>
#include <string.h>

#include "log_macro.h"

#define SLA_FW_VERSION "1.0.0"

typedef void (*TestScenarioFn)(void);

typedef struct {
    const char *name;
    TestScenarioFn run;
} TestScenario;

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

static void emit_test_wifi(void)
{
    LOGD("wifi", "scanning ap channels");
    LOGW("wifi", "retry 1/3 connect ap");
    LOGE("wifi", "reconnect failed errno=-11");
}

static void emit_test_uart(void)
{
    /* 连续输出同类溢出日志，便于 PC 端验证窗口聚合与冷却告警。 */
    LOGE("uart", "uart rx overflow dropped=16");
    LOGE("uart", "uart rx overflow dropped=24");
    LOGE("uart", "uart rx overflow dropped=32");
}

static void emit_test_gpio(void)
{
    LOGI("gpio", "pin=LED2 self-test start");
    LOGI("gpio", "pin=LED2 toggle ok");
}

static void emit_test_memory(void)
{
    LOGE("memory", "malloc failed size=4096");
    LOG_CONT("at pvPortMalloc (heap.c:184)");
    LOG_CONT("at sensor_buf_alloc (app.c:92)");
}

static void emit_test_sensor(void)
{
    LOGE("i2c", "i2c read failed addr=0x38 errno=-5");
    LOGE("sensor", "read failed dev=sht20");
}

static void emit_test_watchdog(void)
{
    LOGW("scheduler", "task worker deadline exceeded delay_ms=120");
    LOGE("watchdog", "watchdog timeout task=worker");
    LOG_CONT("at wdt_feed_check (wdt.c:64)");
}

static const TestScenario kTestScenarios[] = {
    {"wifi", emit_test_wifi},
    {"uart", emit_test_uart},
    {"gpio", emit_test_gpio},
    {"memory", emit_test_memory},
    {"sensor", emit_test_sensor},
    {"watchdog", emit_test_watchdog},
};

static void handle_test_command(const char *arg)
{
    size_t count = sizeof(kTestScenarios) / sizeof(kTestScenarios[0]);
    size_t i;

    if (*arg == '\0') {
        printf(SLA_REPLY_ERR "%d missing test name\r\n", SLA_ERR_INVALID_ARGUMENT);
        return;
    }
    if (strcmp(arg, "all") == 0) {
        printf(SLA_REPLY_OK "TEST %s started\r\n", arg);
        for (i = 0; i < count; i++) {
            kTestScenarios[i].run();
        }
        return;
    }
    for (i = 0; i < count; i++) {
        if (strcmp(arg, kTestScenarios[i].name) == 0) {
            printf(SLA_REPLY_OK "TEST %s started\r\n", arg);
            kTestScenarios[i].run();
            return;
        }
    }
    printf(SLA_REPLY_ERR "%d invalid test name\r\n", SLA_ERR_INVALID_ARGUMENT);
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
        printf(SLA_REPLY_OK "PING VERSION HELP TEST\r\n");
        return;
    }
    if ((arg = match_command(line, "TEST")) != NULL) {
        handle_test_command(arg);
        return;
    }
    printf(SLA_REPLY_ERR "%d unknown command\r\n", SLA_ERR_UNKNOWN_COMMAND);
}
