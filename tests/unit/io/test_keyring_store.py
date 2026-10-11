"""``io/credentials/keyring_store.py`` 的钥匙串适配测试（使用假后端，不访问系统钥匙串）。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import CredentialError
from serial_log_analyzer.io.credentials.keyring_store import (
    SERVICE_NAME,
    KeyringStoreAdapter,
)


class FakeBackend:
    """内存后端，行为与 keyring 模块的最小一致。"""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.calls: list[str] = []

    def get_password(self, service_name: str, username: str) -> str | None:
        self.calls.append("get")
        return self.store.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.calls.append("set")
        self.store[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.calls.append("delete")
        self.store.pop((service_name, username), None)


class ExplodingBackend(FakeBackend):
    """所有操作都失败的后端，用于验证异常翻译。"""

    def get_password(self, service_name: str, username: str) -> str | None:
        raise RuntimeError("keyring locked")

    def set_password(self, service_name: str, username: str, password: str) -> None:
        raise RuntimeError("keyring locked")

    def delete_password(self, service_name: str, username: str) -> None:
        raise RuntimeError("keyring locked")


def test_save_read_delete_round_trip():
    backend = FakeBackend()
    store = KeyringStoreAdapter(backend=backend)

    assert store.available is True
    assert store.read("deepseek") is None

    store.save("deepseek", "sk-test")
    assert store.read("deepseek") == "sk-test"
    assert backend.store[(SERVICE_NAME, "deepseek")] == "sk-test"

    assert store.delete("deepseek") is True
    assert store.read("deepseek") is None


def test_delete_missing_returns_false_without_calling_backend():
    backend = FakeBackend()
    store = KeyringStoreAdapter(backend=backend)

    assert store.delete("absent") is False
    assert "delete" not in backend.calls


def test_custom_service_name_is_used():
    backend = FakeBackend()
    store = KeyringStoreAdapter("OtherService", backend=backend)

    store.save("openai", "sk-1")

    assert ("OtherService", "openai") in backend.store


@pytest.mark.parametrize("identifier", ["", "   "])
def test_blank_identifier_is_rejected(identifier):
    store = KeyringStoreAdapter(backend=FakeBackend())

    with pytest.raises(CredentialError):
        store.read(identifier)


def test_blank_secret_is_rejected():
    store = KeyringStoreAdapter(backend=FakeBackend())

    with pytest.raises(CredentialError):
        store.save("deepseek", "")


def test_backend_failures_become_credential_error():
    store = KeyringStoreAdapter(backend=ExplodingBackend())

    with pytest.raises(CredentialError):
        store.read("deepseek")
    with pytest.raises(CredentialError):
        store.save("deepseek", "sk-1")
    with pytest.raises(CredentialError):
        store.delete("deepseek")


def test_identifier_is_trimmed_before_use():
    backend = FakeBackend()
    store = KeyringStoreAdapter(backend=backend)

    store.save("  deepseek  ", "sk-test")

    assert backend.store == {(SERVICE_NAME, "deepseek"): "sk-test"}
    assert store.read("deepseek") == "sk-test"


def test_describe_mentions_service_and_state():
    store = KeyringStoreAdapter(backend=FakeBackend())

    text = store.describe()

    assert SERVICE_NAME in text
    assert "可用" in text
