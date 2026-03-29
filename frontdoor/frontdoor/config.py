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


settings = Settings()
