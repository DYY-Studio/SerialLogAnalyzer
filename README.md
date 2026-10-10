# SerialLogAnalyzer

PC 端**通用串口日志分析工具**：从任意串口设备实时接收并结构化解析日志，并可把日志上下文
提交给 LLM 获得诊断建议。解析规则由 YAML Preset 声明式定义，不绑定具体芯片或固件，
仓库自带 Hi3861 的示例 Preset 与配套固件。

## 功能

- 串口连接设备，实时接收日志（`QSerialPort`，单 Qt 事件循环）
- YAML Preset 声明式解析：级别 / 模块 / 消息字段提取，多行日志合并，未识别行安全回退
- 日志表格：级别 / 模块 / 文本过滤、暂停滚动、清空、手动导入导出
- LLM 分析：单次分析 + 多轮追问，SSE 流式输出
- Provider 配置驱动：OpenAI 兼容、OpenAI Responses、Anthropic、Google Gemini（YAML 声明）
- 凭据管理：系统 Keychain 优先，环境变量回退，支持运行时临时输入
- PC → 板命令通道：`PING` / `VERSION` / `HELP` / `TEST`

## 快速开始

```bash
git clone <repo-url> SerialLogAnalyzer
cd SerialLogAnalyzer

uv venv --python 3.12
uv sync --extra dev

uv run python main.py
```

不使用 uv 时，也可用任意 Python 3.11–3.14 解释器创建虚拟环境后安装依赖：

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python main.py
```

## 使用流程

1. 工具栏选择串口与波特率（Hi3861 常用 115200），点击连接。
2. 日志实时进入表格；使用过滤栏按级别 / 模块 / 关键字筛选。
3. 选中若干行日志，在右侧分析面板选择上下文范围与目标，提交给 LLM。
4. 结果流式显示；可在同一会话中继续追问。
5. 需要留档时，通过“导出日志”保存为文本文件。

## 项目结构

```text
main.py                  源码直跑入口
src/serial_log_analyzer/
  core/                  纯 Python 业务逻辑与模型（无 Qt 依赖）
  io/                    Qt / 系统适配（串口、网络、设置、凭据、存储）
  ui/                    PySide6 界面与控制器
  bootstrap.py           依赖组装根
presets/logs/            日志解析 Preset（YAML）
providers/adapters|profiles/  LLM 接口声明（YAML）
prompts/                 分析 Prompt 模板
fw/                      Hi3861 日志发送固件
docs/protocols/          协议规范
```

## 文档

- [`docs/llm-integration.md`](docs/llm-integration.md)：LLM 模块进度、SenseNova/书生配置与对接方式（在线验证待完成）

- [`DESIGN.md`](DESIGN.md)：完整架构设计（分层、接口、数据流）
- [`DEVELOPMENT.md`](DEVELOPMENT.md)：开发环境、运行与调试、协作约定
- [`AGENTS.md`](AGENTS.md)：面向 AI 助手与协作者的编码约定
- [`docs/protocols/board-protocol.md`](docs/protocols/board-protocol.md)：板上日志格式与命令通道
- [`docs/protocols/log-preset.md`](docs/protocols/log-preset.md)：日志 Preset schema
- [`docs/protocols/provider.md`](docs/protocols/provider.md)：LLM Provider schema
- [`docs/protocols/json-pointer.md`](docs/protocols/json-pointer.md)：扩展 JSON Pointer 规范
- [`docs/protocols/credentials.md`](docs/protocols/credentials.md)：凭据存储规范

## 许可

[MIT](LICENSE)


## 本地模型配置

接口地址、模型、流式开关和超时分别位于 `providers/profiles/sensenova.yaml` 与
`providers/profiles/internlm.yaml`。本地密钥放项目根目录 `.env`，变量名见 `.env.example`。
`.env` 已被 Git 忽略，不得提交。LLM 组装入口会自动读取它，进程环境同名值优先。
完整窗口与启动入口仍待实现，当前使用方式见 [LLM 接入说明](docs/llm-integration.md)。
