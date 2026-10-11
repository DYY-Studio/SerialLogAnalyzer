# SerialLogAnalyzer

PC 端**通用串口日志分析工具**：从任意串口设备实时接收并结构化解析日志，并可把日志上下文
提交给 LLM 获得诊断建议。解析规则由 YAML Preset 声明式定义，不绑定具体芯片或固件，
仓库自带 Hi3861 的示例 Preset 与配套固件。

## 功能

- 串口连接设备，实时接收日志（`QSerialPort`，单 Qt 事件循环）
- YAML Preset 声明式解析：级别 / 模块 / 消息字段提取，多行日志合并，未识别行安全回退
- 日志表格：级别 / 模块 / 文本过滤、暂停滚动、清空、手动导入导出
- LLM 分析：同一输入框首轮 + 多轮追问，SSE 流式输出
- Provider 配置驱动：OpenAI 兼容、OpenAI Responses、Anthropic、Google Gemini（YAML 声明）
- 凭据管理：按 Profile 声明的 `kind` 从系统 Keychain / 环境变量取值，支持运行时临时输入
- 配置与资源：用户配置目录覆盖内置 YAML Preset / Adapter / Profile 与 Prompt 模板
- 日志留档：导出为文本 / CSV / JSONL，也可导入历史日志回看
- 诊断报告：一条命令列出资源来源、已加载配置、配置错误与日志末尾（`python -m serial_log_analyzer.diagnostics`）
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
3. 选中若干行日志，在右侧分析面板选择上下文范围与目标，在下方输入框写要求（可留空），
   Enter 或「发送」提交首轮分析。
4. 结果流式显示；在同一输入框继续输入即为追问（Enter 发送、Shift+Enter 换行）。
   上下文与目标只在首轮生效，要重开点「新会话」。
5. 需要留档时用菜单「文件 → 导出日志…」（按后缀选文本 / CSV / JSONL），「导入日志…」可回看历史文件，
   「清空日志」清空当前表格；波特率在工具栏下拉里直接改，数据位 / 校验位 / 停止位 / 流控在
   工具栏「串口参数…」，仅本次会话有效。
6. 分析面板顶部切换 LLM Profile（立即生效并记入设置）；「配置 → 切换日志 Preset…」换日志格式，
   切换会清空当前日志；过滤栏的「自动滚动」控制新日志是否自动滚到底部。

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

- [`DESIGN.md`](DESIGN.md)：完整架构设计（分层、接口、数据流）
- [`docs/llm-integration.md`](docs/llm-integration.md)：LLM 管道现状、SenseNova / 书生 配置与调用接口
- [`docs/configuration.md`](docs/configuration.md)：配置文件设计（资源查找顺序、设置键、API Key 来源、导出格式、诊断信息）
- [`DEVELOPMENT.md`](DEVELOPMENT.md)：开发环境、运行与调试、协作约定
- [`AGENTS.md`](AGENTS.md)：面向 AI 助手与协作者的编码约定
- [`docs/protocols/board-protocol.md`](docs/protocols/board-protocol.md)：板上日志格式与命令通道
- [`docs/protocols/log-preset.md`](docs/protocols/log-preset.md)：日志 Preset schema
- [`docs/protocols/provider.md`](docs/protocols/provider.md)：LLM Provider schema
- [`docs/protocols/json-pointer.md`](docs/protocols/json-pointer.md)：扩展 JSON Pointer 规范
- [`docs/protocols/credentials.md`](docs/protocols/credentials.md)：凭据存储规范

## 本地模型配置

`sensenova` / `internlm` 两个 Profile 的接口地址、模型与超时见
`providers/profiles/*.yaml`。本地密钥放项目根目录 `.env`（变量名见 `.env.example`），
`kind: environment` 的 Profile 会先读进程环境、再回落该文件；`.env` 已被 Git 忽略。
两个 Profile 复用 `openai-compatible` Adapter，其流式声明会发送 `stream_options.include_usage`——
若这两个服务拒收该字段，按 [`docs/llm-integration.md`](docs/llm-integration.md) 的说明调整声明。
完整窗口与启动入口已接通：`python main.py` 或 `bootstrap.main()` 可启动应用。

## 许可

[MIT](LICENSE)
