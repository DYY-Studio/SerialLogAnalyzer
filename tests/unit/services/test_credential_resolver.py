"""``core/services/credential_resolver.py`` 的来源解析测试。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import CredentialError
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver


class FakeKeyring:
    """最小钥匙串替身：字典命中即返回，可注入失败与不可用状态。"""

    def __init__(
        self,
        values: dict[str, str] | None = None,
        *,
        available: bool | Exception = True,
        error: Exception | None = None,
    ) -> None:
        self.values = dict(values or {})
        self._available = available
        self._error = error
        self.reads: list[str] = []

    @property
    def available(self) -> bool:
        if isinstance(self._available, Exception):
            raise self._available
        return self._available

    def read(self, credential_id: str) -> str | None:
        self.reads.append(credential_id)
        if self._error is not None:
            raise self._error
        return self.values.get(credential_id)

    def save(self, credential_id: str, secret: str) -> None:  # pragma: no cover - 协议占位
        self.values[credential_id] = secret

    def delete(self, credential_id: str) -> bool:  # pragma: no cover - 协议占位
        return self.values.pop(credential_id, None) is not None


class FakeEnvironment:
    """环境变量替身。"""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)


def _resolver(keyring: FakeKeyring, environment: FakeEnvironment) -> CredentialResolver:
    return CredentialResolver(keyring, environment)


def _keyring_ref(name: str = "demo") -> CredentialRef:
    return CredentialRef(kind=CredentialKind.KEYRING, name=name)


def test_runtime_input_wins_over_declared_source():
    keyring = FakeKeyring({"demo": "from-keyring"})
    resolver = _resolver(keyring, FakeEnvironment())
    resolver.set_runtime_secret("demo", "from-runtime")

    assert resolver.resolve(_keyring_ref()) == "from-runtime"
    assert keyring.reads == []


def test_keyring_kind_reads_keyring():
    keyring = FakeKeyring({"demo": "from-keyring"})
    resolver = _resolver(keyring, FakeEnvironment())

    assert resolver.resolve(_keyring_ref()) == "from-keyring"
    assert keyring.reads == ["demo"]


def test_environment_kind_reads_environment_variable_only():
    keyring = FakeKeyring({"demo": "from-keyring"})
    resolver = _resolver(keyring, FakeEnvironment({"DEMO_KEY": "from-env"}))
    credential = CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="DEMO_KEY")

    assert resolver.resolve(credential) == "from-env"
    assert keyring.reads == []


def test_keyring_miss_does_not_fall_back_to_environment():
    resolver = _resolver(FakeKeyring(), FakeEnvironment({"DEMO_KEY": "from-env"}))

    with pytest.raises(CredentialError) as excinfo:
        resolver.resolve(_keyring_ref())

    message = str(excinfo.value)
    assert "本次会话输入（demo，未命中）" in message
    assert "系统钥匙串（demo）（未命中）" in message
    assert "环境变量 DEMO_KEY" not in message
    assert "credential.kind 改为 environment" in message


def test_runtime_kind_without_input_raises():
    resolver = _resolver(FakeKeyring({"demo": "from-keyring"}), FakeEnvironment())

    with pytest.raises(CredentialError) as excinfo:
        resolver.resolve(CredentialRef(kind=CredentialKind.RUNTIME, name="demo"))

    message = str(excinfo.value)
    assert "本次会话输入（demo，未命中）" in message
    assert "请在界面输入本次会话密钥" in message


def test_keyring_unavailable_is_reported_without_fallback():
    keyring = FakeKeyring({"demo": "from-keyring"}, available=False)
    resolver = _resolver(keyring, FakeEnvironment({"DEMO_KEY": "from-env"}))

    assert resolver.keyring_available() is False
    assert resolver.describe_sources(_keyring_ref()) == (
        "本次会话输入（demo） → 系统钥匙串（demo，不可用）"
    )

    with pytest.raises(CredentialError) as excinfo:
        resolver.resolve(_keyring_ref())

    assert "系统钥匙串（demo，不可用）" in str(excinfo.value)
    assert keyring.reads == []


def test_keyring_read_failure_is_reported_without_fallback():
    keyring = FakeKeyring(error=CredentialError("钥匙串锁住"))
    resolver = _resolver(keyring, FakeEnvironment({"DEMO_KEY": "from-env"}))

    with pytest.raises(CredentialError) as excinfo:
        resolver.resolve(_keyring_ref())

    message = str(excinfo.value)
    assert "钥匙串锁住" in message
    assert "环境变量 DEMO_KEY" not in message


def test_credential_without_any_identifier_raises():
    resolver = _resolver(FakeKeyring(), FakeEnvironment())

    with pytest.raises(CredentialError) as excinfo:
        resolver.resolve(CredentialRef(kind=CredentialKind.RUNTIME))

    message = str(excinfo.value)
    assert "未配置任何来源" in message
    assert resolver.describe_sources(CredentialRef(kind=CredentialKind.RUNTIME)) == (
        "未配置任何来源"
    )


def test_runtime_secret_uses_environment_variable_name_for_environment_kind():
    resolver = _resolver(FakeKeyring(), FakeEnvironment({"DEMO_KEY": "from-env"}))
    resolver.set_runtime_secret("DEMO_KEY", "from-runtime")

    credential = CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="DEMO_KEY")

    assert resolver.resolve(credential) == "from-runtime"


def test_runtime_secret_can_be_cleared_and_blank_ids_are_ignored():
    resolver = _resolver(FakeKeyring(), FakeEnvironment())
    resolver.set_runtime_secret("demo", "secret")
    assert resolver.has_runtime_secret("demo") is True

    resolver.set_runtime_secret("demo", "   ")
    assert resolver.has_runtime_secret("demo") is False

    resolver.set_runtime_secret("", "secret")
    assert resolver.has_runtime_secret("") is False


def test_values_are_stripped_before_returned():
    resolver = _resolver(FakeKeyring({"demo": "  secret  "}), FakeEnvironment())

    assert resolver.resolve(_keyring_ref()) == "secret"


def test_environment_blank_value_is_treated_as_miss():
    resolver = _resolver(FakeKeyring(), FakeEnvironment({"DEMO_KEY": "   "}))
    credential = CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="DEMO_KEY")

    with pytest.raises(CredentialError):
        resolver.resolve(credential)


def test_keyring_probe_failure_counts_as_unavailable():
    resolver = _resolver(FakeKeyring(available=RuntimeError("没有后端")), FakeEnvironment())

    assert resolver.keyring_available() is False


def test_describe_sources_lists_declared_source_only():
    resolver = _resolver(FakeKeyring(), FakeEnvironment())
    environment_credential = CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="DEMO_KEY")
    runtime_credential = CredentialRef(kind=CredentialKind.RUNTIME, name="ollama-local")

    assert resolver.describe_sources(_keyring_ref()) == (
        "本次会话输入（demo） → 系统钥匙串（demo）"
    )
    assert resolver.describe_sources(environment_credential) == (
        "本次会话输入（DEMO_KEY） → 环境变量 DEMO_KEY"
    )
    assert resolver.describe_sources(runtime_credential) == "本次会话输入（ollama-local）"
