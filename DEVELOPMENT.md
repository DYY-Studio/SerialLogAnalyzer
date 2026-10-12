# DEVELOPMENT.md — 开发指南

## 环境要求

- Python 3.11 – 3.14（开发与 CI 建议 pin **3.12**，见 `.python-version`）
- [uv](https://docs.astral.sh/uv/)（推荐）；也可使用标准 `venv` + `pip`
- 平台：macOS / Linux / Windows（串口与 Keychain 依赖系统后端）

> 注意：`.python-version` 固定为 3.12。PySide6 的 wheel 覆盖到 3.13/3.14 时也无需修改
> `requires-python`，但换版本前请先本地验证 `uv sync` 可解。

## 初始化

```bash
uv venv --python 3.12
uv sync --extra dev
```

等价的手工方式：

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 运行

```bash
uv run python main.py          # 源码直跑（推荐日常开发）
uv run serial-log-analyzer     # 安装后的 console script
uv run python -m serial_log_analyzer   # 模块入口
```

应用日志（工具自身日志）默认输出到 stderr，可通过环境变量覆盖：

```bash
SLA_LOG_LEVEL=DEBUG uv run python main.py
SLA_LOG_FILE=./app.log uv run python main.py     # 追加启用文件日志（1 MB × 3 轮转）
```

**设备日志**（来自所连串口设备）与**应用日志**（工具自身）严格分离：前者进入日志表格与
`LogPipeline`，后者使用标准库 `logging`（见 `diagnostics/app_logging.py`），二者不混用。

配置自查（资源从哪里加载、有没有写错的 YAML）：

```bash
uv run python -m serial_log_analyzer.diagnostics            # 中文诊断报告
uv run python -m serial_log_analyzer.diagnostics --json     # JSON 输出
uv run python -m serial_log_analyzer.diagnostics --export report.txt
```

报告包含资源根目录（按优先级）、已加载的 Preset / Adapter / Profile、系统钥匙串可用性、
应用日志末尾与逐条配置错误；退出码 `1` 表示存在配置错误，可直接作为 CI 的资源校验步骤。

## 测试

```bash
uv run pytest                      # 全部
uv run pytest tests/unit           # 单元（不得启动 Qt）
uv run pytest tests/integration    # 集成（pytest-qt，需最小 Qt 环境）
uv run pytest tests/ui             # 少量界面行为
```

约定：

- 单元测试不导入 PySide6；需要 Qt 的测试放 `integration/` 或 `ui/`。
- 写测试前自问其必要性，避免针对代码文本的正则探测式测试。
- 临时验证脚本通过后删除，不保留。

## 静态检查

```bash
uv run ruff check .
uv run ruff check --fix .
```

提交前必须无告警。

## 目录与依赖规则

```text
ui/  ──依赖──▶  core/  ◀──实现──  io/
                     ▲
                bootstrap.py（唯一组装点）
```

1. `core/` 纯 Python：不 import PySide6，不直接访问文件 / 串口 / 网络 / 钥匙串。
2. 外部能力通过 `core/ports.py` 的 `Protocol` 声明，由 `io/` 实现，`bootstrap.py` 注入。
3. `io/` 只做适配与类型转换，不做业务决策；Qt 类型不向上外泄。
4. `ui/` 不解析日志、不发 LLM 请求、不直接操作 `QSerialPort` / `QNetworkAccessManager`。
5. `MainWindow` 只做布局与转发，不持有核心业务状态。
6. 显式构造函数注入，不引入 DI 框架。

迁移提示：未来若改为 Vue + FastAPI，`core/` 可原样复用，仅需替换 `io/` 与 `ui/`。
因此任何把业务逻辑写进 `ui/` 或 `io/` 的改动都应被拒绝。

## 线程模型

v1 只使用 Qt 主事件循环：

```text
Qt Main Thread
├── Widgets / Qt Models / Controllers
├── QSerialPort（readyRead 异步）
├── QNetworkAccessManager（readyRead / finished 异步）
└── core 纯逻辑（解析、JSON Pointer、SSE 帧解析）
```

禁止无理由创建线程。若出现明确 CPU 密集瓶颈，先讨论再引入 `QThreadPool`。

## 配置与资源

| 资源 | 位置 | 格式 |
|---|---|---|
| 日志解析 Preset | `presets/logs/*.yaml` | YAML |
| LLM Adapter | `providers/adapters/*.yaml` | YAML |
| LLM Profile | `providers/profiles/*.yaml` | YAML |
| Prompt 模板 | `prompts/*.md` | Markdown + `string.Template` |
| 界面偏好 | `QSettings` | 系统注册表 / plist / ini |
| API Key | 由 Profile 的 `credential.kind` 决定（Keychain / 环境变量 / 运行时输入） | 见 `docs/protocols/credentials.md` |

资源查找顺序：用户配置目录 → 仓库/内置资源。同 ID 时用户资源覆盖内置资源。

- 用户配置目录：Windows `%APPDATA%\SerialLogAnalyzer`，其他平台 `~/.config/SerialLogAnalyzer`，
  可用 `SLA_CONFIG_HOME` 重定向（便携模式、测试隔离都用它）。
- 「模型服务」对话框的「保存到用户配置」把 Profile 写入
  `<用户配置目录>/providers/profiles/<profile_id>.yaml`（临时文件 + 原子替换，内置文件永不改写）。
- 日志导出默认目录：`SLA_EXPORT_DIR` → 源码运行时 `<仓库根>/exports`（已被 `.gitignore` 忽略）→
  安装后 `~/SerialLogAnalyzer/exports`；界面设置 `logs/export_dir` 可覆盖。
- 应用日志文件（启用时）为 `<用户配置目录>/logs/serial-log-analyzer.log`。
- 字段含义、设置键表、API Key 优先级与导出格式见 [`docs/configuration.md`](docs/configuration.md)。

## 调试串口

- 无真实硬件时可用虚拟串口对（macOS：`socat -d -d pty,raw,echo=0 pty,raw,echo=0`；
  Linux：`socat` 同理）。
- 可编写回放脚本把日志文件按行 + 延迟写入虚拟串口，模拟板子输出。
- 板子固件构建方式见 `fw/README.md`。

## 硬件联调

接入真实 Hi3861 后，可运行门控集成测试验证串口链路与命令通道：

```bash
SLA_HW_PORT=COM3 uv run pytest tests/integration/test_hardware_link.py -v
```

未设置 `SLA_HW_PORT` 时该测试自动跳过，CI 无需硬件。Windows PowerShell 下设置：
`$env:SLA_HW_PORT="COM3"; uv run pytest tests/integration/test_hardware_link.py -v`。


## 常见问题

| 现象 | 排查 |
|---|---|
| 串口列表为空 | 确认驱动与线缆；macOS 检查 `/dev/cu.*` 权限 |
| 日志粘行 | 确认 Preset 正则与板上换行符（应为 `\r\n`） |
| Keychain 不可用 | Linux 无 SecretService 时 `kind: keyring` 的 Profile 取不到密钥；界面提示改用 `environment`，不跨来源回落 |
| 流式无输出 | 检查 profile `stream` 与 adapter `streaming` 声明是否匹配 |
| 发 LLM 请求时进程直接退出（0xC0000005） | 进程里同时存在两套 OpenSSL：`keyring`（经 `jaraco.context`）会导入 Python 的 `ssl`，而 Qt 的 OpenSSL 插件默认绑定系统 `System32\libssl-3-x64.dll`，混用即在 HTTPS 里崩。启动时已固定用系统 TLS（`bootstrap._use_system_tls_backend`）；若仍复现，检查 Qt 的 `tls` 插件是否完整 |
| 自建 Preset / Profile 没生效 | 运行 `python -m serial_log_analyzer.diagnostics`，对照报告里的资源根目录与配置错误 |
| 结果区首次渲染「中文代码注释」时卡几秒 | 等宽字体缺中文字形会走系统回退，Windows 上实测每进程一次要 2.5–4 s。结果区把含中文的代码片段换成本机探测到的「等宽且含中文」字体（`ui/markdown.py`）；本机若没有这类字体只能由平台处理，属已知现象 |
| 导出的日志找不到 | 看设置里的 `logs/export_dir`，留空则用 `SLA_EXPORT_DIR` / `<仓库根>/exports` |

## 分支与提交约定

本仓库采用 **GitHub Flow**。以下为内部维护约定：`main` 始终可运行，改动用短分支 + PR 合入，
合并方式为 **no-ff merge**（见 `AGENTS.md`）。

```bash
git switch -c feature/log-preset-loader    # 从最新 main 开分支
# ...开发、提交...
git push -u origin feature/log-preset-loader
gh pr create --fill                        # 创建 PR
```

- 分支命名：`feature/<主题>` / `fix/<主题>` / `docs/<主题>`。
- PR 不强制评审，但必须通过 `ruff check .` 与 `pytest`。
- 单一主题、可回退；提交信息说明动机与影响，PR 标题即最终提交信息。
- 不提交 `.venv/`、`exports/`、密钥或本地绝对路径。
- 修改资源 schema 时同步更新 `docs/protocols/` 与 `DESIGN.md`。
- AI 助手生成的提交需按 `AGENTS.md` 附加 `Co-authored-by:` trailer。

完整协作规则见 [`AGENTS.md`](AGENTS.md)。
