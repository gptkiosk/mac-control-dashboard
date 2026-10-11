"""mac-control API settings.

Loaded from environment variables prefixed MAC_CONTROL_, then from
~/.mac-control/.env. Defaults are safe for this Mac: the server binds to
127.0.0.1 until Google sign-in exists (Phase 4). Set MAC_CONTROL_HOST=0.0.0.0
only after auth is enforced on every route.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from urllib.parse import urlsplit
import ipaddress
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATA_DIR = Path.home() / ".mac-control"
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAC_CONTROL_",
        env_file=str(DEFAULT_DATA_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: str = Field(default="local", description="local | test")
    organization_name: str = Field(default="Mac Control")
    product_name: str = Field(default="Mac Control Dashboard")
    product_short_name: str = Field(default="MCD")
    host: str = Field(
        default="127.0.0.1",
        description="Bind address. Stays 127.0.0.1 until Phase 4 auth is enforced.",
    )
    port: int = Field(default=8800, ge=1, le=65535)
    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    web_dist: Path = Field(
        default=REPO_ROOT / "apps" / "web" / "dist",
        description="Built Vue app. Served at / when present.",
    )
    log_level: str = Field(default="info")

    # --- Phase 2: collector ---------------------------------------------
    collector_enabled: bool = Field(default=True, description="Off in tests.")
    sample_interval_s: int = Field(default=10, ge=2, le=300)
    macmon_path: str = Field(default="/opt/homebrew/bin/macmon")
    tailscale_path: str = Field(default="/usr/local/bin/tailscale")
    disk_path: str = Field(default="/System/Volumes/Data")
    service_prefixes: tuple[str, ...] = Field(
        default=("ai.hermes.", "ai.openclaw.", "com.openclaw.", "com.headroom.", "com.operator."),
        description="launchd labels with these prefixes appear on the Services panel.",
    )

    # --- Phase 3: task board and agent dispatch ----------------------------
    dispatcher_enabled: bool = Field(default=True, description="Off in tests.")
    max_concurrent_runs: int = Field(default=2, ge=1, le=8)
    default_timeout_s: int = Field(default=1800, ge=30, le=6 * 3600)
    default_budget_usd: float = Field(default=1.0, ge=0.01, le=50.0)
    workdir_roots: tuple[Path, ...] = Field(
        default=(Path.home() / "Projects", DEFAULT_DATA_DIR / "workspaces"),
        description="A card's working directory must be inside one of these.",
    )
    claude_path: str = Field(default="/opt/homebrew/bin/claude")
    codex_path: str = Field(default=str(Path.home() / ".local" / "bin" / "codex"))
    hermes_path: str = Field(default=str(Path.home() / ".local" / "bin" / "hermes"))
    openclaw_path: str = Field(default="/opt/homebrew/bin/openclaw")
    hermes_config_path: Path | None = None
    openclaw_config_path: Path | None = None
    run_retention_days: int = Field(default=90, ge=1)
    allowed_hosts_extra: tuple[str, ...] = Field(
        default=(), description="Extra Host values the request guard accepts (tests only)."
    )
    dev_port: int = Field(default=5173, description="Vite dev server port, allowed by the guard.")

    # --- Phase 7: one local alert rules file ------------------------------
    alerts_config_path: Path | None = None

    @property
    def alerts_path(self) -> Path:
        return self.alerts_config_path or self.data_dir / "alerts.toml"

    # --- Phase 6: read-only operations panels ----------------------------
    gh_path: str = "/opt/homebrew/bin/gh"
    ops_reports_dir: Path = Field(default=DEFAULT_DATA_DIR / "reports")
    hermes_reports_dir: Path | None = None

    # --- Phase 4: opt-in Google sign-in. Enabling requires complete local configuration.
    auth_enabled: bool = False
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    auth_allowed_emails: tuple[str, ...] = ()
    auth_origins: tuple[str, ...] = ("http://127.0.0.1:8800",)

    @model_validator(mode="after")
    def validate_auth(self):
        for origin in self.auth_origins:
            u = urlsplit(origin)
            try:
                local = u.hostname == "localhost" or ipaddress.ip_address(u.hostname or "").is_loopback
            except ValueError:
                local = False
            if (not u.hostname or u.username or u.password or u.path or u.query or u.fragment
                    or origin != f"{u.scheme}://{u.netloc}"
                    or u.scheme not in ("http", "https")
                    or (u.scheme == "http" and not local)):
                raise ValueError("Auth origins require a canonical HTTPS origin or HTTP loopback origin")
        if self.auth_enabled and (not self.google_client_id or not self.google_client_secret.get_secret_value()
                                  or not self.auth_allowed_emails or not self.auth_origins):
            raise ValueError("Google sign-in needs client credentials, an email allowlist and auth origins")
        return self

    @property
    def db_path(self) -> Path:
        return self.data_dir / "data.db"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
