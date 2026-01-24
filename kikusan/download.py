"""Download functionality using yt-dlp."""

import logging
from pathlib import Path

import yt_dlp

from kikusan.config import DEFAULT_FILENAME_TEMPLATE, get_config
from kikusan.lyrics import get_lyrics, save_lyrics
from kikusan.yt_dlp_wrapper import extract_info_with_retry

logger = logging.getLogger(__name__)


def _sanitize_path_component(name: str) -> str:
    """Sanitize a string for use as a directory name."""
    # Remove characters that are invalid in filenames/paths
    invalid_chars = '<>:"|?*'
    for char in invalid_chars:
        name = name.replace(char, "")
    # Replace forward/backslash with dash
    name = name.replace("/", "-").replace("\\", "-")
    # Strip leading/trailing whitespace and dots
    name = name.strip(". ")
    return name or "Unknown"


def _get_primary_artist(artist: str) -> str:
    """Extract primary artist from multi-artist string.

    Splits on common separators and returns the first artist.

    Examples:
        "Queen, David Bowie" -> "Queen"
        "Artist feat. Guest" -> "Artist"
        "Artist & Other" -> "Artist"
        "Artist" -> "Artist"

    Args:
        artist: Full artist string (may contain multiple artists)

    Returns:
        Primary artist name
    """
    # Common separators for multi-artist strings (in priority order)
    separators = [
        " feat. ",
        " ft. ",
        " featuring ",
        " with ",
        " & ",
        ", ",
    ]

    # Try each separator and return first part if found
    for separator in separators:
        if separator in artist:
            return artist.split(separator)[0].strip()

    # No separator found, return as-is
    return artist.strip()


def _get_output_path(
    output_dir: Path,
    info: dict,
    filename_template: str,
    organization_mode: str,
    use_primary_artist: bool = False,
) -> str:
    """
    Calculate output path based on organization mode.

    Args:
        output_dir: Base download directory
        info: yt-dlp metadata dict
        filename_template: Filename template (used in flat mode)
        organization_mode: "flat" or "album"
        use_primary_artist: Extract primary artist for folder (before feat., &, etc.)

    Returns:
        Full output path template for yt-dlp
    """
    if organization_mode == "flat":
        # Current behavior: flat structure
        return str(output_dir / f"{filename_template}.%(ext)s")

    # Album mode: organize by artist/album
    artist = info.get("artist") or info.get("uploader", "Unknown Artist")

    # Extract primary artist if requested
    if use_primary_artist:
        artist = _get_primary_artist(artist)

    artist = _sanitize_path_component(artist)

    album = info.get("album")
    year = info.get("release_year")
    track_number = info.get("track_number")

    # Build path components
    path_parts = [str(output_dir), artist]

    if album:
        # We have album info
        album = _sanitize_path_component(album)
        if year:
            album_folder = f"{year} - {album}"
        else:
            album_folder = album
        path_parts.append(album_folder)

        # Build filename with optional track number
        if track_number:
            filename = f"{track_number:02d} - %(title)s.%(ext)s"
        else:
            filename = "%(title)s.%(ext)s"
    else:
        # No album info: just Artist/Track.ext
        filename = "%(title)s.%(ext)s"

    return str(Path(*path_parts) / filename)


def _get_ydl_opts(
    output_dir: Path,
    audio_format: str,
    filename_template: str,
    organization_mode: str,
    info: dict,
    progress_callback: callable = None,
    use_primary_artist: bool = False,
    cookie_file: str | None = None,
) -> dict:
    """Get common yt-dlp options."""
    # Calculate output path based on organization mode
    output_path = _get_output_path(output_dir, info, filename_template, organization_mode, use_primary_artist)

    opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "0",
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            },
            {
                "key": "EmbedThumbnail",
            },
        ],
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
    }

    # Note: cookies are now handled by yt_dlp_wrapper, not here

    if progress_callback:

        def progress_hook(d):
            """yt-dlp progress hook."""
            if d["status"] == "downloading":
                # Extract progress information
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                speed = d.get("speed", 0)
                eta = d.get("eta", 0)

                # Calculate percentage
                percent = (downloaded / total * 100) if total > 0 else 0

                # Format speed
                if speed:
                    if speed > 1024 * 1024:
                        speed_str = f"{speed / 1024 / 1024:.1f} MB/s"
                    elif speed > 1024:
                        speed_str = f"{speed / 1024:.1f} KB/s"
                    else:
                        speed_str = f"{speed:.0f} B/s"
                else:
                    speed_str = "N/A"

                # Format ETA
                if eta:
                    if eta > 3600:
                        eta_str = f"{eta // 3600}h {(eta % 3600) // 60}m"
                    elif eta > 60:
                        eta_str = f"{eta // 60}m {eta % 60}s"
                    else:
                        eta_str = f"{eta}s"
                else:
                    eta_str = "N/A"

                progress_callback(
                    {
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                        "percent": percent,
                        "speed": speed_str,
                        "eta": eta_str,
                    }
                )

        opts["progress_hooks"] = [progress_hook]

    return opts


def _compute_filename(info: dict, filename_template: str) -> str:
    """Compute the expected filename from metadata using yt-dlp's template."""
    # Use yt-dlp's template rendering
    with yt_dlp.YoutubeDL({"outtmpl": filename_template}) as ydl:
        filename = ydl.prepare_filename(info)
    return yt_dlp.utils.sanitize_filename(filename)


def _file_exists(
    output_dir: Path,
    info: dict,
    audio_format: str,
    filename_template: str,
    organization_mode: str,
    use_primary_artist: bool = False,
) -> Path | None:
    """Check if a file with the expected name already exists."""
    if organization_mode == "flat":
        # Existing flat mode logic
        expected_name = _compute_filename(info, filename_template)

        for ext in [audio_format, "opus", "mp3", "m4a", "flac"]:
            # Check exact match
            exact_path = output_dir / f"{expected_name}.{ext}"
            if exact_path.exists():
                return exact_path

            # Check with glob for partial matches (handles long titles)
            matches = list(output_dir.glob(f"{expected_name[:50]}*.{ext}"))
            if matches:
                return matches[0]

        return None

    # Album mode: search in artist/album subdirectories
    artist = info.get("artist") or info.get("uploader", "Unknown Artist")
    if use_primary_artist:
        artist = _get_primary_artist(artist)
    artist = _sanitize_path_component(artist)
    artist_dir = output_dir / artist

    if not artist_dir.exists():
        return None

    # Search for the file recursively in artist directory
    title = info.get("title", "Unknown")
    for ext in [audio_format, "opus", "mp3", "m4a", "flac"]:
        # Try with and without track number
        for file_path in artist_dir.rglob(f"*{title}*.{ext}"):
            if file_path.is_file():
                return file_path

    return None


def download(
    video_id: str,
    output_dir: Path,
    audio_format: str = "opus",
    filename_template: str = DEFAULT_FILENAME_TEMPLATE,
    fetch_lyrics: bool = True,
    progress_callback: callable = None,
    organization_mode: str = "flat",
    use_primary_artist: bool = False,
    cookie_file: str | None = None,
) -> Path:
    """
    Download a track from YouTube Music.

    Args:
        video_id: YouTube video ID
        output_dir: Directory to save the downloaded file
        audio_format: Audio format (opus, mp3, flac)
        filename_template: yt-dlp output template for filename (flat mode only)
        fetch_lyrics: Whether to fetch and save lyrics
        progress_callback: Optional callback for progress updates
        organization_mode: "flat" or "album" organization
        use_primary_artist: Extract primary artist for folder (before feat., &, etc.)

    Returns:
        Path to the downloaded audio file
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://music.youtube.com/watch?v={video_id}"

    # Extract info first to get metadata
    ydl_opts_info = {"quiet": True, "no_warnings": True}
    info = extract_info_with_retry(
        ydl_opts=ydl_opts_info,
        url=url,
        download=False,
        cookie_file=cookie_file,
        config=get_config(),
    )

    title = info.get("title", "Unknown")
    artist = info.get("artist") or info.get("uploader", "Unknown")
    duration = info.get("duration", 0)

    # Check if already downloaded
    existing = _file_exists(output_dir, info, audio_format, filename_template, organization_mode, use_primary_artist)
    if existing:
        logger.info("Skipping (exists): %s - %s", artist, title)
        return existing

    logger.info("Downloading: %s - %s", artist, title)

    # Download the track
    ydl_opts = _get_ydl_opts(
        output_dir, audio_format, filename_template, organization_mode, info, progress_callback, use_primary_artist, cookie_file
    )
    extract_info_with_retry(
        ydl_opts=ydl_opts,
        url=url,
        download=True,
        cookie_file=cookie_file,
        config=get_config(),
    )

    # Find the downloaded file
    audio_path = _find_downloaded_file(output_dir, info, audio_format, filename_template, organization_mode, use_primary_artist)

    if audio_path and fetch_lyrics:
        lyrics = get_lyrics(title, artist, duration)
        if lyrics:
            save_lyrics(lyrics, audio_path)

    return audio_path


def download_url(
    url: str,
    output_dir: Path,
    audio_format: str = "opus",
    filename_template: str = DEFAULT_FILENAME_TEMPLATE,
    fetch_lyrics: bool = True,
    organization_mode: str = "flat",
    use_primary_artist: bool = False,
    cookie_file: str | None = None,
) -> Path | list[Path]:
    """
    Download a track or playlist from a YouTube/YouTube Music URL.

    Args:
        url: YouTube or YouTube Music URL (single track or playlist)
        output_dir: Directory to save the downloaded file(s)
        audio_format: Audio format (opus, mp3, flac)
        filename_template: yt-dlp output template for filename
        fetch_lyrics: Whether to fetch and save lyrics
        organization_mode: "flat" or "album" organization
        use_primary_artist: Extract primary artist for folder (before feat., &, etc.)

    Returns:
        Path to downloaded file, or list of Paths for playlists
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract info first to check if it's a playlist
    ydl_opts_info = {"quiet": True, "no_warnings": True}
    info = extract_info_with_retry(
        ydl_opts=ydl_opts_info,
        url=url,
        download=False,
        cookie_file=cookie_file,
        config=get_config(),
    )

    # Check if this is a playlist
    if info.get("_type") == "playlist" or "entries" in info:
        return _download_playlist(info, output_dir, audio_format, filename_template, fetch_lyrics, organization_mode, use_primary_artist, cookie_file)

    # Single track
    return _download_single(url, info, output_dir, audio_format, filename_template, fetch_lyrics, organization_mode, use_primary_artist, cookie_file)


def _download_single(
    url: str,
    info: dict,
    output_dir: Path,
    audio_format: str,
    filename_template: str,
    fetch_lyrics: bool,
    organization_mode: str,
    use_primary_artist: bool = False,
    cookie_file: str | None = None,
) -> Path:
    """Download a single track."""
    title = info.get("title", "Unknown")
    artist = info.get("artist") or info.get("uploader", "Unknown")
    duration = info.get("duration", 0)

    # Check if already downloaded
    existing = _file_exists(output_dir, info, audio_format, filename_template, organization_mode, use_primary_artist)
    if existing:
        logger.info("Skipping (exists): %s - %s", artist, title)
        return existing

    logger.info("Downloading: %s - %s", artist, title)

    ydl_opts = _get_ydl_opts(output_dir, audio_format, filename_template, organization_mode, info, None, use_primary_artist, cookie_file)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    audio_path = _find_downloaded_file(output_dir, info, audio_format, filename_template, organization_mode, use_primary_artist)

    if audio_path and fetch_lyrics:
        lyrics = get_lyrics(title, artist, duration)
        if lyrics:
            save_lyrics(lyrics, audio_path)

    return audio_path


def _download_playlist(
    info: dict,
    output_dir: Path,
    audio_format: str,
    filename_template: str,
    fetch_lyrics: bool,
    organization_mode: str,
    use_primary_artist: bool = False,
    cookie_file: str | None = None,
) -> list[Path]:
    """Download all tracks from a playlist."""
    entries = info.get("entries", [])
    playlist_title = info.get("title", "Unknown Playlist")

    logger.info("Downloading playlist: %s (%d tracks)", playlist_title, len(entries))

    downloaded = []
    skipped = 0

    for i, entry in enumerate(entries, 1):
        if entry is None:
            continue

        video_id = entry.get("id") or entry.get("url", "").split("=")[-1]
        title = entry.get("title", "Unknown")
        artist = entry.get("artist") or entry.get("uploader", "Unknown")
        duration = entry.get("duration", 0)

        # Check if already downloaded
        existing = _file_exists(output_dir, entry, audio_format, filename_template, organization_mode, use_primary_artist)
        if existing:
            logger.info("[%d/%d] Skipping (exists): %s - %s", i, len(entries), artist, title)
            downloaded.append(existing)
            skipped += 1
            continue

        logger.info("[%d/%d] Downloading: %s - %s", i, len(entries), artist, title)

        try:
            url = f"https://music.youtube.com/watch?v={video_id}"
            ydl_opts = _get_ydl_opts(output_dir, audio_format, filename_template, organization_mode, entry, None, use_primary_artist, cookie_file)
            extract_info_with_retry(
                ydl_opts=ydl_opts,
                url=url,
                download=True,
                cookie_file=cookie_file,
                config=get_config(),
            )

            audio_path = _find_downloaded_file(output_dir, entry, audio_format, filename_template, organization_mode, use_primary_artist)

            if audio_path:
                downloaded.append(audio_path)
                if fetch_lyrics:
                    lyrics = get_lyrics(title, artist, duration)
                    if lyrics:
                        save_lyrics(lyrics, audio_path)

        except Exception as e:
            logger.warning("Failed to download %s: %s", title, e)

    new_downloads = len(downloaded) - skipped
    logger.info("Downloaded %d new tracks (%d skipped)", new_downloads, skipped)
    return downloaded


def _find_downloaded_file(
    output_dir: Path,
    info: dict,
    audio_format: str,
    filename_template: str,
    organization_mode: str,
    use_primary_artist: bool = False,
) -> Path | None:
    """Find the downloaded audio file in the output directory."""
    if organization_mode == "flat":
        # Existing flat mode logic
        expected_name = _compute_filename(info, filename_template)

        for ext in [audio_format, "opus", "m4a", "webm"]:
            # Check exact match first
            exact_path = output_dir / f"{expected_name}.{ext}"
            if exact_path.exists():
                return exact_path

            # Check with glob for partial matches
            matches = list(output_dir.glob(f"{expected_name[:50]}*.{ext}"))
            if matches:
                return matches[0]

        # Fallback: return most recently modified audio file
        audio_extensions = ["opus", "mp3", "m4a", "flac", "webm"]
        all_audio = []
        for ext in audio_extensions:
            all_audio.extend(output_dir.glob(f"*.{ext}"))

        if all_audio:
            return max(all_audio, key=lambda p: p.stat().st_mtime)

        return None

    # Album mode: search in artist/album subdirectories
    artist = info.get("artist") or info.get("uploader", "Unknown Artist")
    if use_primary_artist:
        artist = _get_primary_artist(artist)
    artist = _sanitize_path_component(artist)
    artist_dir = output_dir / artist

    if not artist_dir.exists():
        return None

    # Get all audio files in artist directory
    audio_extensions = ["opus", "mp3", "m4a", "flac", "webm"]
    all_audio = []
    for ext in audio_extensions:
        all_audio.extend(artist_dir.rglob(f"*.{ext}"))

    # Return most recently modified file (should be the just-downloaded one)
    if all_audio:
        return max(all_audio, key=lambda p: p.stat().st_mtime)

    return None
