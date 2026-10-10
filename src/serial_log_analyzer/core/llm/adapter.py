"""LLM Adapter：把 YAML 声明解释为请求模板与响应提取规则。

Adapter 描述“如何调用某一类模型接口”，与具体 ``base_url`` / ``model`` 解耦；
后者由 Provider Profile 提供。

支持：OpenAI 兼容、OpenAI Responses、Anthropic、Google Gemini。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from serial_log_analyzer.core.models.analysis import AnalysisMessage
from serial_log_analyzer.core.models.provider import StreamEvent

__all__ = ["JSONAdapter", "StreamCondition", "StreamRule", "StreamingSpec"]


@dataclass(frozen=True)
class StreamCondition:
    """流式事件的匹配条件。

    参数:
        pointer: 条件取值所在路径。
        equals: 期望相等的值；``None`` 表示仅检查 ``exists``。
        exists: 仅判断路径是否存在。
    """

    pointer: str
    equals: Any = None
    exists: bool = False


@dataclass(frozen=True)
class StreamRule:
    """从流式事件中提取增量文本的规则。

    参数:
        pointer: 增量文本所在路径。
        when: 可选匹配条件；不满足时跳过该规则。
    """

    pointer: str
    when: StreamCondition | None = None


@dataclass(frozen=True)
class StreamingSpec:
    """流式接口声明。

    参数:
        endpoint: 流式端点（可与非流式不同，例如 Gemini 的 ``:streamGenerateContent``）。
        request_body: 流式请求追加字段（与非流式 ``body`` 合并，冲突时报错）。
        content_events: 正文增量规则。
        reasoning_events: 思考正文增量规则；无则为空。
        terminal_sentinel: 终止哨兵（如 ``[DONE]``）；无则用 ``terminal_when``。
        terminal_when: 终止条件。
        error_events: 错误事件规则（条件 + 消息路径 + 可选状态码路径）。
        allow_clean_eof: 服务端未发终止事件即关闭连接时，是否视为正常结束。
        usage_pointers: 流式用量路径三元组（输入 / 输出 / 总计），每项是候选路径元组
            （按序尝试）；未声明时为空元组。
    """

    endpoint: str
    content_events: tuple[StreamRule, ...]
    terminal_sentinel: str | None = None
    terminal_when: StreamCondition | None = None
    reasoning_events: tuple[StreamRule, ...] = ()
    request_body: dict[str, Any] = field(default_factory=dict)
    error_events: tuple[tuple[StreamCondition, str, str | None], ...] = ()
    allow_clean_eof: bool = False
    usage_pointers: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] = ((), (), ())


@dataclass(frozen=True)
class JSONAdapter:
    """一个模型接口的声明式适配器。

    参数:
        adapter_id: 唯一标识。
        endpoint: 非流式端点，可含 ``${model}`` 占位符。
        headers_template: 请求头模板，支持 ``${api_key}`` 等占位符。
        body_template: 请求体模板，字符串值可为 ``${model}`` / ``${messages}`` 等占位符。
        response_content_pointer: 非流式响应正文的扩展 JSON Pointer。
        messages_format: 消息转换格式：``openai`` / ``anthropic`` / ``gemini``。
        reasoning_pointers: 思考正文候选路径（按序尝试）。
        model_discovery: 模型列表接口声明（可选）。
        usage_pointers: 用量统计路径三元组（input / output / total）。
        streaming: 流式声明；``None`` 表示不支持流式。
        schema_version: 声明文件版本，当前为 ``3``。
        source_path: 加载来源路径，用于错误提示。
    """

    adapter_id: str
    endpoint: str
    headers_template: dict[str, str]
    body_template: dict[str, Any]
    response_content_pointer: str
    messages_format: str = "openai"
    reasoning_pointers: tuple[str, ...] = ()
    model_discovery: dict[str, Any] | None = None
    usage_pointers: tuple[str | None, str | None, str | None] = (None, None, None)
    streaming: StreamingSpec | None = None
    schema_version: int = 3
    source_path: str = ""

    @property
    def streaming_supported(self) -> bool:
        """该 Adapter 是否声明了流式能力。"""

        return self.streaming is not None

    def build_request(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[AnalysisMessage],
        temperature: float,
        max_output_tokens: int,
        stream: bool,
        extra_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """渲染请求头与请求体。

        参数:
            api_key: 已解析的密钥。
            model: 模型名。
            messages: 对话消息（含 system）。
            temperature: 采样温度。
            max_output_tokens: 最大输出 token 数；``0`` 时该字段从请求体移除。
            stream: 是否流式；为 ``True`` 时合并 ``streaming.request_body``。
            extra_body: Profile 追加字段；与模板字段冲突时报错。
            extra_headers: Profile 追加请求头；与模板头冲突时报错。

        返回:
            ``(headers, body)`` 二元组。

        异常:
            ConfigError: 占位符未知、字段冲突或未声明流式却请求流式。
        """

        raise NotImplementedError

    def parse_response(self, payload: Any) -> tuple[str, str | None]:
        """从非流式响应中提取正文与思考正文。

        返回:
            ``(content, reasoning)``；``reasoning`` 缺失时为 ``None``。

        异常:
            ResponseParseError: 路径缺失或类型不是字符串。
        """

        raise NotImplementedError

    def extract_usage(self, payload: Any) -> tuple[int, int, int] | None:
        """提取用量三元组；未声明或路径缺失时返回 ``None``。"""

        raise NotImplementedError

    def stream_content_deltas(self, event: StreamEvent) -> list[str]:
        """从流式事件中提取正文增量。

        异常:
            ProviderError: 未声明流式规则。
        """

        raise NotImplementedError

    def stream_reasoning_deltas(self, event: StreamEvent) -> list[str]:
        """从流式事件中提取思考正文增量。"""

        raise NotImplementedError

    def is_terminal(self, event: StreamEvent) -> bool:
        """判断事件是否表示流结束（哨兵或终止条件）。"""

        raise NotImplementedError

    def stream_error(self, event: StreamEvent) -> str | None:
        """若事件表示服务端错误，返回用户可读错误信息。"""

        raise NotImplementedError
