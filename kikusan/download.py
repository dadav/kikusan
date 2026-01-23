"""Download functionality using yt-dlp."""

import logging
from pathlib import Path

import yt_dlp

from kikusan.config import DEFAULT_FILENAME_TEMPLATE
from kikusan.lyrics import get_lyrics, save_lyrics

logger = logging.getLogger(__name__)


def _get_ydl_opts(
    output_dir: Path,
    audio_format: str,
    filename_template: str,
    progress_callback: callable = None,
) -> dict:
    """Get common yt-dlp options."""
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / f"{filename_template}.%(ext)s"),
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


def _file_exists(output_dir: Path, info: dict, audio_format: str, filename_template: str) -> Path | None:
    """Check if a file with the expected name already exists."""
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


def download(
    video_id: str,
    output_dir: Path,
    audio_format: str = "opus",
    filename_template: str = DEFAULT_FILENAME_TEMPLATE,
    fetch_lyrics: bool = True,
    progress_callback: callable = None,
) -> Path:
    """
    Download a track from YouTube Music.

    Args:
        video_id: YouTube video ID
        output_dir: Directory to save the downloaded file
        audio_format: Audio format (opus, mp3, flac)
        filename_template: yt-dlp output template for filename
        fetch_lyrics: Whether to fetch and save lyrics
        progress_callback: Optional callback for progress updates

    Returns:
        Path to the downloaded audio file
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://music.youtube.com/watch?v={video_id}"

    # Extract info first to get metadata
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    title = info.get("title", "Unknown")
    artist = info.get("artist") or info.get("uploader", "Unknown")
    duration = info.get("duration", 0)

    # Check if already downloaded
    existing = _file_exists(output_dir, info, audio_format, filename_template)
    if existing:
        logger.info("Skipping (exists): %s - %s", artist, title)
        return existing

    logger.info("Downloading: %s - %s", artist, title)

    # Download the track
    ydl_opts = _get_ydl_opts(output_dir, audio_format, filename_template, progress_callback)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find the downloaded file
    audio_path = _find_downloaded_file(output_dir, info, audio_format, filename_template)

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
) -> Path | list[Path]:
    """
    Download a track or playlist from a YouTube/YouTube Music URL.

    Args:
        url: YouTube or YouTube Music URL (single track or playlist)
        output_dir: Directory to save the downloaded file(s)
        audio_format: Audio format (opus, mp3, flac)
        filename_template: yt-dlp output template for filename
        fetch_lyrics: Whether to fetch and save lyrics

    Returns:
        Path to downloaded file, or list of Paths for playlists
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract info first to check if it's a playlist
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    # Check if this is a playlist
    if info.get("_type") == "playlist" or "entries" in info:
        return _download_playlist(info, output_dir, audio_format, filename_template, fetch_lyrics)

    # Single track
    return _download_single(url, info, output_dir, audio_format, filename_template, fetch_lyrics)


def _download_single(
    url: str,
    info: dict,
    output_dir: Path,
    audio_format: str,
    filename_template: str,
    fetch_lyrics: bool,
) -> Path:
    """Download a single track."""
    title = info.get("title", "Unknown")
    artist = info.get("artist") or info.get("uploader", "Unknown")
    duration = info.get("duration", 0)

    # Check if already downloaded
    existing = _file_exists(output_dir, info, audio_format, filename_template)
    if existing:
        logger.info("Skipping (exists): %s - %s", artist, title)
        return existing

    logger.info("Downloading: %s - %s", artist, title)

    ydl_opts = _get_ydl_opts(output_dir, audio_format, filename_template)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    audio_path = _find_downloaded_file(output_dir, info, audio_format, filename_template)

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
) -> list[Path]:
    """Download all tracks from a playlist."""
    entries = info.get("entries", [])
    playlist_title = info.get("title", "Unknown Playlist")

    logger.info("Downloading playlist: %s (%d tracks)", playlist_title, len(entries))

    downloaded = []
    skipped = 0
    ydl_opts = _get_ydl_opts(output_dir, audio_format, filename_template)

    for i, entry in enumerate(entries, 1):
        if entry is None:
            continue

        video_id = entry.get("id") or entry.get("url", "").split("=")[-1]
        title = entry.get("title", "Unknown")
        artist = entry.get("artist") or entry.get("uploader", "Unknown")
        duration = entry.get("duration", 0)

        # Check if already downloaded
        existing = _file_exists(output_dir, entry, audio_format, filename_template)
        if existing:
            logger.info("[%d/%d] Skipping (exists): %s - %s", i, len(entries), artist, title)
            downloaded.append(existing)
            skipped += 1
            continue

        logger.info("[%d/%d] Downloading: %s - %s", i, len(entries), artist, title)

        try:
            url = f"https://music.youtube.com/watch?v={video_id}"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            audio_path = _find_downloaded_file(output_dir, entry, audio_format, filename_template)

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


def _find_downloaded_file(output_dir: Path, info: dict, audio_format: str, filename_template: str) -> Path | None:
    """Find the downloaded audio file in the output directory."""
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
