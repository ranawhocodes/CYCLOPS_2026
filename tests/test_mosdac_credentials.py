"""
The MOSDAC credential boundary.

These run offline. The point is not to test MOSDAC — it is to guarantee that a
password can never leak from this codebase: no prompting, no disk writes, no
echoing into an exception, and no accidental commit.
"""
import os

import pytest

from cyclops.data import mosdac as M


@pytest.fixture(autouse=True)
def _no_creds(monkeypatch):
    monkeypatch.delenv("MOSDAC_USERNAME", raising=False)
    monkeypatch.delenv("MOSDAC_PASSWORD", raising=False)


def test_download_refuses_without_credentials_and_says_how_to_fix():
    """Must raise before any network call, with actionable instructions."""
    assert M.has_credentials() is False
    with pytest.raises(M.MosdacAuthError) as e:
        M.credentials()
    msg = str(e.value)
    assert M.SIGNUP_URL in msg
    assert "MOSDAC_USERNAME" in msg and "MOSDAC_PASSWORD" in msg


def test_partial_credentials_are_rejected(monkeypatch):
    """A username with no password must not be treated as usable."""
    monkeypatch.setenv("MOSDAC_USERNAME", "someone")
    assert M.has_credentials() is False
    monkeypatch.delenv("MOSDAC_USERNAME")
    monkeypatch.setenv("MOSDAC_PASSWORD", "secret")
    assert M.has_credentials() is False


def test_credentials_come_only_from_the_environment(monkeypatch):
    monkeypatch.setenv("MOSDAC_USERNAME", "u@example.com")
    monkeypatch.setenv("MOSDAC_PASSWORD", "p")
    assert M.credentials() == ("u@example.com", "p")


def test_no_credential_is_ever_written_to_disk(monkeypatch, tmp_path):
    """
    Guards the design choice behind reading from the environment: MOSDAC's own
    client stores the password in a config.json, and this module deliberately
    does not. If a future change introduces a config file, this fails.
    """
    import inspect
    src = inspect.getsource(M)
    for bad in ("config.json", "write_text(", "json.dump("):
        assert bad not in src, f"mosdac.py must not persist anything ({bad!r})"


def test_auth_error_never_echoes_the_password_value(monkeypatch):
    """
    A rejected login must not put the password VALUE into the exception.

    Behavioural, not a source grep: an earlier version of this test looked for
    the word "password" in the except block and failed on the help text, which
    names the environment variable and is exactly what should be there.
    """
    import urllib.error
    import urllib.request

    secret = "hunter2-do-not-leak"
    monkeypatch.setenv("MOSDAC_USERNAME", "someone@example.com")
    monkeypatch.setenv("MOSDAC_PASSWORD", secret)

    def boom(*a, **k):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(M.MosdacAuthError) as e:
        M.get_token()
    assert secret not in str(e.value)
    # and not anywhere in the chained context either
    assert e.value.__cause__ is None, "must suppress the original error's context"


def test_secrets_are_gitignored():
    """A .env committed by accident would defeat all of the above."""
    from pathlib import Path
    gi = Path(__file__).resolve().parents[1] / ".gitignore"
    text = gi.read_text()
    assert ".env" in text, ".env must be gitignored"
