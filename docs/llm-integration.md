# LLM 模块接入与交接

本模块负责消息格式、请求构建、HTTP 通信、JSON/SSE 响应解析和日志分析提示词。
不负责采集、关键词筛选、上下文选择、会话历史保存或 UI。

## 指定服务

| Profile | 基地址 | 默认模型 | 凭据环境变量 |
|---|---|---|---|
| `sensenova` | `https://token.sensenova.cn/v1` | `sensenova-6.7-flash-lite` | `SENSENOVA_API_KEY` |
| `internlm` | `https://chat.intern-ai.org.cn/api/v1` | `intern-latest` | `INTERNLM_API_KEY` |

配置依据为 2026-10-10 查阅的官方文档：
[SenseNova](https://github.com/OpenSenseNova/SenseNova6.7/blob/main/API_CN.md)、
[书生 Chat Completions](https://internlm.intern-ai.org.cn/doc/docs/Chat/)。
这些是文档示例，不表示账户已获得模型权限或已完成在线验证。书生别名可能随平台更新。
SenseNova 此配置适用于 token 服务，不能直接用于另一套旧版 JWT API。

两个 Profile 复用 `openai-compatible`（该 Adapter 的流式声明统一带 `stream_options.include_usage`），
并以 `[DONE]` 作为终止事件。**已知风险**：SenseNova / 书生 若拒收 `stream_options`，流式请求会失败；
届时可移除共享 Adapter 中的该项（代价：OpenAI / DeepSeek 流式不再返回 usage），或为这两个服务
重新分出独立声明。

密钥由凭据服务解析，Profile 只存变量名。项目根目录的 `.env` 已按用户要求填入本地密钥，
该文件被 Git 忽略，不在文档或输出中复述。其他成员可复制 `.env.example` 并自行填写。
进程环境变量优先于 `.env`；修改文件后需重新构造客户端。不要提交或共享 `.env`。

## 给集成方的调用接口

依赖由 `bootstrap.py` 显式组装。需要提供：

- 实现 `ResourceLoader` 的资源读取器；用户资源优先级由读取器负责。
- 实现 `CredentialProvider.resolve(CredentialRef) -> str` 的凭据服务。
- 唯一的 `QNetworkAccessManager`、运行中的 Qt 事件循环。
- 已准备好的 `AnalysisMessage` 列表和 `AnalysisRequest`，以及结果/错误回调。

组装过程示例（放入组合根，不在 UI 中构造或调用底层网络对象）：

```python
from serial_log_analyzer.core.llm.adapter_loader import load_adapter
from serial_log_analyzer.core.llm.profile_loader import load_profile
from serial_log_analyzer.core.llm.request import RequestBuilder
from serial_log_analyzer.core.llm.sse import SSEParser
from serial_log_analyzer.core.llm.stream import StreamProcessor
from serial_log_analyzer.core.models.analysis import (
    AnalysisMessage, AnalysisRequest, MessageRole,
)
from serial_log_analyzer.core.prompts.loader import PromptLibrary
from serial_log_analyzer.io.llm.qt_http_transport import QtHttpTransport

# resources、credentials、network_manager 由组合根注入。
profile = load_profile(resources, "sensenova")  # 或 internlm
adapter = load_adapter(resources, profile.adapter_id)
prompt = PromptLibrary(resources).render(
    "aggregate-anomalies", context="[E] [memory] malloc failed"
)
request = RequestBuilder(adapter, profile, credentials).build(
    [AnalysisMessage(MessageRole.USER, prompt)], AnalysisRequest(max_output_tokens=2048)
)

parser = SSEParser()
processor = StreamProcessor(adapter, on_delta, on_usage=handle_usage)

def on_chunk(data: bytes) -> None:
    for event in parser.feed(data):      # 处理跨网络分块的半行
        processor.handle(event)          # 正文/reasoning 增量 + 终止与用量

token = QtHttpTransport(network_manager).send(request, on_chunk, on_done, on_error)
# 需要取消时：token.cancel()。结束后或重复取消为空操作。
```

- 流式：`SSEParser` 维护缓冲，`StreamProcessor` 产出正文增量、可选 reasoning 增量与用量，
  并在终止事件或 `finalize(clean_eof=...)` 后置位 `finished`；
- 非流式：调用方需要自行累积 `on_chunk` 分块，再用 `adapter.parse_response` /
  `adapter.extract_usage` 解析。**这类编排（含响应体上限、终态回调只触发一次）原由已删除的
  `LLMClient` 承担，将随 §12 的 `AnalysisService` 一起落地**；本模块目前只提供零件。
- `on_error` 收到 `AppError`；不把 reasoning 加回会话历史。
- 多轮分析需由 `AnalysisService` 按顺序提供 system/user/assistant 历史，本模块不保存历史。

Adapter / Profile / Prompt 加载、`RequestBuilder`、`SSEParser`、`StreamProcessor`、
`QtHttpTransport`、`AnalysisService` 与桌面窗口均已实现；`python main.py` 可直接启动。
测试使用假密钥或本地 Qt TCP 服务；未进行真实 API 请求。

## 多轮上下文、缓存与思考回传

本节记录 2026-10-12 核对官方文档后的口径，`AnalysisService` 的所有请求都按它组装。

### 缓存命中字段（各家响应）

| Provider | 命中字段 | 与输入总量的关系 |
|---|---|---|
| DeepSeek | `usage.prompt_cache_hit_tokens`（等于 `usage.prompt_tokens_details.cached_tokens`），另有 `prompt_cache_miss_tokens` | `prompt_tokens = hit + miss`，命中**含在**输入内 |
| OpenAI（Chat Completions） | `usage.prompt_tokens_details.cached_tokens` | 命中**含在** `prompt_tokens` 内 |
| OpenAI（Responses） | `usage.input_tokens_details.cached_tokens`（另有 `cache_write_tokens`） | 命中**含在** `input_tokens` 内 |
| Google Gemini | `usageMetadata.cachedContentTokenCount` | `promptTokenCount` 官方说明「包含缓存内容」 |
| Anthropic | `usage.cache_read_input_tokens`（读命中）+ `usage.cache_creation_input_tokens`（写入） | **例外**：`input_tokens` 官方口径是「未被缓存读/写的输入」，总输入 = `input + read + creation` |

来源：[DeepSeek 上下文缓存](https://api-docs.deepseek.com/guides/kv_cache)、
[DeepSeek API 参考](https://api-docs.deepseek.com/api/create-chat-completion)、
[OpenAI 提示缓存](https://developers.openai.com/api/docs/guides/prompt-caching)、
[Gemini 生成接口](https://ai.google.dev/api/generate-content)、
[Anthropic 提示缓存](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)。

代码里统一归一化为「**`input_tokens` = 全部输入（含缓存读/写），`cached_tokens` = 其中命中缓存的部分**」，
映射写在 Adapter 声明里（`providers/adapters/*.yaml` 的 `usage` 段，见 `docs/protocols/provider.md`），
界面用量行显示为 `输入 4096（缓存 1800） / 输出 503 / 总计 4599 tokens`。服务端没给 total 时按输入 + 输出补齐。

### 缓存命中与「多轮不重复发送」

- DeepSeek 的磁盘缓存按**前缀单元完全匹配**命中，多轮对话的第二轮能命中第一轮的前缀；命中情况就是上面那两个 usage 字段。
- 因此**截断历史头部会让前缀失配**：`llm/history_rounds`（0 = 全部携带）只保留首轮 + 最近 N 轮，
  省下的只是问答对本身的 token，代价是缓存前缀之外的部分每轮都重新计费。默认 0，界面与转录始终完整。
- 请求只追加、不修改历史消息，天然有利于前缀命中；切换 Profile / 预设 / 新会话会改变前缀，属预期。

### 思考（reasoning）为什么不回传

- DeepSeek：**不带 `tools` 时** `reasoning_content` 不需要回传，传了也会被忽略、不拼进上下文
  （带 `tools` 才必须回传）。本项目不使用工具调用，因此回传无收益。
- Anthropic：thinking 块带 `signature`，回传要求**原样**带回；它影响的是工具调用连续性与缓存前缀完整性。
  我们解析响应时会跳过 thought 块（`response_text_blocks_pointer`），也没有工具调用。
- 结论：请求只发 `role` + `content`（`AnalysisMessage.summary` 仅用于界面）；界面上的思考来自卡片本身，
  历史轮次的思考仍然可见，但不进入后续请求。

## 错误与生命周期


- 请求前的配置/凭据错误同步抛出；网络与响应解析错误通过 `on_error` 返回。
- HTTP 非 2xx、连接失败、超时、取消各有错误路径，终态回调只触发一次。
- 超时是从发送开始的总时限，不随网络分块重置。
- 不自动重试，避免重复分析及重复计费；不自动跟随重定向。
- 远端错误正文不直接回显，避免错误体包含认证信息；HTTP 错误保留状态码。
- SSE 终止事件中的正文和 usage 先处理再结束；不允许正常 EOF 的配置在缺少终止事件时失败。
- Anthropic usage 分散在多个事件时合并最新累计计数，不重复累加；缺少 total 时用 input + output。
  缓存字段由 Adapter 声明归一化（见「多轮上下文、缓存与思考回传」）。
- `on_usage` 回调携带归一化后的 `TokenUsage`（含 `cached_tokens`），只在数值变化时触发一次。

## 提示词与结果验收

预设包括 `locate-error`、`explain-logs`、`suggest-fix`、`aggregate-anomalies`。
聚合报告要求提供异常摘要、分组证据、可能根因、验证建议和信息缺口。
分类覆盖内存分配失败、任务/调度超时、驱动/外设错误、通信异常及未知类别。
日志作为数据处理；没有异常、不含时间戳或无法判断独立事件时明确说明。
语义聚合属于模型推断，不代表已实现全量日志的自动筛选/告警调度。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/llm tests/integration/test_qt_http_transport.py
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest
```

离线测试覆盖请求构建、消息转换、配置拒绝、中文任意分块、流式 usage/终止、
本地真实 Qt HTTP 成功/错误/超时/取消、断连及多请求隔离。
单元测试不启动 Qt；网络集成测试不访问外网、不启动后台线程。
真实 API 冒烟、两个服务的语义效果对比以及完整 UI 联调待完成。

人工语义评估可使用 `tests/fixtures/llm/openharmony-cases.json`，其中均为合成样例，
用于覆盖正常、内存、调度、驱动、重复及混合异常，不冒充实机采集记录。
每条带有 review 检查点；两个服务应使用同一输入比较证据与分类，不用固定措辞评分。


## 本地 `.env`

`.env` 由 `io/environment.py` 的 `DotEnvEnvironmentReader` 读取（进程环境优先，缺失时回落文件），
组合根在建 `CredentialResolver` 时注入该读取器。`kind: environment` 的 Profile 因此既能用进程
环境变量、也能用仓库根目录的 `.env`；`.env` 被 Git 忽略，`.env.example` 是模板。
