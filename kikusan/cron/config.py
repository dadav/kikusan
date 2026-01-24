"""Cron configuration loading and validation."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from croniter import croniter

from kikusan.hooks import HookConfig, parse_hooks_config

logger = logging.getLogger(__name__)


@dataclass
class PlaylistConfig:
    """Configuration for a single playlist."""

    name: str
    url: str
    sync: bool
    schedule: str


@dataclass
class PluginInstanceConfig:
    """Configuration for a single plugin instance."""

    name: str
    type: str  # Plugin type name
    sync: bool
    schedule: str
    config: dict  # Plugin-specific config


@dataclass
class CronConfig:
    """Root configuration for cron playlists and plugins."""

    playlists: dict[str, PlaylistConfig]
    plugins: dict[str, PluginInstanceConfig]
    hooks: list[HookConfig] = field(default_factory=list)


def load_config(path: Path) -> CronConfig:
    """
    Load and validate cron configuration from YAML file.

    Args:
        path: Path to cron.yaml file

    Returns:
        Validated CronConfig

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax: {e}")

    if not data:
        raise ValueError("Config file is empty")

    # Check that at least playlists or plugins are defined
    if "playlists" not in data and "plugins" not in data:
        raise ValueError("Config must have 'playlists' or 'plugins' key")

    # Load playlists (optional, defaults to empty)
    playlists = {}
    if "playlists" in data:
        playlists_data = data["playlists"]
        if not isinstance(playlists_data, dict):
            raise ValueError("'playlists' must be a dictionary")

        for name, config in playlists_data.items():
            # Validate playlist name
            sanitized_name = validate_playlist_name(name)

            # Validate required fields
            if not isinstance(config, dict):
                raise ValueError(f"Playlist '{name}' config must be a dictionary")

            if "url" not in config:
                raise ValueError(f"Playlist '{name}' missing required field: url")
            if "sync" not in config:
                raise ValueError(f"Playlist '{name}' missing required field: sync")
            if "schedule" not in config:
                raise ValueError(f"Playlist '{name}' missing required field: schedule")

            url = config["url"]
            sync = config["sync"]
            schedule = config["schedule"]

            # Validate types
            if not isinstance(url, str):
                raise ValueError(f"Playlist '{name}' url must be a string")
            if not isinstance(sync, bool):
                raise ValueError(f"Playlist '{name}' sync must be a boolean")
            if not isinstance(schedule, str):
                raise ValueError(f"Playlist '{name}' schedule must be a string")

            # Validate URL
            validate_url(url, name)

            # Validate cron schedule
            validate_cron_schedule(schedule, name)

            playlists[sanitized_name] = PlaylistConfig(
                name=sanitized_name,
                url=url,
                sync=sync,
                schedule=schedule,
            )

    # Load plugins (optional, defaults to empty)
    plugins = {}
    if "plugins" in data:
        plugins_data = data["plugins"]
        if not isinstance(plugins_data, dict):
            raise ValueError("'plugins' must be a dictionary")

        for name, config in plugins_data.items():
            # Validate instance name
            sanitized_name = validate_playlist_name(name)

            # Validate required fields
            if not isinstance(config, dict):
                raise ValueError(f"Plugin '{name}' config must be a dictionary")

            if "type" not in config:
                raise ValueError(f"Plugin '{name}' missing required field: type")
            if "sync" not in config:
                raise ValueError(f"Plugin '{name}' missing required field: sync")
            if "schedule" not in config:
                raise ValueError(f"Plugin '{name}' missing required field: schedule")
            if "config" not in config:
                raise ValueError(f"Plugin '{name}' missing required field: config")

            plugin_type = config["type"]

            # Validate types
            if not isinstance(plugin_type, str):
                raise ValueError(f"Plugin '{name}' type must be a string")
            if not isinstance(config["sync"], bool):
                raise ValueError(f"Plugin '{name}' sync must be a boolean")
            if not isinstance(config["schedule"], str):
                raise ValueError(f"Plugin '{name}' schedule must be a string")
            if not isinstance(config["config"], dict):
                raise ValueError(f"Plugin '{name}' config must be a dictionary")

            # Get plugin class and validate config
            try:
                from kikusan.plugins.registry import get_plugin

                plugin_class = get_plugin(plugin_type)
                plugin_instance = plugin_class()
                plugin_instance.validate_config(config["config"])
            except Exception as e:
                raise ValueError(f"Plugin '{name}' configuration invalid: {e}")

            # Validate cron schedule
            validate_cron_schedule(config["schedule"], name)

            plugins[sanitized_name] = PluginInstanceConfig(
                name=sanitized_name,
                type=plugin_type,
                sync=config["sync"],
                schedule=config["schedule"],
                config=config["config"],
            )

    # Load hooks (optional, defaults to empty)
    hooks = []
    if "hooks" in data:
        hooks_data = data["hooks"]
        if not isinstance(hooks_data, list):
            raise ValueError("'hooks' must be a list")
        hooks = parse_hooks_config(hooks_data)

    logger.info(
        "Loaded configuration for %d playlist(s), %d plugin(s), and %d hook(s)",
        len(playlists),
        len(plugins),
        len(hooks),
    )
    return CronConfig(playlists=playlists, plugins=plugins, hooks=hooks)


def validate_playlist_name(name: str) -> str:
    """
    Validate and sanitize playlist name.

    Only allows alphanumeric characters, dash, and underscore to prevent
    path traversal and filesystem issues.

    Args:
        name: Playlist name

    Returns:
        Sanitized playlist name

    Raises:
        ValueError: If name contains invalid characters
    """
    if not re.match(r"^[\w\-]+$", name):
        raise ValueError(
            f"Invalid playlist name '{name}': "
            "only alphanumeric, dash, and underscore allowed"
        )
    return name


def validate_url(url: str, playlist_name: str) -> None:
    """
    Validate playlist URL.

    Ensures URL is a valid YouTube, YouTube Music, or Spotify URL.

    Args:
        url: Playlist URL
        playlist_name: Playlist name for error messages

    Raises:
        ValueError: If URL is invalid
    """
    # YouTube/YouTube Music patterns
    youtube_patterns = [
        r"^https?://(www\.)?youtube\.com/",
        r"^https?://music\.youtube\.com/",
        r"^https?://youtu\.be/",
    ]

    # Spotify patterns
    spotify_patterns = [
        r"^https?://(open\.)?spotify\.com/playlist/",
        r"^https?://(open\.)?spotify\.com/album/",
    ]

    is_valid = False
    for pattern in youtube_patterns + spotify_patterns:
        if re.match(pattern, url):
            is_valid = True
            break

    if not is_valid:
        raise ValueError(
            f"Playlist '{playlist_name}' has invalid URL: {url}. "
            "Must be a YouTube, YouTube Music, or Spotify URL"
        )


def validate_cron_schedule(schedule: str, playlist_name: str) -> None:
    """
    Validate cron schedule expression.

    Args:
        schedule: Cron expression (e.g., "5 4 * * *")
        playlist_name: Playlist name for error messages

    Raises:
        ValueError: If cron expression is invalid
    """
    if not schedule or not schedule.strip():
        raise ValueError(f"Playlist '{playlist_name}' has empty schedule")

    try:
        # croniter will raise ValueError if expression is invalid
        croniter(schedule)
    except Exception as e:
        raise ValueError(
            f"Playlist '{playlist_name}' has invalid cron schedule '{schedule}': {e}"
        )
