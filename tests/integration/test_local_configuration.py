"""本地 .env 与资源加载测试，使用临时目录与假密钥。"""

from __future__ import annotations

import pytest

from serial_log_analyzer.core.errors import ConfigError, CredentialError
from serial_log_analyzer.core.models.provider import CredentialKind, CredentialRef
from serial_log_analyzer.core.services.credential_resolver import CredentialResolver
from serial_log_analyzer.io.credentials.environment_reader import DotEnvEnvironmentReader
from serial_log_analyzer.io.resources import CompositeResourceLoader


def test_dotenv_priority_and_literal_values(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "\ufeff# test\nTEST_KEY=\"fake-file-key\" # note\nexport OTHER='literal-${TEST_KEY}#abc'\nPLAIN=abc#def\nBLANK=\n",
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
    resolver = CredentialResolver(None, reader)
    assert (
        resolver.resolve(CredentialRef(CredentialKind.ENVIRONMENT, env_var="TEST_KEY"))
        == "fake-env"
    )


def test_blank_process_value_disables_file_fallback(tmp_path):
    path = tmp_path / ".env"
    path.write_text("TEST_KEY=fake-file", encoding="utf-8")
    reader = DotEnvEnvironmentReader(path, environ={"TEST_KEY": ""})
    with pytest.raises(CredentialError):
        CredentialResolver(None, reader).resolve(
            CredentialRef(CredentialKind.ENVIRONMENT, env_var="TEST_KEY")
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
    with pytest.raises(ConfigError) as exc:
        DotEnvEnvironmentReader(path, environ={})
    assert "fake-secret" not in str(exc.value)


def test_resource_priority_and_path_boundary(tmp_path):
    high, low = tmp_path / "high", tmp_path / "low"
    for root in (high, low):
        (root / "prompts").mkdir(parents=True)
    (high / "prompts/test.md").write_text("user", encoding="utf-8")
    (low / "prompts/test.md").write_text("builtin", encoding="utf-8")
    (low / "prompts/other.md").write_text("other", encoding="utf-8")
    loader = CompositeResourceLoader([high, low])
    assert loader.read_text("prompts/test.md") == "user"
    assert loader.list_files("prompts", "*.md") == ["prompts/other.md", "prompts/test.md"]
    with pytest.raises(ConfigError):
        loader.read_text("../escape")
    with pytest.raises(ConfigError):
        loader.list_files("prompts", "../*.md")
    with pytest.raises(ConfigError):
        loader.read_text("missing")
