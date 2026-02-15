"""Command-line interface for Kikusan."""

import logging
import os
from pathlib import Path

import click

from kikusan.config import get_config
from kikusan.cron.cli import cron
from kikusan.download import UnavailableCooldownError, download, download_url
from kikusan.plugins.cli import plugins
from kikusan.search import (
    get_charts,
    get_mood_categories,
    get_mood_playlists,
    get_playlist_tracks,
    search,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)


@click.group()
@click.version_option()
@click.option(
    "--cookie-mode",
    type=click.Choice(["auto", "always", "never"]),
    default=None,
    envvar="KIKUSAN_COOKIE_MODE",
    help="Cookie usage mode: auto (retry with cookies on auth errors), always (always use cookies), never (never use cookies). Default: auto",
)
@click.option(
    "--cookie-retry-delay",
    type=float,
    default=None,
    envvar="KIKUSAN_COOKIE_RETRY_DELAY",
    help="Delay in seconds before retrying with cookies. Default: 1.0",
)
@click.option(
    "--no-log-cookie-usage",
    is_flag=True,
    default=False,
    help="Disable logging of cookie usage statistics",
)
@click.option(
    "--unavailable-cooldown",
    type=int,
    default=None,
    envvar="KIKUSAN_UNAVAILABLE_COOLDOWN_HOURS",
    help="Hours to wait before retrying unavailable videos (0 = disabled). Default: 168 (7 days)",
)
@click.pass_context
def main(ctx, cookie_mode: str | None, cookie_retry_delay: float | None, no_log_cookie_usage: bool, unavailable_cooldown: int | None):
    """Kikusan - Search and download music from YouTube Music."""
    # Store global options in context for subcommands to use
    ctx.ensure_object(dict)

    # Set environment variables from CLI flags (they override env vars)
    if cookie_mode is not None:
        os.environ["KIKUSAN_COOKIE_MODE"] = cookie_mode
    if cookie_retry_delay is not None:
        os.environ["KIKUSAN_COOKIE_RETRY_DELAY"] = str(cookie_retry_delay)
    if no_log_cookie_usage:
        os.environ["KIKUSAN_LOG_COOKIE_USAGE"] = "false"
    if unavailable_cooldown is not None:
        os.environ["KIKUSAN_UNAVAILABLE_COOLDOWN_HOURS"] = str(unavailable_cooldown)


@main.command()
@click.argument("query")
@click.option("-l", "--limit", default=10, help="Maximum number of results")
def search_cmd(query: str, limit: int):
    """Search for music on YouTube Music."""
    results = search(query, limit=limit)

    if not results:
        click.echo("No results found.")
        return

    click.echo(f"\nFound {len(results)} results:\n")

    for i, track in enumerate(results, 1):
        album_info = f" [{track.album}]" if track.album else ""
        click.echo(f"{i:2}. {track.title} - {track.artist}{album_info}")
        click.echo(f"    ID: {track.video_id}  Duration: {track.duration_display}")
        click.echo()


# Register search command with alias
main.add_command(search_cmd, name="search")


@main.command()
@click.argument("video_id", required=False)
@click.option("--url", "-u", help="YouTube, YouTube Music, or Deezer URL")
@click.option("--query", "-q", help="Search query (downloads first match)")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option(
    "--format",
    "-f",
    "audio_format",
    default=None,
    type=click.Choice(["opus", "mp3", "flac"]),
    help="Audio format (default: opus)",
)
@click.option(
    "--filename",
    "-n",
    "filename_template",
    default=None,
    help="Filename template (default: '%(artist,uploader)s - %(title)s')",
)
@click.option("--no-lyrics", is_flag=True, help="Skip fetching lyrics")
@click.option(
    "--add-to-playlist",
    "-p",
    "playlist_name",
    help="Add downloaded track(s) to M3U playlist",
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
    help="Use only primary artist for folder names in album mode (strips 'feat.', etc.)",
)
@click.option(
    "--replaygain/--no-replaygain",
    default=None,
    help="Apply ReplayGain/R128 loudness normalization tags (requires rsgain)",
)
@click.option(
    "--allow-ugc/--no-allow-ugc",
    default=None,
    help="Include UGC (user-generated content) tracks in playlist/chart results. Default: exclude",
)
def download_cmd(
    video_id: str | None,
    url: str | None,
    query: str | None,
    output: str | None,
    audio_format: str | None,
    filename_template: str | None,
    no_lyrics: bool,
    playlist_name: str | None,
    organization_mode: str | None,
    use_primary_artist: bool | None,
    replaygain: bool | None,
    allow_ugc: bool | None,
):
    """Download a track by video ID, URL, or search query.

    Examples:

      kikusan download VIDEO_ID

      kikusan download --url "https://music.youtube.com/watch?v=..."

      kikusan download --url "https://music.youtube.com/playlist?list=..."

      kikusan download --url "https://www.deezer.com/playlist/..."

      kikusan download --query "Bohemian Rhapsody Queen"
    """
    if not video_id and not url and not query:
        raise click.UsageError("One of VIDEO_ID, --url, or --query is required")

    if replaygain is not None:
        os.environ["KIKUSAN_REPLAYGAIN"] = "true" if replaygain else "false"
    if allow_ugc is not None:
        os.environ["KIKUSAN_ALLOW_UGC"] = "true" if allow_ugc else "false"

    config = get_config()
    output_dir = Path(output) if output else config.download_dir
    fmt = audio_format or config.audio_format
    template = filename_template or config.filename_template
    org_mode = organization_mode if organization_mode is not None else config.organization_mode
    primary_artist = use_primary_artist if use_primary_artist is not None else config.use_primary_artist

    try:
        # Search and download first match
        if query:
            results = search(query, limit=1)
            if not results:
                raise click.ClickException(f"No results found for: {query}")

            track = results[0]
            click.echo(f"Found: {track.title} - {track.artist}")

            audio_path = download(
                video_id=track.video_id,
                output_dir=output_dir,
                audio_format=fmt,
                filename_template=template,
                fetch_lyrics=not no_lyrics,
                organization_mode=org_mode,
                use_primary_artist=primary_artist,
                apply_replaygain=config.replaygain,
            )
            if audio_path:
                click.echo(f"Downloaded: {audio_path}")
                if playlist_name:
                    from kikusan.playlist import add_to_m3u

                    add_to_m3u([audio_path], playlist_name, output_dir)
                    click.echo(f"Added to playlist: {playlist_name}.m3u")
            return

        # Handle URL (YouTube, YouTube Music, or Deezer)
        if url:
            from kikusan.deezer import get_tracks_from_url as get_deezer_tracks_from_url
            from kikusan.deezer import is_deezer_url

            if is_deezer_url(url):
                _download_external_url(
                    url=url,
                    output_dir=output_dir,
                    audio_format=fmt,
                    filename_template=template,
                    fetch_lyrics=not no_lyrics,
                    playlist_name=playlist_name,
                    organization_mode=org_mode,
                    use_primary_artist=primary_artist,
                    source_name="Deezer playlist",
                    get_tracks_from_url=get_deezer_tracks_from_url,
                    apply_replaygain=config.replaygain,
                )
            else:
                result = download_url(
                    url=url,
                    output_dir=output_dir,
                    audio_format=fmt,
                    filename_template=template,
                    fetch_lyrics=not no_lyrics,
                    organization_mode=org_mode,
                    use_primary_artist=primary_artist,
                    apply_replaygain=config.replaygain,
                )

                if isinstance(result, list):
                    click.echo(f"Downloaded {len(result)} tracks to {output_dir}")
                    if playlist_name and result:
                        from kikusan.playlist import add_to_m3u

                        add_to_m3u(result, playlist_name, output_dir)
                        click.echo(f"Added {len(result)} track(s) to playlist: {playlist_name}.m3u")
                elif result:
                    click.echo(f"Downloaded: {result}")
                    if playlist_name:
                        from kikusan.playlist import add_to_m3u

                        add_to_m3u([result], playlist_name, output_dir)
                        click.echo(f"Added to playlist: {playlist_name}.m3u")
                else:
                    click.echo("Download completed but could not locate file.")
            return

        # Download by video ID
        audio_path = download(
            video_id=video_id,
            output_dir=output_dir,
            audio_format=fmt,
            filename_template=template,
            fetch_lyrics=not no_lyrics,
            organization_mode=org_mode,
            use_primary_artist=primary_artist,
            apply_replaygain=config.replaygain,
        )

        if audio_path:
            click.echo(f"Downloaded: {audio_path}")
            if playlist_name:
                from kikusan.playlist import add_to_m3u

                add_to_m3u([audio_path], playlist_name, output_dir)
                click.echo(f"Added to playlist: {playlist_name}.m3u")
        else:
            click.echo("Download completed but could not locate file.")

    except UnavailableCooldownError as e:
        click.echo(str(e))
        return
    except Exception as e:
        raise click.ClickException(str(e))


def _download_external_url(
    url: str,
    output_dir: Path,
    audio_format: str,
    filename_template: str,
    fetch_lyrics: bool,
    playlist_name: str | None = None,
    organization_mode: str = "flat",
    use_primary_artist: bool = False,
    source_name: str = "External playlist",
    get_tracks_from_url: callable | None = None,
    apply_replaygain: bool = False,
) -> None:
    """Download tracks from an external playlist source by searching YouTube Music."""
    if get_tracks_from_url is None:
        raise ValueError("get_tracks_from_url callback is required")

    source_tracks = get_tracks_from_url(url)

    if not source_tracks:
        click.echo(f"No tracks found in {source_name.lower()} URL.")
        return

    click.echo(f"Found {len(source_tracks)} tracks in {source_name}")

    downloaded = 0
    skipped = 0
    failed = 0
    downloaded_paths = []

    for i, source_track in enumerate(source_tracks, 1):
        click.echo(
            f"[{i}/{len(source_tracks)}] Searching: {source_track.artist} - {source_track.name}"
        )

        # Search YouTube Music for this track
        results = search(source_track.search_query, limit=1)

        if not results:
            click.echo(f"  Not found on YouTube Music, skipping")
            failed += 1
            continue

        yt_track = results[0]
        click.echo(f"  Found: {yt_track.title} - {yt_track.artist}")

        try:
            audio_path = download(
                video_id=yt_track.video_id,
                output_dir=output_dir,
                audio_format=audio_format,
                filename_template=filename_template,
                fetch_lyrics=fetch_lyrics,
                organization_mode=organization_mode,
                use_primary_artist=use_primary_artist,
                apply_replaygain=apply_replaygain,
            )

            if audio_path:
                downloaded_paths.append(audio_path)
                if "Skipping" not in str(audio_path):
                    downloaded += 1
                else:
                    skipped += 1

        except Exception as e:
            click.echo(f"  Failed: {e}")
            failed += 1

    click.echo(f"\nCompleted: {downloaded} downloaded, {skipped} skipped, {failed} failed")

    # Add all downloaded tracks to playlist
    if playlist_name and downloaded_paths:
        from kikusan.playlist import add_to_m3u

        add_to_m3u(downloaded_paths, playlist_name, output_dir)
        click.echo(f"Added {len(downloaded_paths)} track(s) to playlist: {playlist_name}.m3u")


main.add_command(download_cmd, name="download")


main.add_command(cron, name="cron")


main.add_command(plugins, name="plugins")


@main.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--lyrics/--no-lyrics", default=True, help="Fetch and save lyrics from lrclib.net (default: enabled)")
@click.option("--replaygain/--no-replaygain", default=True, help="Apply ReplayGain/R128 tags via rsgain (default: enabled)")
@click.option("--dry-run", is_flag=True, help="Preview what would be done without making changes")
def tag(directory: str, lyrics: bool, replaygain: bool, dry_run: bool):
    """Tag existing audio files with lyrics and ReplayGain.

    Recursively processes .opus, .mp3, .flac files in DIRECTORY.

    Examples:

      kikusan tag /path/to/music

      kikusan tag --no-replaygain /path/to/music

      kikusan tag --dry-run /path/to/music
    """
    from kikusan.tagging import tag_directory

    target = Path(directory)

    if dry_run:
        click.echo("[dry-run] Previewing changes only")

    stats = tag_directory(
        target,
        do_lyrics=lyrics,
        do_replaygain=replaygain,
        dry_run=dry_run,
    )

    click.echo(f"\nProcessed {stats.files_found} files:")
    if lyrics:
        click.echo(f"  Lyrics: {stats.lyrics_added} added, {stats.lyrics_skipped} skipped (already exist), {stats.lyrics_not_found} not found, {stats.lyrics_failed} failed")
    if replaygain:
        click.echo(f"  ReplayGain: {stats.replaygain_applied} applied, {stats.replaygain_skipped} skipped (already exist), {stats.replaygain_failed} failed")
    if stats.errors:
        click.echo(f"  Errors: {stats.errors}")


# --- Explore command group ---


@main.group()
def explore():
    """Explore moods, genres, and charts on YouTube Music."""


@explore.command(name="moods")
def explore_moods():
    """List available mood & genre categories."""
    try:
        sections = get_mood_categories()
    except Exception as e:
        raise click.ClickException(str(e))

    if not sections:
        click.echo("No categories found.")
        return

    for section in sections:
        click.echo(f"\n{section.title}:")
        for cat in section.categories:
            click.echo(f"  {cat.title}  (params: {cat.params})")


@explore.command(name="mood-playlists")
@click.argument("params")
@click.option("--download", "-d", "do_download", is_flag=True, help="Download all tracks from all playlists in this category")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option(
    "--format", "-f", "audio_format",
    type=click.Choice(["opus", "mp3", "flac"]),
    default=None,
    help="Audio format (default: opus)",
)
@click.option("--add-to-playlist", "-p", "playlist_name", help="Add downloaded tracks to M3U playlist")
@click.option(
    "--allow-ugc/--no-allow-ugc",
    default=None,
    help="Include UGC (user-generated content) tracks. Default: exclude",
)
def explore_mood_playlists_cmd(params: str, do_download: bool, output: str | None, audio_format: str | None, playlist_name: str | None, allow_ugc: bool | None):
    """List playlists for a mood/genre category.

    PARAMS is the category identifier from 'explore moods'.
    Use --download to download all tracks from the playlists.
    """
    if allow_ugc is not None:
        os.environ["KIKUSAN_ALLOW_UGC"] = "true" if allow_ugc else "false"

    config = get_config()

    try:
        playlists = get_mood_playlists(params)
    except Exception as e:
        raise click.ClickException(str(e))

    if not playlists:
        click.echo("No playlists found.")
        return

    for i, pl in enumerate(playlists, 1):
        author = f" by {pl.author}" if pl.author else ""
        click.echo(f"{i:2}. {pl.title}{author}")
        click.echo(f"    Playlist ID: {pl.playlist_id}")

    if do_download:
        for pl in playlists:
            click.echo(f"\nFetching tracks from: {pl.title}")
            try:
                tracks = get_playlist_tracks(pl.playlist_id, allow_ugc=config.allow_ugc)
            except Exception as e:
                click.echo(f"  Failed to fetch tracks: {e}")
                continue
            _download_explore_tracks(tracks, output, audio_format, playlist_name)


@explore.command(name="charts")
@click.option("--country", "-c", default="ZZ", help="ISO 3166-1 Alpha-2 country code (default: ZZ for global)")
@click.option("--download", "-d", "do_download", is_flag=True, help="Download all chart tracks")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option(
    "--format", "-f", "audio_format",
    type=click.Choice(["opus", "mp3", "flac"]),
    default=None,
    help="Audio format (default: opus)",
)
@click.option("--add-to-playlist", "-p", "playlist_name", help="Add downloaded tracks to M3U playlist")
@click.option(
    "--allow-ugc/--no-allow-ugc",
    default=None,
    help="Include UGC (user-generated content) tracks. Default: exclude",
)
def explore_charts_cmd(country: str, do_download: bool, output: str | None, audio_format: str | None, playlist_name: str | None, allow_ugc: bool | None):
    """Show current music charts.

    Use --download to download all chart tracks.
    """
    if allow_ugc is not None:
        os.environ["KIKUSAN_ALLOW_UGC"] = "true" if allow_ugc else "false"

    config = get_config()

    try:
        charts = get_charts(country, allow_ugc=config.allow_ugc)
    except Exception as e:
        raise click.ClickException(str(e))

    if charts.tracks:
        click.echo(f"\nTop Songs ({charts.country}):")
        for track in charts.tracks:
            rank = f"#{track.rank} " if track.rank else ""
            click.echo(f"  {rank}{track.title} - {track.artist}")
            click.echo(f"    ID: {track.video_id}")

    if charts.artists:
        click.echo(f"\nTop Artists ({charts.country}):")
        for artist in charts.artists:
            rank = f"#{artist.rank} " if artist.rank else ""
            click.echo(f"  {rank}{artist.title}")

    if do_download and charts.tracks:
        click.echo(f"\nDownloading {len(charts.tracks)} chart tracks...")
        config = get_config()
        output_dir = Path(output) if output else config.download_dir
        fmt = audio_format or config.audio_format
        downloaded_paths = []

        for i, track in enumerate(charts.tracks, 1):
            click.echo(f"[{i}/{len(charts.tracks)}] Downloading: {track.title} - {track.artist}")
            try:
                audio_path = download(
                    video_id=track.video_id,
                    output_dir=output_dir,
                    audio_format=fmt,
                    filename_template=config.filename_template,
                    fetch_lyrics=True,
                    organization_mode=config.organization_mode,
                    use_primary_artist=config.use_primary_artist,
                    apply_replaygain=config.replaygain,
                )
                if audio_path:
                    downloaded_paths.append(audio_path)
            except UnavailableCooldownError as e:
                click.echo(f"  Skipped (cooldown): {e}")
            except Exception as e:
                click.echo(f"  Failed: {e}")

        click.echo(f"\nDownloaded {len(downloaded_paths)} of {len(charts.tracks)} tracks")
        if playlist_name and downloaded_paths:
            from kikusan.playlist import add_to_m3u
            add_to_m3u(downloaded_paths, playlist_name, output_dir)
            click.echo(f"Added {len(downloaded_paths)} track(s) to playlist: {playlist_name}.m3u")


def _download_explore_tracks(
    tracks: list,
    output: str | None,
    audio_format: str | None,
    playlist_name: str | None,
) -> None:
    """Download a list of Track objects from explore results."""
    if not tracks:
        click.echo("  No tracks to download.")
        return

    config = get_config()
    output_dir = Path(output) if output else config.download_dir
    fmt = audio_format or config.audio_format
    downloaded_paths = []

    for i, track in enumerate(tracks, 1):
        click.echo(f"[{i}/{len(tracks)}] Downloading: {track.title} - {track.artist}")
        try:
            audio_path = download(
                video_id=track.video_id,
                output_dir=output_dir,
                audio_format=fmt,
                filename_template=config.filename_template,
                fetch_lyrics=True,
                organization_mode=config.organization_mode,
                use_primary_artist=config.use_primary_artist,
                apply_replaygain=config.replaygain,
            )
            if audio_path:
                downloaded_paths.append(audio_path)
        except UnavailableCooldownError as e:
            click.echo(f"  Skipped (cooldown): {e}")
        except Exception as e:
            click.echo(f"  Failed: {e}")

    click.echo(f"\nDownloaded {len(downloaded_paths)} of {len(tracks)} tracks")
    if playlist_name and downloaded_paths:
        from kikusan.playlist import add_to_m3u
        add_to_m3u(downloaded_paths, playlist_name, output_dir)
        click.echo(f"Added {len(downloaded_paths)} track(s) to playlist: {playlist_name}.m3u")


@main.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", "-p", default=None, type=int, help="Port to listen on")
@click.option(
    "--cors-origins",
    default=None,
    envvar="KIKUSAN_CORS_ORIGINS",
    help="CORS allowed origins (comma-separated, or '*' for all). Default: *",
)
@click.option(
    "--web-playlist",
    default=None,
    envvar="KIKUSAN_WEB_PLAYLIST",
    help="M3U playlist name for web downloads (optional)",
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
    help="Use only primary artist for folder names in album mode (strips 'feat.', etc.)",
)
@click.option(
    "--multi-user/--no-multi-user",
    default=None,
    help="Enable per-user M3U playlists via Remote-User header (for reverse proxy SSO). Default: disabled",
)
@click.option(
    "--replaygain/--no-replaygain",
    default=None,
    help="Apply ReplayGain/R128 loudness normalization tags (requires rsgain)",
)
@click.option(
    "--allow-ugc/--no-allow-ugc",
    default=None,
    help="Include UGC (user-generated content) tracks in playlist/chart results. Default: exclude",
)
def web(
    host: str,
    port: int | None,
    cors_origins: str | None,
    web_playlist: str | None,
    organization_mode: str | None,
    use_primary_artist: bool | None,
    multi_user: bool | None,
    replaygain: bool | None,
    allow_ugc: bool | None,
):
    """Start the web interface."""
    import uvicorn

    from kikusan.config import get_config

    # Override env vars if CLI flags provided
    if cors_origins is not None:
        os.environ["KIKUSAN_CORS_ORIGINS"] = cors_origins
    if web_playlist is not None:
        os.environ["KIKUSAN_WEB_PLAYLIST"] = web_playlist
    if organization_mode is not None:
        os.environ["KIKUSAN_ORGANIZATION_MODE"] = organization_mode
    if use_primary_artist is not None:
        os.environ["KIKUSAN_USE_PRIMARY_ARTIST"] = "true" if use_primary_artist else "false"
    if multi_user is not None:
        os.environ["KIKUSAN_MULTI_USER"] = "true" if multi_user else "false"
    if replaygain is not None:
        os.environ["KIKUSAN_REPLAYGAIN"] = "true" if replaygain else "false"
    if allow_ugc is not None:
        os.environ["KIKUSAN_ALLOW_UGC"] = "true" if allow_ugc else "false"

    config = get_config()
    server_port = port or config.web_port

    click.echo(f"Starting web server at http://{host}:{server_port}")

    from kikusan.web.app import app

    uvicorn.run(app, host=host, port=server_port)


if __name__ == "__main__":
    main()
