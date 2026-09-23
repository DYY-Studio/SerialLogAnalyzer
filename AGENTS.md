# AGENTS.md — 协作与编码约定

面向 AI 助手与人类协作者的仓库约定。开始改代码前请先读本文件与 `DESIGN.md`。

## 项目概览

SerialLogAnalyzer 是 PC 端串口日志分析工具：连接 Hi3861 开发板，实时接收并解析日志，
支持 YAML Preset 声明式解析与 LLM 辅助分析。同仓包含 Hi3861 侧日志发送固件（`fw/`）。

## 常用命令

```bash
uv venv --python 3.12          # 首次创建虚拟环境
uv sync --extra dev            # 安装运行 + 开发依赖
uv run python main.py          # 启动应用（源码直跑）
uv run pytest                  # 全部测试
uv run pytest tests/unit       # 仅单元测试
uv run ruff check .            # 静态检查
uv run ruff check --fix .      # 自动修复
```

- 优先使用仓库内 `.venv`，不要用系统 Python 安装依赖。
- 提交前必须保证 `ruff check .` 与 `pytest` 通过。

## 目录速览

```text
main.py                  源码直跑入口
src/serial_log_analyzer/ 应用包
  core/                  纯 Python 业务与模型（禁止 Qt）
  io/                    Qt / 系统适配实现
  ui/                    PySide6 界面
  bootstrap.py           唯一依赖组装点
presets/ providers/ prompts/  声明式资源
fw/                      Hi3861 固件
docs/protocols/          协议规范文档
tests/                   单元 / 集成 / UI 测试
```

## 架构硬约束

1. `core/` 不得 import PySide6，不得直接读写文件、串口、网络、钥匙串。
2. `core/` 需要外部能力时，在 `core/ports.py` 定义 `Protocol`，由 `io/` 实现。
3. `io/` 只做适配与类型转换，不做业务决策；Qt 类型不得外泄到 `core/`/`ui` 之外的层。
4. `ui/` 不解析日志、不发 LLM 请求、不直接操作 `QSerialPort` / `QNetworkAccessManager`。
5. `MainWindow` 只负责布局、菜单、工具栏、状态栏，不保存核心业务状态。
6. 依赖注入全部显式构造函数完成，`bootstrap.py` 是唯一组装点，不引入 DI 框架。
7. 禁止 `eval` / `exec` / 动态脚本 Preset；YAML 只描述规则。
8. 禁止全局 Signal / Event Bus、无理由线程、静默吞异常。

> 例外说明：`bootstrap.py` 位于包根而非 `ui/`，因为它同时组装 `core`、`io`、`ui`，
> 属于刻意保留的例外。`diagnostics/app_logging.py` 允许使用标准库 `logging` 写文件日志。

## 代码风格

- 遵循 `ruff` 配置（行宽 100，规则集 E/F/W/I/UP/B/SIM/C4）。
- 公共接口必须有中文 Docstring，说明职责、参数与异常；私有实现按需注释。
- 数据结构优先 `dataclass`，跨层契约优先 `Protocol`。
- 错误统一继承 `core/errors.py` 中的异常体系，不要抛裸 `Exception`。
- 用户可见文案使用中文；代码标识符、日志键名使用英文。

## 测试约定

- 先明确测试是否必要；不要写基于文本正则探测的无意义测试。
- `tests/unit/` 不得启动 Qt；需要 Qt 的放 `tests/integration/` 或 `tests/ui/`，使用 `pytest-qt`。
- 允许临时测试用于验证，但通过后应移除，不保留一次性脚本。

## 分支与协作

本仓库采用 GitHub Flow。以下为**内部维护约定**，描述本团队如何提交与合入改动：

- `main` 始终可运行、可演示；不直接向 `main` 推送，改动用短分支 + PR 合入。
- 分支命名：`feature/<主题>`、`fix/<主题>`、`docs/<主题>`，主题用简短英文短语，例如
  `feature/log-preset-loader`。
- PR 不强制评审，但必须通过 `ruff check .` 与 `pytest`，并在描述中说明“做了什么 + 为什么”。
- 合并方式统一使用 squash merge，保持 `main` 历史线性；PR 标题即最终提交信息。
- 合并后删除源分支；不保留长期存活的开发分支（不设 `develop`）。

## 提交约定

- 每个提交聚焦单一主题，提交信息说明“做了什么 + 为什么”。
- 不要把 `exports/`、`.venv/`、本地配置或任何密钥提交进仓库。
- 修改资源 schema（`presets/`、`providers/`、`prompts/`）时同步更新 `docs/protocols/`。
- 改动较多时拆成多个提交，但每个提交都应能独立通过 `ruff check .` 与 `pytest`。
- 若由 AI 助手生成提交，须在提交信息末尾（空行之后）附加 `Co-authored-by:` trailer，
  身份由该助手按其自身配置填写，本仓库不固定具体值。不得修改或省略已有 trailer。

