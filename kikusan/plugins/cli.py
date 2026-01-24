"""CLI command for plugin-based sync."""

import json
import logging
import os
from pathlib import Path

import click

from kikusan.config import get_config
from kikusan.plugins.base import PluginConfig
from kikusan.plugins.registry import discover_plugins, get_plugin, list_plugins
from kikusan.plugins.sync import sync_plugin_instance

logger = logging.getLogger(__name__)


@click.group()
def plugins():
    """Run plugin-based sync operations."""
    # Discover plugins on first use
    discover_plugins()


@plugins.command(name="list")
def list_available_plugins():
    """List all available plugins."""
    discover_plugins()
    plugin_names = list_plugins()

    if not plugin_names:
        click.echo("No plugins available.")
        return

    click.echo("Available plugins:\n")
    for plugin_name in plugin_names:
        plugin_class = get_plugin(plugin_name)
        plugin = plugin_class()

        click.echo(f"  {plugin_name}")
        schema = plugin.config_schema
        if schema.get("required"):
            click.echo(f"    Required: {', '.join(schema['required'])}")
        if schema.get("optional"):
            click.echo(f"    Optional: {', '.join(schema['optional'].keys())}")
        click.echo()


@plugins.command(name="run")
@click.argument("plugin_name")
@click.option("--config", "-c", help="Plugin config as JSON string", required=True)
@click.option("--output", "-o", type=click.Path(), help="Download directory")
@click.option(
    "--format",
    "-f",
    "audio_format",
    default=None,
    type=click.Choice(["opus", "mp3", "flac"]),
    envvar="KIKUSAN_AUDIO_FORMAT",
    help="Audio format for downloads. Default: opus",
)
@click.option(
    "--organization-mode",
    type=click.Choice(["flat", "album"]),
    default=None,
    envvar="KIKUSAN_ORGANIZATION_MODE",
    help="File organization: flat (all in one dir) or album (Artist/Year - Album/Track). Default: flat",
)
@click.option(
    "--use-primary-artist/--no-use-primary-artist",
    default=None,
    help="Use only primary artist for folder names in album mode",
)
def sync_once(
    plugin_name: str,
    config: str,
    output: str | None,
    audio_format: str | None,
    organization_mode: str | None,
    use_primary_artist: bool | None,
):
    """Run a plugin sync once (without cron.yaml).

    Examples:

      kikusan plugins run listenbrainz --config '{"user": "myuser"}'

      kikusan plugins run rss --config '{"url": "https://..."}'
    """
    discover_plugins()

    main_config = get_config()
    download_dir = Path(output) if output else main_config.download_dir

    # Use CLI parameters if provided, otherwise use config defaults
    fmt = audio_format if audio_format is not None else main_config.audio_format
    org_mode = organization_mode if organization_mode is not None else main_config.organization_mode
    primary_artist = use_primary_artist if use_primary_artist is not None else main_config.use_primary_artist

    try:
        # Parse config
        plugin_config = json.loads(config)

        # Get plugin
        plugin_class = get_plugin(plugin_name)
        plugin = plugin_class()

        # Validate config
        plugin.validate_config(plugin_config)

        # Create config object
        cfg = PluginConfig(
            name=plugin_name,
            download_dir=download_dir,
            audio_format=fmt,
            filename_template=main_config.filename_template,
            config=plugin_config,
            organization_mode=org_mode,
            use_primary_artist=primary_artist,
        )

        # Run sync
        click.echo(f"Running {plugin_name} sync...")
        result = sync_plugin_instance(plugin, cfg, sync_mode=False)

        click.echo(
            f"\nCompleted: {result.downloaded} downloaded, "
            f"{result.skipped} skipped, {result.failed} failed"
        )

        if result.errors:
            click.echo("\nErrors:")
            for error in result.errors:
                click.echo(f"  - {error}")

    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON config: {e}")
    except Exception as e:
        raise click.ClickException(str(e))
