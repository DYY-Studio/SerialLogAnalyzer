"""凭据优先级单元测试，不读取真实文件或钥匙串。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import CredentialError
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver


class Environment:
    def __init__(self, values):
        self.values = values

    def get(self, name):
        return self.values.get(name)


class Keyring:
    available = True

    def read(self, name):
        return "fake-keyring-secret"


def test_runtime_keyring_environment_priority():
    credential = CredentialRef(CredentialKind.KEYRING, name="account", env_var="TEST_KEY")
    resolver = CredentialResolver(Keyring(), Environment({"TEST_KEY": "fake-env-secret"}))
    resolver.set_runtime_secret("account", "fake-runtime-secret")
    assert resolver.resolve(credential) == "fake-runtime-secret"
    resolver.set_runtime_secret("account", None)
    assert resolver.resolve(credential) == "fake-keyring-secret"
    resolver = CredentialResolver(None, Environment({"TEST_KEY": "fake-env-secret"}))
    assert resolver.resolve(credential) == "fake-env-secret"


def test_unavailable_keyring_falls_back():
    keyring = Keyring()
    keyring.available = False
    resolver = CredentialResolver(keyring, Environment({"TEST_KEY": "fake-env-secret"}))
    credential = CredentialRef(CredentialKind.KEYRING, name="account", env_var="TEST_KEY")
    assert not resolver.keyring_available()
    assert resolver.resolve(credential) == "fake-env-secret"


def test_runtime_for_environment_and_runtime_profiles():
    resolver = CredentialResolver(None, Environment({}))
    resolver.set_runtime_secret("TEST_KEY", "fake-runtime-secret")
    assert (
        resolver.resolve(CredentialRef(CredentialKind.ENVIRONMENT, env_var="TEST_KEY"))
        == "fake-runtime-secret"
    )
    resolver.set_runtime_secret("runtime", "fake-session-secret")
    assert resolver.resolve(CredentialRef(CredentialKind.RUNTIME)) == "fake-session-secret"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_empty_credential(value):
    resolver = CredentialResolver(None, Environment({"TEST_KEY": value}))
    with pytest.raises(CredentialError, match="TEST_KEY"):
        resolver.resolve(CredentialRef(CredentialKind.ENVIRONMENT, env_var="TEST_KEY"))


def test_errors_do_not_include_secrets():
    resolver = CredentialResolver(None, Environment({}))
    with pytest.raises(CredentialError):
        resolver.set_runtime_secret("name", "  ")
    with pytest.raises(CredentialError):
        resolver.set_runtime_secret("", "fake-secret-not-to-print")
    assert "fake-secret-not-to-print" not in resolver.describe_sources(
        CredentialRef(CredentialKind.RUNTIME)
    )
