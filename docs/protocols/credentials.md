# 凭据存储规范

API Key 等敏感信息**不得**明文写入仓库、配置文件或日志。本规范定义凭据的来源、
优先级与界面行为。

## 1. 两种来源

| kind | 形态 | 说明 |
|---|---|---|
| `keyring` | `{kind: keyring, name: <account>}` | 系统钥匙串（推荐） |
| `environment` | `{kind: environment, env_var: <VAR>}` | 环境变量：进程环境优先，缺失时读本地 `.env`（见 §7） |

补充约定：

- `kind` 可省略，缺省为 `keyring`（账号名取 `profile_id`）；取值不区分大小写（内部统一按小写解析）；
- 每个 Profile 只能声明一个来源字段：`kind: keyring` 用 `name`（缺省取 `profile_id`），
  `kind: environment` 必须提供 `env_var`；
- 声明了不属于该 `kind` 的来源字段（如 `kind: keyring` 再写 `env_var`）时报 `ConfigError`；
- 配置文件解析失败或 `kind` 非法时报 `ConfigError`（不会退回到另一个来源）。

## 2. 解析

```text
只读 kind 声明的那个来源（唯一，不回落到另一来源）
```

`kind` 决定密钥存在哪：`keyring` 只读钥匙串、`environment` 只读环境变量。取不到非空字符串
（去除首尾空白后非空）时抛出 `CredentialError`，错误消息中列出已尝试的来源、失败原因，
以及可换用的另一来源，便于用户排查。

## 3. 系统钥匙串约定

| 项 | 值 |
|---|---|
| keyring service | `SerialLogAnalyzer` |
| keyring account | credential `name`（缺省取 `profile_id`）；界面读写同样必须使用该账号名 |
| 依赖库 | `keyring>=25,<26` |

平台后端：macOS 使用 Keychain；Windows 使用 Credential Locker；Linux 使用
SecretService（GNOME Keyring / KWallet）。

## 4. 界面行为

- 凭据区在「模型服务」对话框里（见 `docs/configuration.md` §4.4）：来源与目标标识随 Profile 落盘；
- Keyring 可用时：「保存到钥匙串」把当前输入的密钥写入系统钥匙串（账号名即 `name`）；
- Keyring 不可用（如 headless Linux）时：保存 / 清除置灰，并提示声明了 `kind: keyring` 的 Profile
  取不到密钥，需要改用 `environment` 来源；
- 密钥输入框使用密码遮蔽；界面**不读回**已保存的密钥内容，只用「已保存 / 未设置」表示状态。

## 5. 禁止事项

- 禁止把密钥写入 `providers/profiles/*.yaml`、`QSettings`、日志或异常消息；
- 禁止在代码中硬编码密钥；
- 禁止在错误信息中泄露密钥内容（只允许出现来源名称，如 `DEEPSEEK_API_KEY`）。

## 6. 测试约定

- 单元测试使用 Fake `KeyringStore` 与 Fake `EnvironmentReader`，不触碰真实钥匙串；
- 集成测试如需验证真实后端，只能使用临时 account，并在测试结束时删除。

## 7. 本地 `.env`（`kind: environment` 的文件来源）

仓库根目录的 `.env` 存放本机 API 密钥，`.env.example` 只保留空变量名供复制；`.env` 与
`.env.*` 被 Git 忽略，只有 `.env.example` 可提交。SenseNova 用 `SENSENOVA_API_KEY`，
书生用 `INTERNLM_API_KEY`。

`DotEnvEnvironmentReader`（`io/environment.py`）实现 `EnvironmentReader`：同名进程环境变量
优先，缺失时读取指定的 `.env`；进程环境里显式设置为空值时**不回退**文件，该变量视为缺失，
`kind: environment` 的 Profile 因此解析失败（不跨来源回落）。

文件只读取指定路径，不向上搜索，不修改 `os.environ`，不执行命令，不展开变量；支持 UTF-8 BOM、
注释、`export` 前缀与单/双引号。重复变量、非法赋值或不可读文件抛 `ConfigError`，消息不包含
文件行内容或密钥。读取器在构造时载入文件，修改 `.env` 后需要重新构造。
