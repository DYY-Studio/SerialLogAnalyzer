"""``io/environment.py`` 的进程环境与本地 ``.env`` 读取测试。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import ConfigError, CredentialError
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver
from serial_log_analyzer.io.environment import DotEnvEnvironmentReader, ProcessEnvironment


class _UnavailableKeyring:
    """占位钥匙串：``available=False``，``kind: environment`` 不会访问它。"""

    available = False


def _resolver(reader: object) -> CredentialResolver:
    return CredentialResolver(_UnavailableKeyring(), reader)  # type: ignore[arg-type]


def test_process_environment_treats_blank_as_missing(monkeypatch):
    monkeypatch.setenv("SLA_TEST_KEY", "value")
    monkeypatch.setenv("SLA_TEST_BLANK", "   ")
    environment = ProcessEnvironment()

    assert environment.get("SLA_TEST_KEY") == "value"
    assert environment.get("SLA_TEST_BLANK") is None
    assert environment.get("SLA_TEST_MISSING") is None


def test_dotenv_priority_and_literal_values(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "\ufeff# test\nTEST_KEY=\"fake-file-key\" # note\nexport OTHER='literal-${TEST_KEY}#abc'\n"
        "PLAIN=abc#def\nBLANK=\n",
        encoding="utf-8",
    )
    environment = {"TEST_KEY": "fake-process-key"}
    reader = DotEnvEnvironmentReader(path, environ=environment)

    assert reader.get("TEST_KEY") == "fake-process-key"
    assert reader.get("OTHER") == "literal-${TEST_KEY}#abc"
    assert reader.get("PLAIN") == "abc#def"
    assert reader.get("BLANK") == ""
    assert reader.get("MISSING") is None
    assert environment == {"TEST_KEY": "fake-process-key"}


def test_missing_file_can_use_process_environment(tmp_path):
    reader = DotEnvEnvironmentReader(tmp_path / "missing", environ={"TEST_KEY": "fake-env"})

    resolved = _resolver(reader).resolve(
        CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="TEST_KEY")
    )

    assert resolved == "fake-env"


def test_blank_process_value_disables_file_fallback(tmp_path):
    path = tmp_path / ".env"
    path.write_text("TEST_KEY=fake-file", encoding="utf-8")
    reader = DotEnvEnvironmentReader(path, environ={"TEST_KEY": ""})

    with pytest.raises(CredentialError):
        _resolver(reader).resolve(
            CredentialRef(kind=CredentialKind.ENVIRONMENT, env_var="TEST_KEY")
        )


@pytest.mark.parametrize(
    "bad",
    [
        "TEST_KEY=fake-secret\nTEST_KEY=other",
        "invalid assignment",
        'TEST_KEY="fake-secret',
        'TEST_KEY="fake-secret" extra',
        "123=fake-secret",
    ],
)
def test_bad_dotenv_never_echoes_content(tmp_path, bad):
    path = tmp_path / ".env"
    path.write_text(bad, encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        DotEnvEnvironmentReader(path, environ={})

    assert "fake-secret" not in str(excinfo.value)
