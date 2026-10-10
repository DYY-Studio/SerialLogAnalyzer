"""``core/services/credential_resolver.py`` 的来源优先级测试。"""

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


def test_runtime_input_wins_over_other_sources():
    keyring = FakeKeyring({"demo": "from-keyring"})
    resolver = _resolver(keyring, FakeEnvironment({"DEMO_KEY": "from-env"}))
    resolver.set_runtime_secret("demo", "from-runtime")

    credential = CredentialRef(kind=CredentialKind.KEYRING, name="demo", env_var="DEMO_KEY")

    assert resolver.resolve(credential) == "from-runtime"
    assert keyring.reads == []


def test_keyring_is_preferred_for_keyring_kind():
    keyring = FakeKeyring({"demo": "from-keyring"})
    resolver = _resolver(keyring, FakeEnvironment({"DEMO_KEY": "from-env"}))

    credential = CredentialRef(kind=CredentialKind.KEYRING, name="demo", env_var="DEMO_KEY")

    assert resolver.resolve(credential) == "from-keyring"


def test_environment_is_fallback_when_keyring_misses():
    resolver = _resolver(FakeKeyring(), FakeEnvironment({"DEMO_KEY": "from-env"}))

    credential = CredentialRef(kind=CredentialKind.KEYRING, name="demo", env_var="DEMO_KEY")

    assert resolver.resolve(credential) == "from-env"


def test_environment_kind_prefers_environment_variable():
    resolver = _resolver(
        FakeKeyring({"demo": "from-keyring"}), FakeEnvironment({"DEMO_KEY": "from-env"})
    )

    credential = CredentialRef(kind=CredentialKind.ENVIRONMENT, name="demo", env_var="DEMO_KEY")

    assert resolver.resolve(credential) == "from-env"
    assert resolver.describe_sources(credential).startswith("本次会话输入（demo）")


def test_runtime_kind_still_falls_back_to_keyring():
    resolver = _resolver(FakeKeyring({"demo": "from-keyring"}), FakeEnvironment())

    credential = CredentialRef(kind=CredentialKind.RUNTIME, name="demo")

    assert resolver.resolve(credential) == "from-keyring"


def test_keyring_unavailable_is_reported_but_environment_still_used():
    keyring = FakeKeyring({"demo": "from-keyring"}, available=False)
    resolver = _resolver(keyring, FakeEnvironment({"DEMO_KEY": "from-env"}))

    credential = CredentialRef(kind=CredentialKind.KEYRING, name="demo", env_var="DEMO_KEY")

    assert resolver.keyring_available() is False
    assert resolver.resolve(credential) == "from-env"
    assert "不可用" in resolver.describe_sources(credential)
    assert keyring.reads == []


def test_keyring_failure_does_not_block_environment():
    keyring = FakeKeyring(error=CredentialError("钥匙串锁住"))
    resolver = _resolver(keyring, FakeEnvironment({"DEMO_KEY": "from-env"}))

    credential = CredentialRef(kind=CredentialKind.KEYRING, name="demo", env_var="DEMO_KEY")

    assert resolver.resolve(credential) == "from-env"


def test_all_sources_missed_raises_with_attempts():
    resolver = _resolver(FakeKeyring(), FakeEnvironment())

    credential = CredentialRef(kind=CredentialKind.KEYRING, name="demo", env_var="DEMO_KEY")

    with pytest.raises(CredentialError) as excinfo:
        resolver.resolve(credential)

    message = str(excinfo.value)
    assert "本次会话输入（demo）" in message
    assert "系统钥匙串（demo）" in message
    assert "环境变量 DEMO_KEY" in message
    assert "未命中" in message


def test_credential_without_any_identifier_raises():
    resolver = _resolver(FakeKeyring(), FakeEnvironment())

    with pytest.raises(CredentialError) as excinfo:
        resolver.resolve(CredentialRef(kind=CredentialKind.RUNTIME))

    assert "未配置任何来源" in str(excinfo.value)


def test_runtime_secret_uses_environment_variable_name_too():
    resolver = _resolver(FakeKeyring(), FakeEnvironment())
    resolver.set_runtime_secret("DEMO_KEY", "from-runtime")

    credential = CredentialRef(kind=CredentialKind.KEYRING, name="demo", env_var="DEMO_KEY")

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

    assert resolver.resolve(CredentialRef(kind=CredentialKind.KEYRING, name="demo")) == "secret"


def test_environment_blank_value_is_treated_as_miss():
    resolver = _resolver(FakeKeyring(), FakeEnvironment({"DEMO_KEY": "   "}))

    credential = CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="DEMO_KEY")

    with pytest.raises(CredentialError):
        resolver.resolve(credential)


def test_keyring_probe_failure_counts_as_unavailable():
    resolver = _resolver(FakeKeyring(available=RuntimeError("没有后端")), FakeEnvironment())

    assert resolver.keyring_available() is False


def test_describe_sources_lists_full_chain():
    resolver = _resolver(FakeKeyring(), FakeEnvironment())

    credential = CredentialRef(kind=CredentialKind.KEYRING, name="demo", env_var="DEMO_KEY")

    assert resolver.describe_sources(credential) == (
        "本次会话输入（demo） → 本次会话输入（DEMO_KEY） → 系统钥匙串（demo） → 环境变量 DEMO_KEY"
    )
