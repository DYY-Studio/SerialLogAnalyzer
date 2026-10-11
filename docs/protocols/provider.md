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
  input_cached_tokens_pointers:            # 缓存命中（展示用），按序尝试取第一个命中的
    - "/usage/prompt_tokens_details/cached_tokens"
    - "/usage/prompt_cache_hit_tokens"

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
| `adapter_id` | 是 | `^[a-z][a-z0-9-]*$`，且必须等于文件主名（`demo.yaml` → `demo`） |
| `endpoint` | 是 | 相对路径，可含白名单占位符（如 `${model}`）；不得包含 `://` |
| `messages_format` | 否 | `openai`（默认）/ `anthropic` / `gemini` |
| `headers` | 否 | 字符串到字符串；缺省为空；值可含 `${api_key}` 占位符 |
| `body` | 否 | 请求体模板；缺省为空；字符串值若为占位符须独占该值 |
| `response_content_pointer` | 是 | 非流式正文路径（扩展 JSON Pointer） |
| `response_reasoning_content_pointers` | 否 | 思考正文候选路径，按序尝试 |
| `response_text_blocks_pointer` | 否 | 正文块数组路径；声明时按序拼接其中全部文本块，跳过 thought / refusal（Anthropic、OpenAI Responses 需要） |
| `default_max_output_tokens` | 否 | 非负整数，默认 `0`；请求上限为 `0` 时用它填充 `${max_output_tokens}`，两者都为 `0` 才移除该字段（Anthropic 必填） |
| `models` | 否 | 模型列表接口声明，见 1.2 |
| `usage` | 否 | 用量字段路径，见 1.2 |
| `streaming` | 否 | 流式声明；缺省表示不支持流式 |

### 1.2 `models` 与 `usage` 子字段

`models` 描述“如何列出可用模型”，三个取值的语义层次不同：

| 字段 | 必填 | 说明 |
|---|---|---|
| `endpoint` | 是 | 模型列表端点，相对路径（与 `endpoint` 同样的限制） |
| `response_models_pointer` | 是 | 指向模型数组的**扩展 JSON Pointer** |
| `response_model_id` | 否 | 数组元素内部的相对键名（如 `id`），**不是** Pointer |
| `response_model_display` | 否 | 数组元素内部的展示名键名，**不是** Pointer |
| `response_model_strip_prefix` | 否 | 需要从模型名上剥掉的**字面前缀** |

模型列表请求固定为 `GET <base_url><endpoint>`：复用 Adapter 的请求头（无请求体，因此省略
`Content-Type`）；非 2xx 报 `HttpStatusError`，指针缺失或类型不符报 `ResponseParseError`；
`response_model_strip_prefix` 在解析时剥掉（Gemini 的 `models/` 前缀即此用途）。解析结果供
「模型服务」对话框填充模型下拉（见 `docs/configuration.md` §4.4）。

`usage` 取非流式响应中的用量字段，至少声明一个指针，否则报 `ConfigError`：
| 字段 | 说明 |
|---|---|
| `input_tokens_pointer` | 输入 token 数（扩展 JSON Pointer） |
| `output_tokens_pointer` | 输出 token 数 |
| `total_tokens_pointer` | 总 token 数；未声明时按输入 + 输出补齐 |
| `input_cached_tokens_pointers` | 缓存命中 token 的候选指针，按序尝试取第一个（展示用，不改变输入总量） |
| `input_extra_tokens_pointers` | 这些指针上的值**全部相加**并计入输入总量，用于「`input_tokens` 不含缓存部分」的 Provider |

各家的缓存字段与口径见 `docs/llm-integration.md` §4；Anthropic 的 `input_tokens` 官方口径是
「未被缓存读/写的输入」，所以它用 `input_extra_tokens_pointers` 把 `cache_read` + `cache_creation`
补进输入，另外单独声明 `input_cached_tokens_pointers: cache_read_input_tokens`。

### 1.3 占位符白名单

| 占位符 | 推荐位置 | 含义 |
|---|---|---|
| `${api_key}` | headers | 已解析的密钥 |
| `${model}` | endpoint / body | 模型名 |
| `${system}` | body | 系统消息文本（多条 system 以空行拼接） |
| `${messages}` | body | 已按 `messages_format` 转换的消息数组 |
| `${temperature}` | body | 采样温度 |
| `${max_output_tokens}` | body | 最大输出 token；请求上限为 `0` 时取 Adapter 的 `default_max_output_tokens`，两者都为 `0` 时该字段整体从请求体移除 |
| `${stream}` | body | 是否流式 |

“推荐位置”只是约定，**加载期使用统一白名单**：只要占位符在白名单内，
`headers` / `endpoint` / `body` 均可使用，不按位置拒绝（避免误伤合法组合）。

未知占位符（`headers`、`endpoint`、`streaming.endpoint`、`body` 中任意位置）报 `ConfigError`；
非独占形式的占位符（如 `"prefix-${model}"` 出现在 body 中）同样报 `ConfigError`。

### 1.4 流式声明 `streaming`

| 字段 | 必填 | 说明 |
|---|---|---|
| `transport` | 是 | 当前仅支持 `sse` |
| `endpoint` | 是 | 流式端点；可与 `endpoint` 不同 |
| `request_body` | 否 | 流式请求追加字段；与非流式 `body` 冲突时报错 |
| `content_events` | 是 | 正文增量规则数组：`{pointer, when?, text_blocks?}` |
| `reasoning_events` | 否 | 思考正文增量规则数组；规则字段同 `content_events` |
| `terminal` | 是 | 终止条件：`{sentinel: "[DONE]"}` 或 `{when: {pointer, equals\|exists}}` |
| `allow_clean_eof` | 否 | 服务端未发终止事件即关闭连接时是否视为正常结束 |
| `error_events` | 否 | `{when, message_pointer, status_pointer?}` 数组 |
| `usage` | 否 | 流式用量指针数组：`input_tokens_pointers` / `output_tokens_pointers` / `total_tokens_pointers`（另有与非流式同名的 `input_cached_tokens_pointers` / `input_extra_tokens_pointers`） |

`streaming.usage` 各子键都是**候选指针数组**（同一数值在不同服务端可能出现在不同位置），
至少一个数组非空，否则报 `ConfigError`；候选按序尝试，由 `core/llm/stream.py` 消费并归一化为
`TokenUsage`（`input_extra_tokens_pointers` 里的值全部相加计入输入）。

只对流式请求合法的字段（如 `stream_options`）必须写在 `streaming.request_body`：
Profile 的 `extra_body` 会合并进**每一次**请求，用它承载流式专属字段会让非流式请求也带上该字段。

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
  kind: keyring          # keyring | environment，只读这一个来源
  name: deepseek         # keyring 账号名，缺省取 profile_id

extra_body: {}
extra_headers: {}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 当前固定为 `1` |
| `profile_id` | 是 | `^[a-z][a-z0-9-]*$`，且必须等于文件主名 |
| `adapter_id` | 是 | 必须能加载到对应 Adapter（不存在时报错） |
| `base_url` | 是 | 以 `http://` 或 `https://` 开头，且不以 `/` 结尾 |
| `model` | 是 | 模型名 |
| `stream` | 否 | 流式开关，默认 `true`；Adapter 未声明 `streaming` 且此处为 `true` 时报错 |
| `request_timeout_seconds` | 否 | 正数，默认 `120`；布尔值非法 |
| `credential` | 否 | 凭据引用，见 `credentials.md`；缺省等价于 `{kind: keyring}`（账号名取 `profile_id`） |
| `extra_body` | 否 | 追加请求体字段；与 Adapter 模板字段冲突时报 `ConfigError` |
| `extra_headers` | 否 | 追加请求头；与 Adapter 模板头同名（大小写不敏感）时报 `ConfigError` |

## 3. 内置 Adapter

| adapter_id | 典型服务 | 流式 |
|---|---|---|
| `openai-compatible` | OpenAI、DeepSeek、通义、Ollama、LM Studio | SSE |
| `openai-responses` | OpenAI Responses API | SSE |
| `anthropic` | Claude Messages API | SSE |
| `google-gemini` | Gemini generateContent | SSE |

## 4. 资源查找顺序

Adapter 与 Profile 都通过同一套资源加载器查找，优先级由高到低：

1. 用户配置目录 `providers/adapters/`、`providers/profiles/`
   （Windows `%APPDATA%\SerialLogAnalyzer`，其他平台 `~/.config/SerialLogAnalyzer`，
   可用 `SLA_CONFIG_HOME` 覆盖）；
2. 源码运行时的仓库根 `providers/`；
3. 包内 `serial_log_analyzer/resources/providers/`。

同 `adapter_id` / `profile_id` 时高优先级覆盖低优先级，因此可以在不改仓库的前提下
本地覆盖内置 Adapter。查找顺序的完整说明见 `docs/configuration.md`。

## 5. 校验与错误

| 情况 | 行为 |
|---|---|
| YAML 非法 / 缺少必填字段 / 字段类型错误 | `ConfigError` |
| 出现未知字段 | `ConfigError`（避免拼写错误静默失效） |
| 未知占位符 | `ConfigError` |
| `adapter_id` / `profile_id` 与文件名不一致 | `ConfigError` |
| `stream: true` 但 Adapter 无 `streaming` | `ConfigError` |
| 响应路径不存在或类型不符 | `ResponseParseError` |
| 服务端返回错误事件 | `ProviderError`（不回显远端错误正文，避免回显凭据） |

> 运行期行为由 `core/llm/adapter.py`（渲染与解析）、`core/llm/request.py`（URL 与凭据）
> 与 `core/llm/stream.py`（流式装配）实现；`max_output_tokens` 为 `0` 时该字段从请求体移除。
