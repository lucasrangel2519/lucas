"""Configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, never overrides real env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "sim"}


@dataclass
class Config:
    ig_app_id: str
    ig_app_secret: str
    ig_redirect_uri: str
    ig_user_id: str
    ig_access_token: str
    ig_api_version: str

    tiktok_client_key: str
    tiktok_client_secret: str
    tiktok_redirect_uri: str
    tiktok_refresh_token: str
    tiktok_access_token: str
    tiktok_privacy_level: str
    tiktok_brand_organic: bool

    media_base_url: str
    timezone: str
    late_window_hours: float
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        env = os.environ.get
        return cls(
            ig_app_id=env("IG_APP_ID", ""),
            ig_app_secret=env("IG_APP_SECRET", ""),
            ig_redirect_uri=env("IG_REDIRECT_URI", ""),
            ig_user_id=env("IG_USER_ID", ""),
            ig_access_token=env("IG_ACCESS_TOKEN", ""),
            ig_api_version=env("IG_API_VERSION", "") or "v23.0",
            tiktok_client_key=env("TIKTOK_CLIENT_KEY", ""),
            tiktok_client_secret=env("TIKTOK_CLIENT_SECRET", ""),
            tiktok_redirect_uri=env("TIKTOK_REDIRECT_URI", ""),
            tiktok_refresh_token=env("TIKTOK_REFRESH_TOKEN", ""),
            tiktok_access_token=env("TIKTOK_ACCESS_TOKEN", ""),
            tiktok_privacy_level=env("TIKTOK_PRIVACY_LEVEL", "") or "SELF_ONLY",
            tiktok_brand_organic=_bool("TIKTOK_BRAND_ORGANIC"),
            media_base_url=(env("MEDIA_BASE_URL", "") or "").rstrip("/"),
            timezone=env("TIMEZONE", "") or "America/Sao_Paulo",
            late_window_hours=float(env("JANELA_ATRASO_HORAS", "") or 12),
            dry_run=_bool("DRY_RUN"),
        )
