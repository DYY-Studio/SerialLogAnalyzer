/**
 * @file board_command.h
 * @brief PC → 板命令通道的协议常量与解析声明（参考实现骨架）。
 *
 * PC 端发送以 \r\n 结尾的文本命令，固件以：
 *   @OK <payload>
 *   @ERR <code> <message>
 * 响应，详见 fw/README.md 与 docs/protocols/board-protocol.md。
 */

#ifndef SLA_BOARD_COMMAND_H
#define SLA_BOARD_COMMAND_H

/** @brief 响应前缀：成功。 */
#define SLA_REPLY_OK "@OK "
/** @brief 响应前缀：失败。 */
#define SLA_REPLY_ERR "@ERR "

/** @brief 错误码：未知命令。 */
#define SLA_ERR_UNKNOWN_COMMAND 1
/** @brief 错误码：参数非法。 */
#define SLA_ERR_INVALID_ARGUMENT 2
/** @brief 错误码：当前状态不支持。 */
#define SLA_ERR_UNSUPPORTED 3

/**
 * @brief 处理一行完整命令（不含行尾符）。
 * @param line 已去掉 \r\n 的命令文本。
 *
 * 实现位于 board_command.c；应在主循环中调用，不要在中断上下文调用。
 */
void BoardCommand_HandleLine(const char *line);

/**
 * @brief 输出当前固件版本（供 VERSION 命令使用）。
 */
void BoardCommand_ReplyVersion(void);

#endif /* SLA_BOARD_COMMAND_H */
