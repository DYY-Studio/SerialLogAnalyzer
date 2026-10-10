"""``io/storage/profile_store.py`` 与 ``core/llm/profile_writer.py`` 的保存测试。"""

from __future__ import annotations

import pytest
import yaml

from serial_log_analyzer.core.errors import ConfigError
from serial_log_analyzer.core.llm.profile_writer import dump_profile
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef, ProviderProfile
from serial_log_analyzer.io.storage.profile_store import ProfileStore


def _profile(profile_id: str = "my-local", **overrides) -> ProviderProfile:
    data = {
        "profile_id": profile_id,
        "adapter_id": "openai-compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
        "credential": CredentialRef(kind=CredentialKind.RUNTIME),
        "stream": True,
        "request_timeout_seconds": 300.0,
    }
    data.update(overrides)
    return ProviderProfile(**data)


def test_dump_profile_writes_expected_key_order():
    text = dump_profile(_profile())

    keys = list(yaml.safe_load(text))
    assert keys == [
        "schema_version",
        "profile_id",
        "adapter_id",
        "base_url",
        "model",
        "stream",
        "request_timeout_seconds",
        "credential",
        "extra_body",
        "extra_headers",
    ]
    payload = yaml.safe_load(text)
    assert payload["schema_version"] == 1
    assert payload["credential"] == {"kind": "runtime"}
    assert payload["request_timeout_seconds"] == 300


def test_dump_profile_keeps_keyring_and_environment_fields():
    profile = _profile(
        "deepseek",
        credential=CredentialRef(
            kind=CredentialKind.KEYRING, name="deepseek", env_var="DEEPSEEK_API_KEY"
        ),
    )

    payload = yaml.safe_load(dump_profile(profile))

    assert payload["credential"] == {
        "kind": "keyring",
        "name": "deepseek",
        "env_var": "DEEPSEEK_API_KEY",
    }


def test_dump_profile_rejects_invalid_values():
    with pytest.raises(ConfigError):
        dump_profile(_profile(profile_id="Bad_Id"))
    with pytest.raises(ConfigError):
        dump_profile(_profile(base_url="http://127.0.0.1:11434/v1/"))
    with pytest.raises(ConfigError):
        dump_profile(_profile(model=""))
    with pytest.raises(ConfigError):
        dump_profile(_profile(request_timeout_seconds=0))
    with pytest.raises(ConfigError):
        dump_profile(
            _profile(credential=CredentialRef(kind=CredentialKind.KEYRING, name=""))
        )


def test_save_writes_into_user_directory(tmp_path):
    store = ProfileStore(tmp_path)
    profile = _profile("my-local")

    path = store.save(profile)

    assert path == tmp_path / "providers" / "profiles" / "my-local.yaml"
    assert path.read_text(encoding="utf-8") == dump_profile(profile)
    assert store.exists("my-local")
    assert store.load_text("my-local") == dump_profile(profile)
    assert not list(path.parent.glob("*.tmp"))


def test_save_overwrites_existing_file(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_profile("my-local"))
    store.save(_profile("my-local", model="qwen3:8b"))

    payload = yaml.safe_load(store.load_text("my-local"))
    assert payload["model"] == "qwen3:8b"


def test_load_text_returns_none_for_missing_profile(tmp_path):
    store = ProfileStore(tmp_path)

    assert store.load_text("absent") is None
    assert store.exists("absent") is False


def test_delete_reports_whether_file_existed(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(_profile("my-local"))

    assert store.delete("my-local") is True
    assert store.delete("my-local") is False


def test_path_for_rejects_invalid_identifier(tmp_path):
    store = ProfileStore(tmp_path)

    with pytest.raises(ConfigError):
        store.path_for("Bad Id")


def test_directory_is_under_root(tmp_path):
    store = ProfileStore(tmp_path)

    assert store.root == tmp_path
    assert store.directory() == tmp_path / "providers" / "profiles"
