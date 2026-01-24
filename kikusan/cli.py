"""Command-line interface for Kikusan."""

import logging
import os
from pathlib import Path

import click

from kikusan.config import get_config
from kikusan.cron.cli import cron
from kikusan.download import download, download_url
from kikusan.plugins.cli import plugins
from kikusan.search import search

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
@click.pass_context
def main(ctx, cookie_mode: str | None, cookie_retry_delay: float | None, no_log_cookie_usage: bool):
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
@click.option("--url", "-u", help="YouTube, YouTube Music, or Spotify URL")
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
):
    """Download a track by video ID, URL, or search query.

    Examples:

      kikusan download VIDEO_ID

      kikusan download --url "https://music.youtube.com/watch?v=..."

      kikusan download --url "https://music.youtube.com/playlist?list=..."

      kikusan download --url "https://open.spotify.com/playlist/..."

      kikusan download --query "Bohemian Rhapsody Queen"
    """
    if not video_id and not url and not query:
        raise click.UsageError("One of VIDEO_ID, --url, or --query is required")

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
            )
            if audio_path:
                click.echo(f"Downloaded: {audio_path}")
                if playlist_name:
                    from kikusan.playlist import add_to_m3u

                    add_to_m3u([audio_path], playlist_name, output_dir)
                    click.echo(f"Added to playlist: {playlist_name}.m3u")
            return

        # Handle URL (YouTube, YouTube Music, or Spotify)
        if url:
            from kikusan.spotify import is_spotify_url

            if is_spotify_url(url):
                _download_spotify_url(
                    url=url,
                    output_dir=output_dir,
                    audio_format=fmt,
                    filename_template=template,
                    fetch_lyrics=not no_lyrics,
                    playlist_name=playlist_name,
                    organization_mode=org_mode,
                    use_primary_artist=primary_artist,
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
        )

        if audio_path:
            click.echo(f"Downloaded: {audio_path}")
            if playlist_name:
                from kikusan.playlist import add_to_m3u

                add_to_m3u([audio_path], playlist_name, output_dir)
                click.echo(f"Added to playlist: {playlist_name}.m3u")
        else:
            click.echo("Download completed but could not locate file.")

    except Exception as e:
        raise click.ClickException(str(e))


def _download_spotify_url(
    url: str,
    output_dir: Path,
    audio_format: str,
    filename_template: str,
    fetch_lyrics: bool,
    playlist_name: str | None = None,
    organization_mode: str = "flat",
    use_primary_artist: bool = False,
) -> None:
    """Download tracks from a Spotify playlist/album by searching YouTube Music."""
    from kikusan.spotify import get_tracks_from_url

    spotify_tracks = get_tracks_from_url(url)

    if not spotify_tracks:
        click.echo("No tracks found in Spotify URL.")
        return

    click.echo(f"Found {len(spotify_tracks)} tracks in Spotify playlist/album")

    downloaded = 0
    skipped = 0
    failed = 0
    downloaded_paths = []

    for i, sp_track in enumerate(spotify_tracks, 1):
        click.echo(f"[{i}/{len(spotify_tracks)}] Searching: {sp_track.artist} - {sp_track.name}")

        # Search YouTube Music for this track
        results = search(sp_track.search_query, limit=1)

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
def web(
    host: str,
    port: int | None,
    cors_origins: str | None,
    web_playlist: str | None,
    organization_mode: str | None,
    use_primary_artist: bool | None,
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

    config = get_config()
    server_port = port or config.web_port

    click.echo(f"Starting web server at http://{host}:{server_port}")

    from kikusan.web.app import app

    uvicorn.run(app, host=host, port=server_port)


if __name__ == "__main__":
    main()
