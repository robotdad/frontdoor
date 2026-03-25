from pathlib import Path


def test_defaults(monkeypatch):
    """Verify all default values including secret_key length>=32."""
    # Ensure env vars are not set so we get true defaults
    monkeypatch.delenv("FRONTDOOR_SECRET_KEY", raising=False)
    monkeypatch.delenv("FRONTDOOR_SECURE_COOKIES", raising=False)

    from frontdoor.config import Settings

    s = Settings()

    assert s.port == 8420
    assert s.caddy_main_config == Path("/etc/caddy/Caddyfile")
    assert s.caddy_conf_d == Path("/etc/caddy/conf.d")
    assert s.manifest_dir == Path("/opt/frontdoor/manifests")
    assert isinstance(s.secret_key, str)
    assert len(s.secret_key) >= 32
    assert s.secure_cookies is False


def test_secret_key_from_env(monkeypatch):
    """Verify FRONTDOOR_SECRET_KEY env override."""
    monkeypatch.setenv("FRONTDOOR_SECRET_KEY", "my-custom-secret-key-for-testing-1234")

    from frontdoor.config import Settings

    s = Settings()
    assert s.secret_key == "my-custom-secret-key-for-testing-1234"


def test_secure_cookies_from_env(monkeypatch):
    """Verify FRONTDOOR_SECURE_COOKIES='true' override."""
    monkeypatch.setenv("FRONTDOOR_SECURE_COOKIES", "true")

    from frontdoor.config import Settings

    s = Settings()
    assert s.secure_cookies is True


def test_session_timeout_default():
    """Verify session_timeout default is 2592000 (30 days in seconds)."""
    from frontdoor.config import Settings

    s = Settings()
    assert s.session_timeout == 2592000


def test_cookie_domain_default(monkeypatch):
    """Verify cookie_domain defaults to empty string when env var not set."""
    monkeypatch.delenv("FRONTDOOR_COOKIE_DOMAIN", raising=False)

    from frontdoor.config import Settings

    s = Settings()
    assert s.cookie_domain == ""


def test_cookie_domain_from_env(monkeypatch):
    """Verify FRONTDOOR_COOKIE_DOMAIN env var is respected."""
    monkeypatch.setenv("FRONTDOOR_COOKIE_DOMAIN", ".example.com")

    from frontdoor.config import Settings

    s = Settings()
    assert s.cookie_domain == ".example.com"
