# 凭据存储规范

API Key 等敏感信息**不得提交到 Git**，不得写入共享配置或日志。允许按用户要求保存到
被 Git 忽略的本地 `.env`。本规范定义凭据来源、优先级与界面行为。

## 1. 三种来源

| kind | 形态 | 说明 |
|---|---|---|
| `keyring` | `{kind: keyring, name: <account>}` | 系统钥匙串（推荐） |
| `environment` | `{kind: environment, env_var: <VAR>}` | 环境变量（CI / headless 场景） |
| `runtime` | `{kind: runtime}` | 每次运行时由用户输入，仅存内存 |

补充约定：

- `kind` 可省略，缺省为 `runtime`；取值不区分大小写（内部统一按小写解析）；
- 只有 `kind: environment` 必须提供 `env_var`；`kind: keyring` 未给 `name` 时以 `profile_id` 作为账号名；
- 配置文件解析失败或 `kind` 非法时报 `ConfigError`（不会静默降级为运行时输入）。

Profile 中同时可以给出 `name` 与 `env_var` 作为双来源声明：

```yaml
credential:
  kind: keyring
  name: deepseek
  env_var: DEEPSEEK_API_KEY
```

此时 `kind` 表示**首选来源**，另一项作为回退。

## 2. 解析优先级

```text
1. 运行时输入（本次会话内存中的值，固定最优先）
2. kind 声明的首选来源
3. 另一来源（回退）
```

`kind` 只决定**首选来源**：`kind: keyring` 时先查钥匙串、再查环境变量；
`kind: environment` 时先查环境变量、再查钥匙串。运行时输入永远排在最前，与 `kind` 无关。

运行时输入按 `name` 与 `env_var` 两个候选键匹配，任一命中即生效。

任一来源取到非空字符串（去除首尾空白后非空）即停止；所有来源均失败时抛出
`CredentialError`，错误消息中列出已尝试的来源，便于用户排查。

## 3. 系统钥匙串约定

| 项 | 值 |
|---|---|
| keyring service | `SerialLogAnalyzer` |
| keyring account | credential `name`（缺省取 `profile_id`）；界面读写同样必须使用该账号名 |
| 依赖库 | `keyring>=25,<26` |

平台后端：macOS 使用 Keychain；Windows 使用 Credential Locker；Linux 使用
SecretService（GNOME Keyring / KWallet）。

## 4. 界面行为

- Keyring 可用时：凭据对话框提供“保存到系统钥匙串”勾选项；
- 用户输入密钥后默认**仅本次会话有效**，不自动落盘；勾选保存时才写入钥匙串；
- Keyring 不可用（如 headless Linux）时：勾选项置灰，提示将回退到环境变量或运行时输入；
- 密钥输入框使用密码遮蔽，且不回显已保存的密钥内容（只显示“已保存”状态）。

## 5. 禁止事项

- 禁止把密钥写入 `providers/profiles/*.yaml`、`QSettings`、日志或异常消息；
- 禁止在代码中硬编码密钥；
- 禁止在错误信息中泄露密钥内容（只允许出现来源名称，如 `DEEPSEEK_API_KEY`）。

## 6. 测试约定

- 单元测试使用 Fake `KeyringStore` 与 Fake `EnvironmentReader`，不触碰真实钥匙串；
- 集成测试如需验证真实后端，只能使用临时 account，并在测试结束时删除。


## 7. 本地 .env

项目根目录 `.env` 存放本机 API 密钥，`.env.example` 仅保留空变量名供复制。
`.env` 和 `.env.*` 被 Git 忽略，只有 `.env.example` 可提交。
SenseNova 使用 `SENSENOVA_API_KEY`，书生使用 `INTERNLM_API_KEY`。

`DotEnvEnvironmentReader` 实现 EnvironmentReader：同名进程环境变量优先，缺失时读 `.env`。
进程环境显式设置为空值时不回退文件，该密钥视为缺失。文件只读取指定路径，不向上搜索，
不修改 os.environ，不执行命令，不展开变量。支持 UTF-8 BOM、注释、export 前缀及单/双引号。
重复变量、非法赋值或不可读文件抛出 ConfigError，消息不包含文件行内容或密钥。
读取器构造时载入文件，修改 `.env` 后需重新构造客户端。

`build_llm_client(profile_id, manager, project_root=...)` 在组合根中连接资源、环境读取器、
CredentialResolver 与网络传输。此入口只组装运行时/环境凭据，不启用系统钥匙串。
CredentialResolver 支持注入钥匙串接口用于完整应用集成，并保持运行时 → 钥匙串 → 环境优先级。
运行时输入的 credential_id 取 credential.name、否则 env_var、否则固定 `runtime`。
