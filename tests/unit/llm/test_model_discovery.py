"""模型发现测试：请求组装与响应解析，不启动 Qt、不访问外部服务。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from serial_log_analyzer.core.errors import ConfigError, ResponseParseError
from serial_log_analyzer.core.llm.adapter_loader import load_adapter
from serial_log_analyzer.core.llm.model_discovery import ModelDiscoveryService, parse_model_list
from serial_log_analyzer.core.llm.profile_loader import load_profile
from serial_log_analyzer.core.llm.request import RequestBuilder
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef, ModelOption

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def resources(make_loader):
    files = {
        p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8-sig")
        for directory in ("providers", "prompts")
        for p in (ROOT / directory).rglob("*")
        if p.is_file()
    }
    return make_loader(files)


class FakeCredentials:
    """固定返回假密钥的凭据提供者。"""

    def resolve(self, credential) -> str:
        return "k-123"


class FakeTransport:
    """记录请求并手动触发回调的传输替身。"""

    def __init__(self, *, fail=None, payload: bytes = b"") -> None:
        self.requests = []
        self.credential = None
        self._fail = fail
        self._payload = payload

    def send(self, request, on_chunk, on_done, on_error):
        self.requests.append(request)
        if self._fail is not None:
            on_error(self._fail)
            return None
        if self._payload:
            on_chunk(self._payload)
        on_done()
        return None


def _profile(resources, profile_id: str = "sensenova"):
    """把 Profile 的凭据换成运行时输入，避免测试依赖环境变量或钥匙串。"""

    profile = load_profile(resources, profile_id)
    return replace(profile, credential=CredentialRef(CredentialKind.RUNTIME, name=profile_id))


def _builder(resources, profile_id: str = "sensenova") -> RequestBuilder:
    profile = _profile(resources, profile_id)
    return RequestBuilder(load_adapter(resources, profile.adapter_id), profile, FakeCredentials())


def test_build_model_list_is_get_without_body_and_content_type(resources) -> None:
    profile = _profile(resources)
    request = _builder(resources).build_model_list()

    assert request.method == "GET"
    assert request.url == f"{profile.base_url}/models"
    assert request.body == {}
    assert request.stream is False
    assert request.headers == {"Authorization": "Bearer k-123"}


def test_build_model_list_requires_models_section(resources) -> None:
    profile = _profile(resources)
    adapter = replace(load_adapter(resources, profile.adapter_id), model_discovery=None)

    with pytest.raises(ConfigError, match="未声明 models 段"):
        RequestBuilder(adapter, profile, FakeCredentials()).build_model_list()


def test_parse_openai_style_list(resources) -> None:
    adapter = load_adapter(resources, "openai-compatible")

    options = parse_model_list(adapter, {"data": [{"id": "a"}, {"id": "b"}]})

    assert options == [ModelOption("a", "a"), ModelOption("b", "b")]


def test_parse_gemini_strips_prefix_and_uses_display(resources) -> None:
    adapter = load_adapter(resources, "google-gemini")

    options = parse_model_list(
        adapter,
        {"models": [{"name": "models/gemini-1.5-pro", "displayName": "Gemini 1.5 Pro"}]},
    )

    assert options == [ModelOption("gemini-1.5-pro", "Gemini 1.5 Pro")]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": "not-a-list"},
        {"data": [1]},
        {"data": [{"name": "x"}]},
        {"data": []},
    ],
)
def test_parse_rejects_malformed_payloads(resources, payload) -> None:
    adapter = load_adapter(resources, "openai-compatible")

    with pytest.raises(ResponseParseError):
        parse_model_list(adapter, payload)


def test_parse_requires_models_section(resources) -> None:
    adapter = replace(load_adapter(resources, "openai-compatible"), model_discovery=None)

    with pytest.raises(ConfigError, match="未声明 models 段"):
        parse_model_list(adapter, {"data": [{"id": "a"}]})


def test_service_fetch_parses_response(resources) -> None:
    transport = FakeTransport(payload=b'{"data": [{"id": "m-1"}]}')
    service = ModelDiscoveryService(transport, FakeCredentials())
    done, errors = [], []

    service.fetch(
        load_adapter(resources, "openai-compatible"), _profile(resources), done.append, errors.append
    )

    assert transport.requests[0].method == "GET"
    assert done == [[ModelOption("m-1", "m-1")]] and errors == []


def test_service_forwards_transport_error(resources) -> None:
    failure = ResponseParseError("上游报错")
    service = ModelDiscoveryService(FakeTransport(fail=failure), FakeCredentials())
    done, errors = [], []

    service.fetch(
        load_adapter(resources, "openai-compatible"), _profile(resources), done.append, errors.append
    )

    assert done == [] and errors == [failure]


def test_service_reports_invalid_json(resources) -> None:
    service = ModelDiscoveryService(FakeTransport(payload=b"not-json"), FakeCredentials())
    done, errors = [], []

    service.fetch(
        load_adapter(resources, "openai-compatible"), _profile(resources), done.append, errors.append
    )

    assert done == [] and isinstance(errors[0], ResponseParseError)
