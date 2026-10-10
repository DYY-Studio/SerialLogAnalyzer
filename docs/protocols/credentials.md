# 凭据存储规范

API Key 等敏感信息**不得**明文写入仓库、配置文件或日志。本规范定义凭据的来源、
优先级与界面行为。

## 1. 三种来源

| kind | 形态 | 说明 |
|---|---|---|
| `keyring` | `{kind: keyring, name: <account>}` | 系统钥匙串（推荐） |
| `environment` | `{kind: environment, env_var: <VAR>}` | 环境变量（CI / headless 场景） |
| `runtime` | `{kind: runtime}` | 每次运行时由用户输入，仅存内存 |

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
1. 运行时输入（本次会话内存中的值）
2. 系统钥匙串
3. 环境变量
```

任一来源取到非空字符串即停止；三个来源均失败时抛出 `CredentialError`，
错误消息中列出已尝试的来源，便于用户排查。

## 3. 系统钥匙串约定

| 项 | 值 |
|---|---|
| keyring service | `SerialLogAnalyzer` |
| keyring account | credential `name`（缺省取 `profile_id`） |
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
