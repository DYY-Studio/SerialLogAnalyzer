/**
 * @file log_macro.h
 * @brief Hi3861 统一日志输出宏。
 *
 * 约定格式：[LEVEL] [tag] message\r\n
 * 与 PC 端 presets/logs/hi3861-default.yaml 的 pattern 一一对应；
 * 修改本文件中的格式常量时，必须同步更新 Preset。
 */

#ifndef SLA_LOG_MACRO_H
#define SLA_LOG_MACRO_H

#include <stdio.h>

/** @brief 日志级别标识（与 Preset level_map 对应）。 */
#define SLA_LOG_LEVEL_V "V"
#define SLA_LOG_LEVEL_D "D"
#define SLA_LOG_LEVEL_I "I"
#define SLA_LOG_LEVEL_W "W"
#define SLA_LOG_LEVEL_E "E"

/**
 * @brief 输出一条日志。
 * @param lv  级别标识字符串常量。
 * @param tag 模块名，不带方括号。
 * @param fmt printf 风格格式串。
 */
#define SLA_LOG(lv, tag, fmt, ...) \
    printf("[" lv "] [" tag "] " fmt "\r\n", ##__VA_ARGS__)

/** @brief 详细日志。 */
#define LOGV(tag, fmt, ...) SLA_LOG(SLA_LOG_LEVEL_V, tag, fmt, ##__VA_ARGS__)

/** @brief 调试日志。 */
#define LOGD(tag, fmt, ...) SLA_LOG(SLA_LOG_LEVEL_D, tag, fmt, ##__VA_ARGS__)

/** @brief 信息日志。 */
#define LOGI(tag, fmt, ...) SLA_LOG(SLA_LOG_LEVEL_I, tag, fmt, ##__VA_ARGS__)

/** @brief 警告日志。 */
#define LOGW(tag, fmt, ...) SLA_LOG(SLA_LOG_LEVEL_W, tag, fmt, ##__VA_ARGS__)

/** @brief 错误日志。 */
#define LOGE(tag, fmt, ...) SLA_LOG(SLA_LOG_LEVEL_E, tag, fmt, ##__VA_ARGS__)

/**
 * @brief 输出一条多行日志的后续行（行首缩进，PC 端会并入上一条）。
 * @param fmt printf 风格格式串。
 */
#define LOG_CONT(fmt, ...) printf("    " fmt "\r\n", ##__VA_ARGS__)

#endif /* SLA_LOG_MACRO_H */
