"""Configuration handling for Kikusan."""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Default filename template: Artist - Title
DEFAULT_FILENAME_TEMPLATE = "%(artist,uploader)s - %(title)s"


@dataclass
class Config:
    """Application configuration."""

    download_dir: Path
    audio_format: str
    filename_template: str
    organization_mode: str
    use_primary_artist: bool
    web_port: int
    spotify_client_id: str | None
    spotify_client_secret: str | None
    web_playlist_name: str | None = None
    gotify_url: str | None = None
    gotify_token: str | None = None
    yt_dlp_cookie_file: str | None = None
    cookie_mode: str = "auto"
    cookie_retry_delay: float = 1.0
    log_cookie_usage: bool = True
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    @property
    def cookie_file_path(self) -> str | None:
        """Get the effective cookie file path, checking uploaded file first."""
        # Check for uploaded cookie file first
        uploaded_cookie = Path(".kikusan/cookies.txt")
        if uploaded_cookie.exists():
            return str(uploaded_cookie)

        # Fall back to env var
        return self.yt_dlp_cookie_file

    @classmethod
    def from_env(cls) -> "Config":
        """Create config from environment variables with defaults."""
        # Parse CORS origins
        cors_env = os.getenv("KIKUSAN_CORS_ORIGINS", "*")
        if cors_env == "*":
            cors_origins = ["*"]
        else:
            cors_origins = [origin.strip() for origin in cors_env.split(",")]

        # Parse and validate cookie mode
        cookie_mode = os.getenv("KIKUSAN_COOKIE_MODE", "auto").lower()
        if cookie_mode not in ("auto", "always", "never"):
            raise ValueError(
                f"Invalid KIKUSAN_COOKIE_MODE: {cookie_mode}. "
                f"Must be one of: auto, always, never"
            )

        # Parse cookie retry delay
        cookie_retry_delay = float(os.getenv("KIKUSAN_COOKIE_RETRY_DELAY", "1.0"))

        # Parse log cookie usage flag
        log_cookie_usage = os.getenv("KIKUSAN_LOG_COOKIE_USAGE", "true").lower() in (
            "true",
            "1",
            "yes",
        )

        return cls(
            download_dir=Path(os.getenv("KIKUSAN_DOWNLOAD_DIR", "./downloads")),
            audio_format=os.getenv("KIKUSAN_AUDIO_FORMAT", "opus"),
            filename_template=os.getenv("KIKUSAN_FILENAME_TEMPLATE", DEFAULT_FILENAME_TEMPLATE),
            organization_mode=os.getenv("KIKUSAN_ORGANIZATION_MODE", "flat"),
            use_primary_artist=os.getenv("KIKUSAN_USE_PRIMARY_ARTIST", "false").lower() in ("true", "1", "yes"),
            web_port=int(os.getenv("KIKUSAN_WEB_PORT", "8000")),
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            web_playlist_name=os.getenv("KIKUSAN_WEB_PLAYLIST"),
            gotify_url=os.getenv("GOTIFY_URL"),
            gotify_token=os.getenv("GOTIFY_TOKEN"),
            yt_dlp_cookie_file=os.getenv("YT_DLP_COOKIE_FILE"),
            cookie_mode=cookie_mode,
            cookie_retry_delay=cookie_retry_delay,
            log_cookie_usage=log_cookie_usage,
            cors_origins=cors_origins,
        )

    @property
    def spotify_configured(self) -> bool:
        """Check if Spotify credentials are configured."""
        return bool(self.spotify_client_id and self.spotify_client_secret)

    @property
    def gotify_configured(self) -> bool:
        """Check if Gotify notifications are configured."""
        return bool(self.gotify_url and self.gotify_token)

    def validate_organization_mode(self):
        """Validate organization mode value."""
        if self.organization_mode not in ("flat", "album"):
            raise ValueError(
                f"Invalid organization mode: {self.organization_mode}. Must be 'flat' or 'album'."
            )


def get_config() -> Config:
    """Get the current configuration."""
    return Config.from_env()
