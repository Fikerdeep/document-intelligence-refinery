"""The .env loader: fills the environment, never overrides it, never crashes."""

import os

from refinery.env import load_env


def test_loads_values_and_strips_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('ANTHROPIC_API_KEY="sk-test-123"\n# comment\n\nOTHER=plain\n')
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    assert load_env(env) == 2
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test-123"
    assert os.environ["OTHER"] == "plain"


def test_existing_environment_wins(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    load_env(env)
    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"


def test_missing_file_is_a_quiet_noop(tmp_path):
    assert load_env(tmp_path / "absent.env") == 0
