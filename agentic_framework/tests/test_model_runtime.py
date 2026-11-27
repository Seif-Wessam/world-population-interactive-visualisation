import subprocess
import sys
from unittest.mock import Mock

import pytest

from agentic_framework import model_runtime


def test_import_without_credentials():
    """Importing the runtime must not require local configuration."""
    script = """
import os
from unittest.mock import patch

os.environ.pop("HF_TOKEN", None)
os.environ.pop("OPENAI_API_KEY", None)

with patch("dotenv.load_dotenv"), patch("openai.OpenAI") as constructor:
    from agentic_framework import model_runtime

    assert model_runtime.client is None
    constructor.assert_not_called()
    """

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_get_client_requires_token(monkeypatch):
    """A real client cannot be constructed without our HF credential."""
    monkeypatch.setattr(model_runtime, "client", None)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    constructor = Mock()
    monkeypatch.setattr(model_runtime, "OpenAI", constructor)

    with pytest.raises(
        model_runtime.ModelUnavailableError,
        match="HF_TOKEN",
    ):
        model_runtime.get_client()

    constructor.assert_not_called()
    assert model_runtime.client is None


def test_get_client_constructs_once_and_reuses(monkeypatch):
    """Repeated calls reuse the configured SDK client."""
    monkeypatch.setattr(model_runtime, "client", None)
    monkeypatch.setenv("HF_TOKEN", "fake-test-token")

    fake_client = Mock()
    constructor = Mock(return_value=fake_client)
    monkeypatch.setattr(model_runtime, "OpenAI", constructor)

    assert model_runtime.get_client() is fake_client
    assert model_runtime.get_client() is fake_client

    constructor.assert_called_once_with(
        base_url="https://router.huggingface.co/v1",
        api_key="fake-test-token",
        timeout=60.0,
        max_retries=0,
    )