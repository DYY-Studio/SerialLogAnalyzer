"""``core/llm/profile_loader.py`` 的 Profile 声明校验测试。"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.profile_loader import load_profile, load_profiles
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef

_ADAPTER_DIR = "providers/adapters"
_PROFILE_DIR = "providers/profiles"

_STREAMING_ADAPTER = {
    "schema_version": 3,
    "adapter_id": "streaming-adapter",
    "endpoint": "/v1/chat/completions",
    "response_content_pointer": "/choices/0/message/content",
    "streaming": {
        "transport": "sse",
        "endpoint": "/v1/chat/completions",
        "content_events": [{"pointer": "/choices/0/delta/content"}],
        "terminal": {"sentinel": "[DONE]"},
    },
}
_PLAIN_ADAPTER = {
    "schema_version": 3,
    "adapter_id": "plain-adapter",
    "endpoint": "/v1/chat/completions",
    "response_content_pointer": "/choices/0/message/content",
}


def _yaml(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _base(profile_id: str = "demo") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "adapter_id": "streaming-adapter",
        "base_url": "https://api.example.com/v1",
        "model": "demo-model",
    }


def _loader(make_loader, data: dict[str, Any], profile_id: str = "demo"):
    return make_loader(
        {
            f"{_ADAPTER_DIR}/streaming-adapter.yaml": _yaml(_STREAMING_ADAPTER),
            f"{_ADAPTER_DIR}/plain-adapter.yaml": _yaml(_PLAIN_ADAPTER),
            f"{_PROFILE_DIR}/{profile_id}.yaml": _yaml(data),
        }
    )


def test_minimal_profile_uses_documented_defaults(make_loader):
    profile = load_profile(_loader(make_loader, _base()), "demo")

    assert profile.profile_id == "demo"
    assert profile.adapter_id == "streaming-adapter"
    assert profile.base_url == "https://api.example.com/v1"
    assert profile.model == "demo-model"
    assert profile.stream is True
    assert profile.request_timeout_seconds == 120.0
    assert profile.extra_body == {}
    assert profile.extra_headers == {}
    assert profile.credential == CredentialRef(kind=CredentialKind.KEYRING, name="demo")


def test_profile_with_all_fields_is_parsed(make_loader):
    data = _base()
    data.update(
        {
            "stream": False,
            "request_timeout_seconds": 300,
            "credential": {
                "kind": "keyring",
                "name": "demo-account",
            },
            "extra_body": {"temperature": 0.2},
            "extra_headers": {"X-Trace": "1"},
        }
    )

    profile = load_profile(_loader(make_loader, data), "demo")

    assert profile.stream is False
    assert profile.request_timeout_seconds == 300.0
    assert profile.credential == CredentialRef(kind=CredentialKind.KEYRING, name="demo-account")
    assert profile.extra_body == {"temperature": 0.2}
    assert profile.extra_headers == {"X-Trace": "1"}


def test_missing_credential_section_defaults_to_keyring(make_loader):
    data = _base()
    data["credential"] = None

    profile = load_profile(_loader(make_loader, data), "demo")

    assert profile.credential == CredentialRef(kind=CredentialKind.KEYRING, name="demo")


def test_keyring_without_name_uses_profile_id(make_loader):
    data = _base()
    data["credential"] = {"kind": "keyring"}

    profile = load_profile(_loader(make_loader, data), "demo")

    assert profile.credential == CredentialRef(kind=CredentialKind.KEYRING, name="demo")


def test_environment_credential_requires_env_var(make_loader):
    data = _base()
    data["credential"] = {"kind": "environment", "env_var": "DEMO_KEY"}

    profile = load_profile(_loader(make_loader, data), "demo")

    assert profile.credential == CredentialRef(
        kind=CredentialKind.ENVIRONMENT, env_var="DEMO_KEY"
    )


@pytest.mark.parametrize(
    "credential",
    [
        {"kind": "environment"},
        {"kind": "vault"},
        {"kind": 1},
        {"kind": "keyring", "extra": "x"},
        {"kind": "keyring", "env_var": "DEMO_API_KEY"},
        {"kind": "environment", "name": "demo-account"},
        {"kind": "environment", "env_var": "DEMO_KEY", "name": "demo-account"},
        {"kind": "runtime"},
        {"kind": "runtime", "name": "demo-account"},
        {"kind": "runtime", "env_var": "DEMO_API_KEY"},
        ["keyring"],
        "keyring",
    ],
)
def test_invalid_credential_sections_are_rejected(make_loader, credential):
    data = _base()
    data["credential"] = credential

    with pytest.raises(ConfigError):
        load_profile(_loader(make_loader, data), "demo")


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": 2},
        {"profile_id": "Other"},
        {"profile_id": "with_underscore"},
        {"adapter_id": "Bad_Adapter"},
        {"base_url": "ftp://api.example.com"},
        {"base_url": "https://api.example.com/v1/"},
        {"base_url": ""},
        {"model": ""},
        {"stream": "yes"},
        {"request_timeout_seconds": 0},
        {"request_timeout_seconds": -1},
        {"request_timeout_seconds": "120"},
        {"request_timeout_seconds": True},
        {"extra_body": ["temperature"]},
        {"extra_body": {1: "x"}},
        {"extra_headers": {"X-Trace": 1}},
        {"unknown_field": 1},
    ],
)
def test_invalid_profile_fields_are_rejected(make_loader, overrides):
    data = _base()
    data.update(overrides)

    with pytest.raises(ConfigError):
        load_profile(_loader(make_loader, data), "demo")


def test_missing_required_field_is_rejected(make_loader):
    data = _base()
    del data["base_url"]

    with pytest.raises(ConfigError):
        load_profile(_loader(make_loader, data), "demo")


def test_stream_true_requires_adapter_streaming_support(make_loader):
    data = _base()
    data["adapter_id"] = "plain-adapter"

    with pytest.raises(ConfigError) as excinfo:
        load_profile(_loader(make_loader, data), "demo")
    assert "流式" in str(excinfo.value)

    data["stream"] = False
    profile = load_profile(_loader(make_loader, data), "demo")
    assert profile.stream is False


def test_unknown_adapter_is_reported(make_loader):
    data = _base()
    data["adapter_id"] = "absent-adapter"

    with pytest.raises(ConfigError) as excinfo:
        load_profile(_loader(make_loader, data), "demo")
    assert "Adapter" in str(excinfo.value)


def test_load_profile_rejects_invalid_and_missing_ids(make_loader):
    loader = _loader(make_loader, _base())

    with pytest.raises(ConfigError):
        load_profile(loader, "Bad_Id")
    with pytest.raises(ConfigError) as excinfo:
        load_profile(loader, "absent")
    assert "absent" in str(excinfo.value)


def test_load_profile_rejects_broken_yaml_and_non_mapping(make_loader):
    adapter = _yaml(_STREAMING_ADAPTER)
    broken = make_loader({f"{_ADAPTER_DIR}/streaming-adapter.yaml": adapter,
                          f"{_PROFILE_DIR}/demo.yaml": "schema_version: [1\n"})
    with pytest.raises(ConfigError):
        load_profile(broken, "demo")

    listed = make_loader({f"{_ADAPTER_DIR}/streaming-adapter.yaml": adapter,
                          f"{_PROFILE_DIR}/demo.yaml": "- a\n"})
    with pytest.raises(ConfigError):
        load_profile(listed, "demo")


def test_load_profiles_sorts_by_profile_id(make_loader):
    loader = make_loader(
        {
            f"{_ADAPTER_DIR}/streaming-adapter.yaml": _yaml(_STREAMING_ADAPTER),
            f"{_PROFILE_DIR}/zeta.yaml": _yaml(_base("zeta")),
            f"{_PROFILE_DIR}/alpha.yaml": _yaml(_base("alpha")),
            f"{_PROFILE_DIR}/notes.txt": "忽略",
        }
    )

    profiles = load_profiles(loader)

    assert [item.profile_id for item in profiles] == ["alpha", "zeta"]
