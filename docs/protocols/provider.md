# LLM Provider 声明规范

Provider 层由两部分 YAML 组成：

- **Adapter**（`providers/adapters/*.yaml`）：描述“如何调用这一类接口”，与具体服务地址无关；
- **Profile**（`providers/profiles/*.yaml`）：描述“调用哪一个服务”，引用 Adapter 并给出
  `base_url`、`model` 与凭据。

声明格式为 YAML，不提供其他格式的兼容层。

## 1. Adapter

```yaml
schema_version: 3
adapter_id: openai-compatible
endpoint: "/chat/completions"
messages_format: openai        # openai | anthropic | gemini

headers:
  Authorization: "Bearer ${api_key}"

body:
  model: "${model}"
  messages: "${messages}"
  temperature: "${temperature}"
  max_tokens: "${max_output_tokens}"
  stream: "${stream}"

response_content_pointer: "/choices/0/message/content"
response_reasoning_content_pointers:
  - "/choices/0/message/reasoning_content"

models:
  endpoint: "/models"
  response_models_pointer: "/data"
  response_model_id: "id"

usage:
  input_tokens_pointer: "/usage/prompt_tokens"
  output_tokens_pointer: "/usage/completion_tokens"
  total_tokens_pointer: "/usage/total_tokens"

streaming:
  transport: sse
  endpoint: "/chat/completions"
  request_body:
    stream_options:
      include_usage: true
  content_events:
    - pointer: "/choices/0/delta/content"
  reasoning_events: []
  terminal:
    sentinel: "[DONE]"
  allow_clean_eof: true
  error_events:
    - when:
        pointer: "/choices/0/finish_reason"
        equals: "error"
      message_pointer: "/error/message"
      status_pointer: "/error/status"
  usage:
    input_tokens_pointers: ["/usage/prompt_tokens"]
    output_tokens_pointers: ["/usage/completion_tokens"]
    total_tokens_pointers: ["/usage/total_tokens"]
```

### 1.1 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 当前固定为 `3` |
| `adapter_id` | 是 | `^[a-z][a-z0-9-]*$`，唯一 |
| `endpoint` | 是 | 相对路径，可含 `${model}`；不得包含 `://` |
| `messages_format` | 否 | `openai`（默认）/ `anthropic` / `gemini` |
| `headers` | 是 | 字符串到字符串；值可含 `${api_key}` 占位符 |
| `body` | 是 | 请求体模板；字符串值若为占位符须独占该值 |
| `response_content_pointer` | 是 | 非流式正文路径（扩展 JSON Pointer） |
| `response_reasoning_content_pointers` | 否 | 思考正文候选路径，按序尝试 |
| `models` | 否 | 模型列表接口声明 |
| `usage` | 否 | 用量字段路径 |
| `streaming` | 否 | 流式声明；缺省表示不支持流式 |

### 1.2 占位符白名单

| 占位符 | 可用于 | 含义 |
|---|---|---|
| `${api_key}` | headers | 已解析的密钥 |
| `${model}` | endpoint / body | 模型名 |
| `${system}` | body | 系统消息文本（多条 system 以空行拼接） |
| `${messages}` | body | 已按 `messages_format` 转换的消息数组 |
| `${temperature}` | body | 采样温度 |
| `${max_output_tokens}` | body | 最大输出 token；值为 `0` 时该字段整体从请求体移除 |
| `${stream}` | body | 是否流式 |

未知占位符、非独占形式的占位符（如 `"prefix-${model}"` 出现在 body 中）均报 `ConfigError`。

### 1.3 流式声明 `streaming`

| 字段 | 必填 | 说明 |
|---|---|---|
| `transport` | 是 | 当前仅支持 `sse` |
| `endpoint` | 是 | 流式端点；可与 `endpoint` 不同 |
| `request_body` | 否 | 流式请求追加字段；与非流式 `body` 冲突时报错 |
| `content_events` | 是 | 正文增量规则数组：`{pointer, when?}` |
| `reasoning_events` | 否 | 思考正文增量规则数组 |
| `terminal` | 是 | 终止条件：`{sentinel: "[DONE]"}` 或 `{when: {pointer, equals\|exists}}` |
| `allow_clean_eof` | 否 | 服务端未发终止事件即关闭连接时是否视为正常结束 |
| `error_events` | 否 | `{when, message_pointer, status_pointer?}` 数组 |
| `usage` | 否 | 流式用量指针数组，支持多候选 |

条件 `when` 的形态：

```yaml
when: {pointer: "/type", equals: "response.completed"}   # 取值相等
when: {pointer: "/candidates/0/finishReason", exists: true}  # 路径存在
```

## 2. Profile

```yaml
schema_version: 1
profile_id: deepseek
adapter_id: openai-compatible
base_url: "https://api.deepseek.com/v1"
model: "deepseek-chat"
stream: true
request_timeout_seconds: 120

credential:
  kind: keyring          # keyring | environment | runtime
  name: deepseek         # keyring 账号名
  env_var: DEEPSEEK_API_KEY  # kind=environment 时使用

extra_body: {}
extra_headers: {}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 当前固定为 `1` |
| `profile_id` | 是 | `^[a-z][a-z0-9-]*$`，唯一 |
| `adapter_id` | 是 | 必须能加载到对应 Adapter |
| `base_url` | 是 | 合法 HTTP(S) URL，无尾部 `/` |
| `model` | 是 | 模型名 |
| `stream` | 否 | 流式开关；Adapter 未声明 `streaming` 且此处为 `true` 时报错 |
| `request_timeout_seconds` | 否 | 默认 120 |
| `credential` | 是 | 凭据引用，见 `credentials.md` |
| `extra_body` | 否 | 追加请求体字段；与 Adapter 模板冲突时报错 |
| `extra_headers` | 否 | 追加请求头；与 Adapter 模板头同名（大小写不敏感）时报错 |

## 3. 内置 Adapter

| adapter_id | 典型服务 | 流式 |
|---|---|---|
| `openai-compatible` | OpenAI、DeepSeek、通义、Ollama、LM Studio | SSE |
| `openai-responses` | OpenAI Responses API | SSE |
| `anthropic` | Claude Messages API | SSE |
| `google-gemini` | Gemini generateContent | SSE |

## 4. 校验与错误

| 情况 | 行为 |
|---|---|
| YAML 非法 / 缺少必填字段 / 字段类型错误 | `ConfigError` |
| 出现未知字段 | `ConfigError`（避免拼写错误静默失效） |
| 未知占位符 | `ConfigError` |
| `stream: true` 但 Adapter 无 `streaming` | `ConfigError` |
| 响应路径不存在或类型不符 | `ResponseParseError` |
| 服务端返回错误事件 | `ProviderError`（携带服务端消息） |
