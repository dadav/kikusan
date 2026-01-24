"""Cron CLI command implementation."""

import logging
import os
from pathlib import Path

import click

from kikusan.config import get_config
from kikusan.cron.scheduler import CronScheduler

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--config",
    "-c",
    default="cron.yaml",
    type=click.Path(exists=True),
    help="Path to cron configuration file (default: cron.yaml)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Override download directory",
)
@click.option(
    "--once",
    is_flag=True,
    help="Run all playlists once and exit (skip scheduling)",
)
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
def cron(
    config: str,
    output: str | None,
    once: bool,
    audio_format: str | None,
    organization_mode: str | None,
    use_primary_artist: bool | None,
):
    """
    Run continuous playlist sync based on cron.yaml.

    This command monitors configured playlists and automatically downloads
    new tracks according to the cron schedule defined for each playlist.

    Configuration file format (cron.yaml):

    \b
    playlists:
      playlist_name:
        url: <YouTube, YouTube Music, or Spotify playlist URL>
        sync: <true to delete removed tracks, false to keep them>
        schedule: <cron expression, e.g., "5 4 * * *">

    Examples:

    \b
      # Run continuously with default config
      kikusan cron

    \b
      # Run with custom config file
      kikusan cron --config /path/to/cron.yaml

    \b
      # Run all playlists once and exit
      kikusan cron --once

    \b
      # Override download directory
      kikusan cron --output /custom/downloads
    """
    # Set environment variables from CLI flags (they override env vars)
    if audio_format is not None:
        os.environ["KIKUSAN_AUDIO_FORMAT"] = audio_format
    if organization_mode is not None:
        os.environ["KIKUSAN_ORGANIZATION_MODE"] = organization_mode
    if use_primary_artist is not None:
        os.environ["KIKUSAN_USE_PRIMARY_ARTIST"] = "true" if use_primary_artist else "false"

    config_path = Path(config)
    download_dir = Path(output) if output else None

    # If download_dir not specified, use config default
    if not download_dir:
        main_config = get_config()
        download_dir = main_config.download_dir

    try:
        scheduler = CronScheduler(config_path, download_dir)

        if once:
            # Run all playlists once and exit
            click.echo("Running all playlists once...")
            scheduler.sync_all_once()
            click.echo("Done.")
        else:
            # Run continuously
            click.echo(f"Starting cron scheduler with config: {config_path}")
            click.echo(f"Download directory: {download_dir}")
            scheduler.run_forever()

    except FileNotFoundError as e:
        raise click.ClickException(str(e))
    except ValueError as e:
        raise click.ClickException(f"Configuration error: {e}")
    except KeyboardInterrupt:
        click.echo("\nStopping...")
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")
