import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    port: int = 8420
    caddy_main_config: Path = field(
        default_factory=lambda: Path("/etc/caddy/Caddyfile")
    )
    caddy_conf_d: Path = field(default_factory=lambda: Path("/etc/caddy/conf.d"))
    manifest_dir: Path = field(default_factory=lambda: Path("/opt/frontdoor/manifests"))
    secret_key: str = field(
        default_factory=lambda: (
            os.environ.get("FRONTDOOR_SECRET_KEY") or secrets.token_hex(32)
        )
    )
    secure_cookies: bool = field(
        default_factory=lambda: (
            os.environ.get("FRONTDOOR_SECURE_COOKIES", "false").lower() == "true"
        )
    )
    session_timeout: int = 2592000
    cookie_domain: str = field(
        default_factory=lambda: os.environ.get("FRONTDOOR_COOKIE_DOMAIN", "")
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get("FRONTDOOR_LOG_LEVEL", "info")
    )
    tokens_file: Path = field(
        default_factory=lambda: Path(
            os.environ.get("FRONTDOOR_TOKENS_FILE", "/opt/frontdoor/tokens.json")
        )
    )
    allow_localhost_admin: bool = field(
        default_factory=lambda: (
            os.environ.get("FRONTDOOR_ALLOW_LOCALHOST_ADMIN", "true").lower() == "true"
        )
    )
    self_unit: str = field(
        default_factory=lambda: os.environ.get("FRONTDOOR_SELF_UNIT", "frontdoor.service")
    )
    service_user: str = field(
        default_factory=lambda: os.environ.get("FRONTDOOR_SERVICE_USER", "")
    )


settings = Settings()
